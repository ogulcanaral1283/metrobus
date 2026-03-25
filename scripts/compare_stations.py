"""
Compare IETT official station data with current OSM-based stations.
Then generate updated stations.ts and route_network.json with IETT coordinates.
"""
import json
import os
import math

# ─── Load IETT Data ───
iett_path = os.path.join(os.path.dirname(__file__), "..", "data", "metrobus_34G_stops.json")
with open(iett_path, "r", encoding="utf-8") as f:
    iett_data = json.load(f)

d_stops = sorted([s for s in iett_data if s["YON"] == "D"], key=lambda x: int(x["SIRANO"]))
g_stops = sorted([s for s in iett_data if s["YON"] == "G"], key=lambda x: int(x["SIRANO"]))

# IETT "D" direction: Söğütlüçeşme(1) → Beylikdüzü Son Durak(44)
# IETT "G" direction: B.SONDURAK(1) → Söğütlüçeşme(44)
# Our system "east" = TÜYAP/Beylikdüzü → Söğütlüçeşme (batıdan doğuya)
# So IETT "D" is reverse of our "east" and IETT "G" matches our "east"

# For "east" (gidis = batıdan doğuya), we reverse IETT "D" stops
# But actually, IETT "G" goes Beylikduzu->Sogutlucesme which IS our "east" direction
# Let's check:
print("=" * 70)
print("  IETT D direction (first→last):", d_stops[0]["DURAKADI"], "→", d_stops[-1]["DURAKADI"])
print("  IETT G direction (first→last):", g_stops[0]["DURAKADI"], "→", g_stops[-1]["DURAKADI"])
print("=" * 70)

# So:
# IETT D: SÖĞÜTLÜÇEŞME → B.SONDURAK (east to west) = our "west"/"donus"
# IETT G: B.SONDURAK → SÖĞÜTLÜÇEŞME (west to east) = our "east"/"gidis"

# Map IETT G to our "east" direction (gidiş = batıdan doğuya)
east_stops = g_stops  # G = Beylikdüzü → Söğütlüçeşme = our east

# ─── Map IETT names to our short codes ───
# The IETT stop name sometimes differs slightly from our system
# Let's create mapping by approximate coordinate matching

