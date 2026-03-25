"""
Fetch platform ways from Overpass, cache locally, pick best per station.
Save updated station-slots.ts with correct platform lengths.
"""
import requests, json, math, re, os
from collections import defaultdict
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(__file__))
CACHE = os.path.join(BASE, "data", "overpass_platforms.json")

QUERY = """
[out:json][timeout:120];
(
  way["public_transport"="platform"]["name"~"Beylikdüzü|Beykent|Cumhuriyet|Belediye|Güzelyurt|Haramidere|Saadetdere|Mustafa Kemalpaşa|Avcılar|Şükrübey|Sosyal|Küçükçekmece|Cennet|Florya|Beşyol|Sefaköy|Yenibosna|Şirinevler|Bahçelievler|İncirli|Zeytinburnu|Merter|Cevizlibağ|Topkapı|Bayrampaşa|Edirnekapı|Ayvansaray|Halıcıoğlu|Okmeydanı|Darülaceze|Çağlayan|Mecidiyeköy|Zincirlikuyu|15 Temmuz|Burhaniye|Altunizade|Acıbadem|Uzunçayır|Fikirtepe|Söğütlüçeşme"](40.96, 28.58, 41.10, 29.07);
);
out body;
>;
out skel qt;
"""

# Check cache
if os.path.exists(CACHE):
    print(f"Cache bulundu: {CACHE}")
    with open(CACHE, "r", encoding="utf-8") as f:
        data = json.load(f)
else:
    print("Overpass sorgusu çalıştırılıyor...")
    r = requests.post("https://overpass-api.de/api/interpreter", data={"data": QUERY}, timeout=180)
    r.raise_for_status()
    data = r.json()
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"Cache kaydedildi: {CACHE}")

nodes = {}
ways = []
for el in data['elements']:
    if el['type'] == 'node':
        nodes[el['id']] = (el['lat'], el['lon'])
    elif el['type'] == 'way' and 'tags' in el:
        ways.append(el)

print(f"{len(ways)} platform way, {len(nodes)} node")

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def way_length(way):
    total = 0
    nds = way['nodes']
    for i in range(1, len(nds)):
        if nds[i-1] in nodes and nds[i] in nodes:
            total += haversine(*nodes[nds[i-1]], *nodes[nds[i]])
    return round(total)

# All platform ways with lengths
all_platforms = []
for w in ways:
    name = w['tags'].get('name', '?')
    length = way_length(w)
    all_platforms.append((name, length))

# Group by name, pick BEST per name (closest to 100m, 20-250m range)
by_name = defaultdict(list)
for name, length in all_platforms:
    by_name[name].append(length)

best_per_name = {}
for name, lengths in by_name.items():
    reasonable = [l for l in lengths if 20 <= l <= 250]
    if not reasonable:
        reasonable = [l for l in lengths if l > 0]
    if reasonable:
        best = min(reasonable, key=lambda x: abs(x - 100))
        best_per_name[name] = best

# ─── Load station-slots.ts ───
ts_path = os.path.join(BASE, "packages", "shared", "src", "constants", "station-slots.ts")
with open(ts_path, "r", encoding="utf-8") as f:
    ts_text = f.read()

m_ts = re.search(r'STATION_SLOTS.*?=\s*(\[.*\]);', ts_text, re.DOTALL)
slots_data = json.loads(m_ts.group(1))

def norm(n):
    return n.lower().replace('ı','i').replace('ş','s').replace('ç','c').replace('ö','o').replace('ü','u').replace('ğ','g').replace('â','a').replace('-',' ').strip()

plat_lookup = {norm(k): (k, v) for k, v in best_per_name.items()}

print(f"\n{'Durak':<50} {'Eski':>5} {'Yeni':>5} {'Slot':>5}")
print("-" * 70)
updated = 0
for slot in slots_data:
    sn = norm(slot['name'])
    old = slot['platformLengthMeters']
    old_slots = slot['slotCount']
    
    matched = None
    for pk, pv in plat_lookup.items():
        if sn in pk or pk in sn:
            matched = pv; break
        sw = set(sn.split()); pw = set(pk.split())
        if sw & pw and len(sw & pw) / max(len(sw), 1) > 0.4:
            matched = pv; break
    
    if matched:
        _, new_len = matched
        new_slots = max(1, min(4, new_len // 40))
        if new_slots < 2 and new_len >= 36:
            new_slots = 2
        
        changed = old != new_len
        m = "⚡" if changed else "✅"
        print(f"{m} {slot['name']:<48} {old:>4}m {new_len:>4}m {new_slots:>5}")
        if changed:
            slot['platformLengthMeters'] = new_len
            slot['slotCount'] = new_slots
            updated += 1
    else:
        print(f"❓ {slot['name']:<48} {old:>4}m  ???")

print(f"\n{updated} durak güncellendi")

# Save
slots_json = json.dumps(slots_data, indent=2, ensure_ascii=False)
now = datetime.now().isoformat()

new_ts = f"""// Station Stop Positions — Overpass API'den
// Generated: {now}
// Platform uzunlukları: Overpass platform way geometrisinden
// {len(slots_data)} durak

export interface StopPosition {{
    id: number;
    lat: number;
    lon: number;
}}

export interface StationSlotInfo {{
    /** Durak adı */
    name: string;
    /** Bu duraktaki stop_position noktaları */
    stopPositions: StopPosition[];
    /** Slot sayısı (kaç otobüs aynı anda durabilir) */
    slotCount: number;
    /** Platform uzunluğu (metre) — Overpass platform way */
    platformLengthMeters: number;
}}

export const STATION_SLOTS: StationSlotInfo[] = {slots_json};
"""
with open(ts_path, "w", encoding="utf-8") as f:
    f.write(new_ts)
print(f"💾 {ts_path}")
