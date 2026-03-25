"""
Her durak platformunun gidiş ve dönüş yönleri için
giriş noktası (baş) koordinatlarını bul.

Platform way'lerinin node'ları sıralı. Metrobüs hattı kabaca
batıdan doğuya (gidiş) ve doğudan batıya (dönüş) gidiyor:
  - Gidiş giriş noktası = platformun batı ucu (düşük longitude)
  - Dönüş giriş noktası = platformun doğu ucu (yüksek longitude)
"""
import json, os

BASE = os.path.dirname(os.path.dirname(__file__))
CACHE = os.path.join(BASE, "data", "overpass_platforms.json")

with open(CACHE, "r", encoding="utf-8") as f:
    data = json.load(f)

nodes = {}
ways = []
for el in data['elements']:
    if el['type'] == 'node':
        nodes[el['id']] = (el['lat'], el['lon'])
    elif el['type'] == 'way' and 'tags' in el:
        ways.append(el)

import math
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

# Her platform way için uç noktaları ve uzunluk
print(f"{'Durak':<50} {'Uzunluk':>7}  {'Gidiş Giriş (Batı Uç)':>30}  {'Dönüş Giriş (Doğu Uç)':>30}")
print("=" * 130)

results = []
for w in ways:
    name = w['tags'].get('name', '?')
    length = way_length(w)
    if length < 20 or length > 250:
        continue
    
    # Way'in node koordinatları
    way_coords = [(nodes[n][0], nodes[n][1]) for n in w['nodes'] if n in nodes]
    if len(way_coords) < 2:
        continue
    
    first = way_coords[0]   # (lat, lon)
    last = way_coords[-1]   # (lat, lon)
    
    # Batı ucu = düşük longitude → gidiş girişi
    # Doğu ucu = yüksek longitude → dönüş girişi
    if first[1] < last[1]:
        gidis_entry = first
        donus_entry = last
    else:
        gidis_entry = last
        donus_entry = first
    
    results.append({
        'name': name,
        'length': length,
        'gidis_lat': gidis_entry[0],
        'gidis_lon': gidis_entry[1],
        'donus_lat': donus_entry[0],
        'donus_lon': donus_entry[1],
    })
    
    print(f"{name:<50} {length:>5}m  ({gidis_entry[0]:.7f}, {gidis_entry[1]:.7f})  ({donus_entry[0]:.7f}, {donus_entry[1]:.7f})")

# JSON olarak kaydet
output_path = os.path.join(BASE, "data", "platform_entries.json")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\n💾 {len(results)} platform giriş noktası → {output_path}")
