"""Find edges causing line crossing between Okmeydan and Darulaceze."""
import json, re, os

BASE = os.path.dirname(os.path.dirname(__file__))
ts_path = os.path.join(BASE, "packages", "shared", "src", "constants", "route-network-data.ts")

with open(ts_path, "r", encoding="utf-8") as f:
    ts = f.read()
m = re.search(r'ROUTE_NETWORK:\s*RouteNetwork\s*=\s*({.*});', ts, re.DOTALL)
data = json.loads(m.group(1))

# Area of interest: Okmeydan-Darulaceze corridor
# Okmeydan: ~41.056, 28.961  |  Darulaceze: ~41.062, 28.968
LAT_MIN, LAT_MAX = 41.055, 41.069
LON_MIN, LON_MAX = 28.958, 28.978

def edge_in_area(edge):
    for pt in edge["geometry"]:
        if LAT_MIN <= pt[0] <= LAT_MAX and LON_MIN <= pt[1] <= LON_MAX:
            return True
    return False

def avg_coord(geom):
    lats = [p[0] for p in geom]
    lons = [p[1] for p in geom]
    return sum(lats)/len(lats), sum(lons)/len(lons)

print("=== GIDIS edges in Okmeydan-Darulaceze area ===")
for e in data["edges"]["gidis"]:
    if edge_in_area(e):
        g = e["geometry"]
        al, ao = avg_coord(g)
        print(f"  seq={e['sequenceIndex']:3d} id={e['id']:25s} shared={str(e['isSharedGeometry']):5s} "
              f"pts={len(g):3d} len={e['lengthMeters']:5d}m "
              f"avg=[{al:.5f},{ao:.5f}] "
              f"start=[{g[0][0]:.5f},{g[0][1]:.5f}] end=[{g[-1][0]:.5f},{g[-1][1]:.5f}]")

print()
print("=== DONUS edges in Okmeydan-Darulaceze area ===")
for e in data["edges"]["donus"]:
    if edge_in_area(e):
        g = e["geometry"]
        al, ao = avg_coord(g)
        print(f"  seq={e['sequenceIndex']:3d} id={e['id']:25s} shared={str(e['isSharedGeometry']):5s} "
              f"pts={len(g):3d} len={e['lengthMeters']:5d}m "
              f"avg=[{al:.5f},{ao:.5f}] "
              f"start=[{g[0][0]:.5f},{g[0][1]:.5f}] end=[{g[-1][0]:.5f},{g[-1][1]:.5f}]")

# Now compare lat positions of gidis vs donus edges at same longitude
# The crossing means gidis should be south (lower lat) but is north (higher lat) at some point
print()
print("=== Crossing analysis ===")
print("For each longitude slice, compare gidis vs donus average latitude:")
print("  If gidis_lat > donus_lat = CROSSED (gidis should be south/lower)")

# Sample some longitudes
for test_lon in [28.960, 28.962, 28.964, 28.966, 28.968, 28.970, 28.972, 28.974]:
    g_lats = []
    d_lats = []
    for e in data["edges"]["gidis"]:
        for pt in e["geometry"]:
            if abs(pt[1] - test_lon) < 0.001:
                g_lats.append(pt[0])
    for e in data["edges"]["donus"]:
        for pt in e["geometry"]:
            if abs(pt[1] - test_lon) < 0.001:
                d_lats.append(pt[0])
    if g_lats and d_lats:
        g_avg = sum(g_lats)/len(g_lats)
        d_avg = sum(d_lats)/len(d_lats)
        crossed = "❌ CROSSED" if g_avg > d_avg else "✅ OK"
        print(f"  lon={test_lon:.3f}: gidis_lat={g_avg:.6f} donus_lat={d_avg:.6f} diff={g_avg-d_avg:.6f} {crossed}")
