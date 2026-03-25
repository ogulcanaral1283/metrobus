"""
Replace OSM edge geometry with IETT GeoJSON route data.
Generates new route_network.json and route-network-data.ts
using 34G_G_D0 (gidis) and 34G_D_D0 (donus) LineStrings.
"""
import json
import math
import os
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(__file__))


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def polyline_length(coords):
    """Total length in meters for [[lat,lon], ...] list."""
    total = 0
    for i in range(1, len(coords)):
        total += haversine(coords[i - 1][0], coords[i - 1][1],
                           coords[i][0], coords[i][1])
    return total


def nearest_point_on_polyline(polyline, lat, lon):
    """
    Find the index of the nearest point in polyline [[lat,lon],...] to (lat,lon).
    Returns (best_idx, best_dist).
    """
    best_idx = 0
    best_dist = float("inf")
    for i, (plat, plon) in enumerate(polyline):
        d = haversine(lat, lon, plat, plon)
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx, best_dist


# ─── Load data ───
with open(os.path.join(BASE, "data", "metrobus_routes.geojson"), "r",
          encoding="utf-8") as f:
    routes = json.load(f)

with open(os.path.join(BASE, "data", "metrobus_34G_stops.json"), "r",
          encoding="utf-8") as f:
    iett_stops = json.load(f)

# ─── Find 34G main routes ───
gidis_geojson = None
donus_geojson = None
for feat in routes["features"]:
    props = feat.get("properties", {})
    guz = props.get("GUZERGAH_KODU", "")
    if guz == "34G_G_D0":
        gidis_geojson = feat
    elif guz == "34G_D_D0":
        donus_geojson = feat

if not gidis_geojson or not donus_geojson:
    # Try finding by HAT_KODU=34G + YON + widest coverage
    for feat in routes["features"]:
        props = feat.get("properties", {})
        if props.get("HAT_KODU") == "34G":
            yon = props.get("YON", "")
            guz = props.get("GUZERGAH_KODU", "")
            coords = feat["geometry"]["coordinates"]
            if yon == "GİDİŞ" and (gidis_geojson is None or
                                   len(coords) > len(
                                       gidis_geojson["geometry"]["coordinates"])):
                gidis_geojson = feat
            elif yon == "DÖNÜŞ" and (donus_geojson is None or
                                     len(coords) > len(
                                         donus_geojson["geometry"]["coordinates"])):
                donus_geojson = feat

print(f"Gidis route: {gidis_geojson['properties']['GUZERGAH_KODU']}")
print(f"  Coords: {len(gidis_geojson['geometry']['coordinates'])}")
print(f"Donus route: {donus_geojson['properties']['GUZERGAH_KODU']}")
print(f"  Coords: {len(donus_geojson['geometry']['coordinates'])}")

# ─── Convert GeoJSON [lon,lat] to [lat,lon] format ───
gidis_polyline = [[c[1], c[0]] for c in gidis_geojson["geometry"]["coordinates"]]
donus_polyline = [[c[1], c[0]] for c in donus_geojson["geometry"]["coordinates"]]

print(f"\nGidis polyline: {len(gidis_polyline)} points, "
      f"{polyline_length(gidis_polyline):.0f}m")
print(f"Donus polyline: {len(donus_polyline)} points, "
      f"{polyline_length(donus_polyline):.0f}m")

# ─── Get station coordinates for each direction ───
g_stops = sorted([s for s in iett_stops if s["YON"] == "G"],
                 key=lambda x: int(x["SIRANO"]))
d_stops = sorted([s for s in iett_stops if s["YON"] == "D"],
                 key=lambda x: int(x["SIRANO"]))

print(f"\nIETT Gidis stops: {len(g_stops)} (G: {g_stops[0]['DURAKADI']} → {g_stops[-1]['DURAKADI']})")
print(f"IETT Donus stops: {len(d_stops)} (D: {d_stops[0]['DURAKADI']} → {d_stops[-1]['DURAKADI']})")


