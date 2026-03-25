"""
Regenerate route_network.json from the route-network-data.ts (the original OSM data).
Then update just the stop coordinates with IETT data.
"""
import json
import os
import re
import math

BASE = os.path.dirname(os.path.dirname(__file__))

# Extract JSON from TypeScript file
ts_path = os.path.join(BASE, "packages", "shared", "src", "constants",
                       "route-network-data.ts")
with open(ts_path, "r", encoding="utf-8") as f:
    ts_content = f.read()

# Find the JSON object after "ROUTE_NETWORK: RouteNetwork = "
match = re.search(r'ROUTE_NETWORK:\s*RouteNetwork\s*=\s*({.*});', ts_content, re.DOTALL)
if not match:
    print("ERROR: Could not find ROUTE_NETWORK in TS file")
    exit(1)

route_data = json.loads(match.group(1))
print(f"Loaded from TS: {route_data['stats']['totalEdgesGidis']} gidis edges, "
      f"{route_data['stats']['totalEdgesDonus']} donus edges")
print(f"  Gidis stops: {route_data['stats']['totalStopsGidis']}")
print(f"  Donus stops: {route_data['stats']['totalStopsDonus']}")

# ─── Now update stop coordinates with IETT data ───
iett_path = os.path.join(BASE, "data", "metrobus_34G_stops.json")
with open(iett_path, "r", encoding="utf-8") as f:
    iett_data = json.load(f)

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

g_iett = sorted([s for s in iett_data if s["YON"] == "G"], key=lambda x: int(x["SIRANO"]))
d_iett = sorted([s for s in iett_data if s["YON"] == "D"], key=lambda x: int(x["SIRANO"]))

def update_stops(our_stops, iett_stops):
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
            stop["latitude"] = float(ist["YKOORDINATI"])
            stop["longitude"] = float(ist["XKOORDINATI"])
            iett_used.add(best_idx)
            updated += 1
    return updated

g_upd = update_stops(route_data["stops"]["gidis"], g_iett)
d_upd = update_stops(route_data["stops"]["donus"], d_iett)
print(f"\nUpdated gidis stops: {g_upd}/{len(route_data['stops']['gidis'])}")
print(f"Updated donus stops: {d_upd}/{len(route_data['stops']['donus'])}")

# ─── Save route_network.json ───
rn_path = os.path.join(BASE, "rl_env", "data", "route_network.json")
with open(rn_path, "w", encoding="utf-8") as f:
    json.dump(route_data, f, ensure_ascii=False)
print(f"\n💾 Saved: {rn_path}")
print("  OSM edge geometry preserved + IETT stop coordinates applied")
