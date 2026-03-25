"""Debug: find why some stops map to 0m."""
import json, math, os

def haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(d_lon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

data_path = os.path.join(os.path.dirname(__file__), "data", "route_network.json")
with open(data_path, "r", encoding="utf-8") as f:
    data = json.load(f)

edges = data["edges"]["gidis"]
stops = data["stops"]["gidis"]

# Count segments and build segment list
segments = []
cum = 0.0
for edge in edges:
    geom = edge["geometry"]
    for pi in range(len(geom) - 1):
        lat1, lng1 = geom[pi]
        lat2, lng2 = geom[pi + 1]
        dist = haversine(lat1, lng1, lat2, lng2)
        if dist < 0.1:
            continue
        segments.append({
            "start_meter": cum, "length": dist,
            "start_lat": lat1, "start_lng": lng1,
            "end_lat": lat2, "end_lng": lng2,
        })
        cum += dist

print(f"Toplam segment: {len(segments)}")
print(f"Toplam uzunluk: {cum:.0f}m")
print(f"Step (coarse): {max(1, len(segments) // 200)}")
print()

# For each stop, find distance to nearest segment
for i, stop in enumerate(stops):
    slat, slng = stop["latitude"], stop["longitude"]
    best_d = float("inf")
    best_m = 0.0
    best_seg_idx = 0
    for si, seg in enumerate(segments):
        d = haversine(slat, slng, seg["start_lat"], seg["start_lng"])
        if d < best_d:
            best_d = d
            best_m = seg["start_meter"]
            best_seg_idx = si
    
    status = "OK" if best_m > 0 else "*** 0m ***"
    print(f"  {i:2d}. {stop['name'][:35]:35s}  nearest_seg={best_seg_idx:4d}  dist={best_d:.0f}m  meter={best_m:.0f}m  {status}")
