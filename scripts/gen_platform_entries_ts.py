"""Convert platform_entries.json to TypeScript constant."""
import json, os

BASE = os.path.dirname(os.path.dirname(__file__))
json_path = os.path.join(BASE, "data", "platform_entries.json")
ts_path = os.path.join(BASE, "packages", "shared", "src", "constants", "platform-entries.ts")

with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

# Deduplicate: pick best per name (closest to 100m)
from collections import defaultdict
by_name = defaultdict(list)
for p in data:
    by_name[p['name']].append(p)

best = []
for name, entries in by_name.items():
    reasonable = [e for e in entries if 20 <= e['length'] <= 250]
    if not reasonable:
        reasonable = entries
    pick = min(reasonable, key=lambda x: abs(x['length'] - 100))
    best.append(pick)

# Sort by longitude (west to east)
best.sort(key=lambda x: x['gidis_lon'])

entries_json = json.dumps(best, indent=2, ensure_ascii=False)

ts = f"""// Platform giriş noktaları — Overpass platform way uçları
// Gidiş = batı ucu (düşük longitude), Dönüş = doğu ucu (yüksek longitude)
// {len(best)} durak

export interface PlatformEntry {{
    name: string;
    /** Platform uzunluğu (metre) */
    length: number;
    /** Gidiş yönü giriş noktası */
    gidis_lat: number;
    gidis_lon: number;
    /** Dönüş yönü giriş noktası */
    donus_lat: number;
    donus_lon: number;
}}

export const PLATFORM_ENTRIES: PlatformEntry[] = {entries_json};
"""

with open(ts_path, "w", encoding="utf-8") as f:
    f.write(ts)
print(f"Saved {len(best)} entries to {ts_path}")