# Current stations from our system (hardcoded from stations.ts)
current_stations = [
    {"code": "TYP", "name": "Tüyap", "lat": 41.022058, "lon": 28.623512},
    {"code": "HDM", "name": "Hadımköy", "lat": 41.019286, "lon": 28.631496},
    {"code": "CMH", "name": "Cumhuriyet Mah.", "lat": 41.015463, "lon": 28.641471},
    {"code": "BLB", "name": "Beylikdüzü Belediye", "lat": 41.012418, "lon": 28.649437},
    {"code": "BYL", "name": "Beylikdüzü", "lat": 41.009508, "lon": 28.657147},
    {"code": "GZY", "name": "Güzelyurt", "lat": 41.006637, "lon": 28.665256},
    {"code": "HRM", "name": "Haramidere", "lat": 41.005981, "lon": 28.673016},
    {"code": "HRS", "name": "H.Sanayi", "lat": 41.004230, "lon": 28.685371},
    {"code": "SDD", "name": "Saadetdere Mah.", "lat": 40.999715, "lon": 28.693001},
    {"code": "MKP", "name": "Mustafa Kemal Paşa", "lat": 40.994998, "lon": 28.706146},
    {"code": "CHN", "name": "Cihangir Üniversite", "lat": 40.990706, "lon": 28.713657},
    {"code": "AVC", "name": "Avcılar Mrk. Ünv.", "lat": 40.983601, "lon": 28.725913},
    {"code": "SKB", "name": "Şükrübey", "lat": 40.980358, "lon": 28.731326},
    {"code": "IBB", "name": "İBB Sosyal Tesisleri", "lat": 40.978088, "lon": 28.745463},
    {"code": "KCK", "name": "Küçükçekmece", "lat": 40.986372, "lon": 28.769420},
    {"code": "CEN", "name": "Cennet Mah.", "lat": 40.985346, "lon": 28.782645},
    {"code": "FLR", "name": "Florya", "lat": 40.987586, "lon": 28.790428},
    {"code": "BES", "name": "Beşyol", "lat": 40.994992, "lon": 28.795078},
    {"code": "SKY", "name": "Sefaköy", "lat": 40.998818, "lon": 28.798906},
    {"code": "YNB", "name": "Yenibosna", "lat": 40.992316, "lon": 28.834746},
    {"code": "ASR", "name": "Ataköy-Şirinevler", "lat": 40.991741, "lon": 28.845778},
    {"code": "BHC", "name": "Bahçelievler", "lat": 40.995186, "lon": 28.863941},
    {"code": "INC", "name": "İncirli", "lat": 40.997877, "lon": 28.872609},
    {"code": "ZYT", "name": "Zeytinburnu", "lat": 41.003521, "lon": 28.891227},
    {"code": "MER", "name": "Merter", "lat": 41.007522, "lon": 28.897266},
    {"code": "CVZ", "name": "Cevizlibağ", "lat": 41.016555, "lon": 28.911123},
    {"code": "TPK", "name": "Topkapı", "lat": 41.020432, "lon": 28.917463},
    {"code": "BYM", "name": "Bayrampaşa-Maltepe", "lat": 41.023933, "lon": 28.921484},
    {"code": "AMB", "name": "Adnan Menderes Bulvarı", "lat": 41.030035, "lon": 28.924704},
    {"code": "EDK", "name": "Edirnekapı", "lat": 41.032933, "lon": 28.928614},
    {"code": "AYV", "name": "Ayvansaray-Eyüp", "lat": 41.038476, "lon": 28.937238},
    {"code": "HLC", "name": "Halıcıoğlu", "lat": 41.048658, "lon": 28.946185},
    {"code": "OKM2", "name": "Okmeydanı", "lat": 41.056704, "lon": 28.961473},
    {"code": "PRP", "name": "Darülaceze-Perpa", "lat": 41.063086, "lon": 28.968340},
    {"code": "OKH", "name": "Okmeydanı Hastane", "lat": 41.067358, "lon": 28.975802},
    {"code": "CGL", "name": "Çağlayan", "lat": 41.067320, "lon": 28.981552},
    {"code": "MEC", "name": "Mecidiyeköy", "lat": 41.066822, "lon": 28.992503},
    {"code": "ZNK", "name": "Zincirlikuyu", "lat": 41.067505, "lon": 29.013945},
    {"code": "BGZ", "name": "15 Temmuz Şehitler Köprüsü", "lat": 41.036750, "lon": 29.043541},
    {"code": "BRH", "name": "Burhaniye", "lat": 41.031934, "lon": 29.046852},
    {"code": "ALT", "name": "Altunizade", "lat": 41.021126, "lon": 29.048928},
    {"code": "ACB", "name": "Acıbadem", "lat": 41.015031, "lon": 29.056570},
    {"code": "UZN", "name": "Uzunçayır", "lat": 40.998883, "lon": 29.056412},
    {"code": "FKT", "name": "Fikirtepe", "lat": 40.993656, "lon": 29.047085},
    {"code": "SGC", "name": "Söğütlüçeşme", "lat": 40.991442, "lon": 29.037863},
]

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# ─── Compare IETT G stops with our east stations ───
print("\n" + "=" * 70)
print("  COMPARISON: IETT G-direction vs Our East Stations")
print("=" * 70)
print(f"  IETT G stops: {len(g_stops)} | Our stops: {len(current_stations)}")
print()

# Note: IETT has 44 stops, our system has 45
# IETT does not have "Ataköy-Şirinevler" (Şirinevler is combined with another)
# Let's find matches by closest coordinate

matched_pairs = []
iett_matched = set()