def build_edges(polyline, stops, direction_code, direction_name):
    """
    Split polyline into edges between consecutive station pairs.
    Returns (edges_list, stops_list).
    """
    # Map each station to nearest polyline point
    station_indices = []
    for s in stops:
        slat = float(s["YKOORDINATI"])
        slon = float(s["XKOORDINATI"])
        idx, dist = nearest_point_on_polyline(polyline, slat, slon)
        station_indices.append({
            "name": s["DURAKADI"],
            "code": s["DURAKKODU"],
            "lat": slat,
            "lon": slon,
            "poly_idx": idx,
            "dist": dist,
        })
        if dist > 200:
            print(f"  ⚠️ {s['DURAKADI']}: {dist:.0f}m from polyline")

    # Ensure indices are monotonically increasing
    for i in range(1, len(station_indices)):
        if station_indices[i]["poly_idx"] <= station_indices[i - 1]["poly_idx"]:
            # Force it to be at least one ahead
            station_indices[i]["poly_idx"] = station_indices[i - 1]["poly_idx"] + 1
            if station_indices[i]["poly_idx"] >= len(polyline):
                station_indices[i]["poly_idx"] = len(polyline) - 1

    # Build edges between consecutive stations
    edges = []
    network_stops = []
    prefix = "G_" if direction_code == "gidis" else "D_"

    for i in range(len(station_indices) - 1):
        s1 = station_indices[i]
        s2 = station_indices[i + 1]
        start_idx = s1["poly_idx"]
        end_idx = s2["poly_idx"]

        # Extract geometry segment
        segment = polyline[start_idx:end_idx + 1]
        if len(segment) < 2:
            segment = [polyline[start_idx], polyline[min(end_idx, len(polyline) - 1)]]

        edge_id = f"{prefix}IETT_{i:03d}"
        edge_length = polyline_length(segment)

        edges.append({
            "id": edge_id,
            "osmWayId": 0,  # No OSM reference
            "direction": direction_code,
            "geometry": segment,
            "sequenceIndex": i,
            "isSharedGeometry": False,
            "lengthMeters": round(edge_length),
        })

    # Build stops
    for i, si in enumerate(station_indices):
        if i == 0:
            edge_idx = 0
            pos = 0.0
        elif i == len(station_indices) - 1:
            edge_idx = len(edges) - 1
            pos = 1.0
        else:
            edge_idx = i - 1
            pos = 1.0

        stop_prefix = "GS_" if direction_code == "gidis" else "DS_"
        network_stops.append({
            "id": f"{stop_prefix}IETT_{si['code']}",
            "osmId": int(si["code"]),
            "name": si["name"],
            "direction": direction_code,
            "latitude": si["lat"],
            "longitude": si["lon"],
            "edgeId": edges[edge_idx]["id"] if edges else "",
            "positionAlongEdge": round(pos, 4),
        })

    total_len = sum(e["lengthMeters"] for e in edges)
    print(f"\n{direction_name}: {len(edges)} edges, {len(network_stops)} stops, "
          f"{total_len}m total")

    return edges, network_stops


print("\n--- Building gidis edges ---")
gidis_edges, gidis_stops_net = build_edges(
    gidis_polyline, g_stops, "gidis", "Gidis")

print("\n--- Building donus edges ---")
donus_edges, donus_stops_net = build_edges(
    donus_polyline, d_stops, "donus", "Donus")

# ─── Assemble route network ───
route_network = {
    "edges": {
        "gidis": gidis_edges,
        "donus": donus_edges,
    },
    "stops": {
        "gidis": gidis_stops_net,
        "donus": donus_stops_net,
    },
    "sharedWayIds": [],
    "stats": {
        "totalEdgesGidis": len(gidis_edges),
        "totalEdgesDonus": len(donus_edges),
        "totalStopsGidis": len(gidis_stops_net),
        "totalStopsDonus": len(donus_stops_net),
        "sharedWayCount": 0,
        "totalLengthGidisMeters": sum(e["lengthMeters"] for e in gidis_edges),
        "totalLengthDonusMeters": sum(e["lengthMeters"] for e in donus_edges),
    },
}

# ─── Save route_network.json ───
rn_path = os.path.join(BASE, "rl_env", "data", "route_network.json")
with open(rn_path, "w", encoding="utf-8") as f:
    json.dump(route_network, f, ensure_ascii=False)
print(f"\n💾 Saved: {rn_path}")

# ─── Generate route-network-data.ts ───
ts_path = os.path.join(BASE, "packages", "shared", "src", "constants",
                       "route-network-data.ts")
ts_json = json.dumps(route_network, ensure_ascii=False)
now = datetime.now().isoformat()
ts_content = f"""// =============================================
// Route Network Data — İBB/İETT Resmi Güzergah
// Generated: {now}
// Kaynak: İETT Hat Güzergahları GeoJSON (data.ibb.gov.tr)
// Gidiş: {len(gidis_edges)} edges, {len(gidis_stops_net)} stops
// Dönüş: {len(donus_edges)} edges, {len(donus_stops_net)} stops
// =============================================

import type {{ RouteNetwork }} from '../types/route-network';

export const ROUTE_NETWORK: RouteNetwork = {ts_json};
"""
with open(ts_path, "w", encoding="utf-8") as f:
    f.write(ts_content)
print(f"💾 Saved: {ts_path}")

print(f"\n{'=' * 60}")
print(f"  DONE — İBB/İETT resmi güzergah verisi uygulandı")
print(f"  Gidiş: {len(gidis_edges)} edge, {len(gidis_stops_net)} durak, "
      f"{route_network['stats']['totalLengthGidisMeters']}m")
print(f"  Dönüş: {len(donus_edges)} edge, {len(donus_stops_net)} durak, "
      f"{route_network['stats']['totalLengthDonusMeters']}m")
print(f"{'=' * 60}")
