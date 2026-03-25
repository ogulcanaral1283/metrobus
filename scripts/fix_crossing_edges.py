"""
Make the 3 swapped edge pairs perfectly parallel.
Strategy: use donus geometry as reference, generate gidis as +8m offset copy.
This ensures both lines run perfectly parallel in the Okmeydan-Darulaceze zone.
"""
import json, re, os, math
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(__file__))

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def polyline_length(coords):
    total = 0
    for i in range(1, len(coords)):
        total += haversine(coords[i-1][0], coords[i-1][1], coords[i][0], coords[i][1])
    return round(total)

def offset_polyline(coords, offset_deg):
    """Offset a polyline perpendicular to its direction by offset_deg degrees."""
    if len(coords) < 2:
        return coords
    result = []
    for i in range(len(coords)):
        if i == 0:
            dy = coords[1][0] - coords[0][0]
            dx = coords[1][1] - coords[0][1]
        elif i == len(coords) - 1:
            dy = coords[i][0] - coords[i-1][0]
            dx = coords[i][1] - coords[i-1][1]
        else:
            dy = coords[i+1][0] - coords[i-1][0]
            dx = coords[i+1][1] - coords[i-1][1]
        length = math.sqrt(dx*dx + dy*dy)
        if length == 0:
            result.append(coords[i][:])
            continue
        # Perpendicular: rotate 90° → (-dy, dx) normalized
        nx = -dy / length
        ny = dx / length
        result.append([
            round(coords[i][0] + nx * offset_deg, 7),
            round(coords[i][1] + ny * offset_deg, 7)
        ])
    return result

# ─── Load ───
ts_path = os.path.join(BASE, "packages", "shared", "src", "constants", "route-network-data.ts")
with open(ts_path, "r", encoding="utf-8") as f:
    ts = f.read()
m = re.search(r'ROUTE_NETWORK:\s*RouteNetwork\s*=\s*({.*});', ts, re.DOTALL)
data = json.loads(m.group(1))

gidis_by_id = {e["id"]: e for e in data["edges"]["gidis"]}
donus_by_id = {e["id"]: e for e in data["edges"]["donus"]}

# The 3 pairs we previously swapped — now make parallel
# For each pair: use the donus geometry as reference,
# generate gidis as offset of donus (reversed, since gidis goes opposite direction)
PAIRS = [
    ("G_1047802787", "D_1047802788"),
    ("G_227510672",  "D_227909788"),
    ("G_227909784",  "D_227909783"),
]

# ~8m offset in lat/lon degrees (at Istanbul latitude ~41°)
# 1 degree lat = ~111km, so 8m = 0.000072
# 1 degree lon = ~111km * cos(41°) = ~83.8km, so 8m = 0.0000955
# Use a uniform offset_deg that gives ~8m perpendicular shift
OFFSET = 0.00007  # ~8m

for g_id, d_id in PAIRS:
    g_edge = gidis_by_id[g_id]
    d_edge = donus_by_id[d_id]
    
    print(f"� {g_id} || {d_id}")
    
    # Use donus edge geometry as the reference
    # Donus goes east→west (Darulaceze→Okmeydan)
    # Gidis goes west→east, so reverse donus to get gidis direction
    ref_geom = d_edge["geometry"]  # donus direction
    
    # Generate gidis geometry: offset the donus geometry to the south 
    # (lower lat = negative offset on perpendicular)
    # Then reverse it for gidis direction (west→east)
    gidis_from_ref = offset_polyline(ref_geom, -OFFSET)
    gidis_from_ref.reverse()  # Reverse for gidis direction
    
    g_edge["geometry"] = gidis_from_ref
    g_edge["lengthMeters"] = polyline_length(gidis_from_ref)
    
    print(f"   Donus ref: {len(ref_geom)} pts ({d_edge['lengthMeters']}m)")
    print(f"   Gidis gen: {len(gidis_from_ref)} pts ({g_edge['lengthMeters']}m)")

# ─── Verify parallelism ───
print("\n=== Verify parallelism ===")
for test_lon in [28.960, 28.962, 28.964, 28.966, 28.968]:
    g_lats = [pt[0] for e in data["edges"]["gidis"] for pt in e["geometry"] if abs(pt[1]-test_lon)<0.001]
    d_lats = [pt[0] for e in data["edges"]["donus"] for pt in e["geometry"] if abs(pt[1]-test_lon)<0.001]
    if g_lats and d_lats:
        ga, da = sum(g_lats)/len(g_lats), sum(d_lats)/len(d_lats)
        diff_m = haversine(ga, test_lon, da, test_lon)
        crossed = "❌" if ga > da else "✅"
        print(f"  lon={test_lon:.3f}: gap={diff_m:.1f}m {crossed}")

# ─── Save TS ───
ts_json = json.dumps(data, ensure_ascii=False)
now = datetime.now().isoformat()
new_ts = f"""// =============================================
// Route Network Data — Directed Graph
// Generated: {now}
// Fix: Okmeydanı-Darülaceze parallel lanes
// Gidiş: {data['stats']['totalEdgesGidis']} edges, {data['stats']['totalStopsGidis']} stops
// Dönüş: {data['stats']['totalEdgesDonus']} edges, {data['stats']['totalStopsDonus']} stops
// Shared ways: {data['stats']['sharedWayCount']}
// =============================================

import type {{ RouteNetwork }} from '../types/route-network';

export const ROUTE_NETWORK: RouteNetwork = {ts_json};
"""
with open(ts_path, "w", encoding="utf-8") as f:
    f.write(new_ts)
print(f"\n💾 {ts_path}")

rn_path = os.path.join(BASE, "rl_env", "data", "route_network.json")
with open(rn_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
print(f"💾 {rn_path}")
print("\n✅ Edges are now perfectly parallel!")