for cs in current_stations:
    best_dist = float("inf")
    best_iett = None
    best_idx = -1
    for i, ist in enumerate(g_stops):
        if i in iett_matched:
            continue
        ilat = float(ist["YKOORDINATI"])
        ilon = float(ist["XKOORDINATI"])
        d = haversine(cs["lat"], cs["lon"], ilat, ilon)
        if d < best_dist:
            best_dist = d
            best_iett = ist
            best_idx = i
    
    if best_dist < 1000:  # within 1km
        matched_pairs.append({
            "code": cs["code"],
            "our_name": cs["name"],
            "iett_name": best_iett["DURAKADI"],
            "our_lat": cs["lat"],
            "our_lon": cs["lon"],
            "iett_lat": float(best_iett["YKOORDINATI"]),
            "iett_lon": float(best_iett["XKOORDINATI"]),
            "distance_m": round(best_dist, 1),
            "iett_code": best_iett["DURAKKODU"],
        })
        iett_matched.add(best_idx)
    else:
        matched_pairs.append({
            "code": cs["code"],
            "our_name": cs["name"],
            "iett_name": "❌ NO MATCH",
            "our_lat": cs["lat"],
            "our_lon": cs["lon"],
            "iett_lat": None,
            "iett_lon": None,
            "distance_m": best_dist,
            "iett_code": None,
        })

print(f"{'#':>3} {'Code':5} {'Our Name':30s} {'IETT Name':35s} {'Dist(m)':>8}")
print("-" * 90)
total_drift = 0
for i, p in enumerate(matched_pairs):
    marker = "✅" if p["distance_m"] < 200 else ("⚠️" if p["distance_m"] < 500 else "❌")
    print(f"{i+1:>3} {p['code']:5} {p['our_name']:30s} {p['iett_name']:35s} {p['distance_m']:>8.1f} {marker}")
    if p["iett_lat"]:
        total_drift += p["distance_m"]

# Find unmatched IETT stops
unmatched_iett = [g_stops[i] for i in range(len(g_stops)) if i not in iett_matched]
if unmatched_iett:
    print(f"\n  Unmatched IETT stops:")
    for u in unmatched_iett:
        print(f"    {u['SIRANO']}. {u['DURAKADI']} ({u['YKOORDINATI']}, {u['XKOORDINATI']})")

print(f"\n  Total matched: {sum(1 for p in matched_pairs if p['iett_lat'])} / {len(current_stations)}")
print(f"  Average coordinate drift: {total_drift / max(1, sum(1 for p in matched_pairs if p['iett_lat'])):.1f}m")

# ─── Generate updated stations ───
print("\n" + "=" * 70)
print("  GENERATING UPDATED STATION DATA")
print("=" * 70)

# Use IETT coordinates where available, keep OSM for unmatched
updated = []
for p in matched_pairs:
    if p["iett_lat"]:
        updated.append({
            "code": p["code"],
            "name": p["iett_name"].strip().title() if p["iett_name"] != "❌ NO MATCH" else p["our_name"],
            "name_iett": p["iett_name"].strip(),
            "latitude": p["iett_lat"],
            "longitude": p["iett_lon"],
            "iett_code": p["iett_code"],
            "source": "IETT",
        })
    else:
        updated.append({
            "code": p["code"],
            "name": p["our_name"],
            "name_iett": None,
            "latitude": p["our_lat"],
            "longitude": p["our_lon"],
            "iett_code": None,
            "source": "OSM",
        })

# Save comparison and updated data
out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
with open(os.path.join(out_dir, "station_comparison.json"), "w", encoding="utf-8") as f:
    json.dump(matched_pairs, f, ensure_ascii=False, indent=2)

with open(os.path.join(out_dir, "stations_updated_iett.json"), "w", encoding="utf-8") as f:
    json.dump(updated, f, ensure_ascii=False, indent=2)

print(f"  💾 Saved: data/station_comparison.json")
print(f"  💾 Saved: data/stations_updated_iett.json")
print(f"  Total stations: {len(updated)}")
print(f"  From IETT: {sum(1 for s in updated if s['source'] == 'IETT')}")
print(f"  From OSM (no match): {sum(1 for s in updated if s['source'] == 'OSM')}")
