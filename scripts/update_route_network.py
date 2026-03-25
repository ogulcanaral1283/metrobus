"""
Update route_network.json stop coordinates with official IETT data.
Keeps the edge geometry (OSM paths) intact but updates stop lat/lng.
"""
import json
import math
import os

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# Load files
base = os.path.dirname(os.path.dirname(__file__))

with open(os.path.join(base, "data", "metrobus_34G_stops.json"), "r", encoding="utf-8") as f:
    iett_data = json.load(f)

route_path = os.path.join(base, "rl_env", "data", "route_network.json")
with open(route_path, "r", encoding="utf-8") as f:
    route = json.load(f)

# IETT directions
# D = Söğütlüçeşme → Beylikdüzü (east to west) = our "donus"
# G = Beylikdüzü → Söğütlüçeşme (west to east) = our "gidis"
iett_g = sorted([s for s in iett_data if s["YON"] == "G"], key=lambda x: int(x["SIRANO"]))
iett_d = sorted([s for s in iett_data if s["YON"] == "D"], key=lambda x: int(x["SIRANO"]))

print(f"IETT G (gidis): {len(iett_g)} stops")
print(f"IETT D (donus): {len(iett_d)} stops")
print(f"Route gidis: {len(route['stops']['gidis'])} stops")
print(f"Route donus: {len(route['stops']['donus'])} stops")


def update_stops(our_stops, iett_stops, direction_name):
    """Match and update coordinates by nearest distance."""
    updated = 0
    iett_used = set()

    for stop in our_stops:
        best_dist = float("inf")
        best_idx = -1
        for i, ist in enumerate(iett_stops):
            if i in iett_used:
                continue
            ilat = float(ist["YKOORDINATI"])
            ilon = float(ist["XKOORDINATI"])
            d = haversine(stop["latitude"], stop["longitude"], ilat, ilon)
            if d < best_dist:
                best_dist = d
                best_idx = i

        if best_dist < 1000 and best_idx >= 0:
            ist = iett_stops[best_idx]
            old_lat = stop["latitude"]
            old_lon = stop["longitude"]
            stop["latitude"] = float(ist["YKOORDINATI"])
            stop["longitude"] = float(ist["XKOORDINATI"])
            iett_used.add(best_idx)
            updated += 1
            print(f"  ✅ {stop['name']:35s} drift={best_dist:6.1f}m  ({old_lat:.6f},{old_lon:.6f}) → ({stop['latitude']:.6f},{stop['longitude']:.6f})")
        else:
            print(f"  ❌ {stop['name']:35s} no match (nearest={best_dist:.0f}m)")

    return updated


print(f"\n--- Updating gidis stops ---")
g_updated = update_stops(route["stops"]["gidis"], iett_g, "gidis")
print(f"Updated: {g_updated}/{len(route['stops']['gidis'])}")

print(f"\n--- Updating donus stops ---")
d_updated = update_stops(route["stops"]["donus"], iett_d, "donus")
print(f"Updated: {d_updated}/{len(route['stops']['donus'])}")

# Save updated route
with open(route_path, "w", encoding="utf-8") as f:
    json.dump(route, f, ensure_ascii=False)

print(f"\n💾 Saved updated route_network.json")
print(f"Total updates: {g_updated + d_updated}")
