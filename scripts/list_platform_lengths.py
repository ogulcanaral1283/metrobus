import re, json

with open(r'c:\Users\ogulcan\Desktop\metrobus\packages\shared\src\constants\station-slots.ts', 'r', encoding='utf-8') as f:
    text = f.read()

m = re.search(r'STATION_SLOTS.*?=\s*(\[.*\]);', text, re.DOTALL)
data = json.loads(m.group(1))

print(f"{'Durak':<50} {'Slot':>5} {'Platform':>10}")
print("-" * 68)
total = 0
for s in sorted(data, key=lambda x: -x['platformLengthMeters']):
    name = s['name']
    slots = s['slotCount']
    plat = s['platformLengthMeters']
    print(f"{name:<50} {slots:>5} {plat:>8}m")
    total += plat
print("-" * 68)
print(f"Toplam: {len(data)} durak, {total}m platform")
print(f"Ortalama: {total/len(data):.0f}m")
print(f"1 slot: {sum(1 for s in data if s['slotCount']==1)} durak")
print(f"2 slot: {sum(1 for s in data if s['slotCount']>=2)} durak")
