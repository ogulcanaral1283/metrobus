"""
Regenerate platform-geometries.ts from cached Overpass platform ways.
Each way becomes a Polyline on the dashboard map.
"""
import json, os

BASE = os.path.dirname(os.path.dirname(__file__))
CACHE = os.path.join(BASE, "data", "overpass_platforms.json")
OUT = os.path.join(BASE, "packages", "shared", "src", "constants", "platform-geometries.ts")

with open(CACHE, "r", encoding="utf-8") as f:
    data = json.load(f)

nodes = {}
ways = []
for el in data['elements']:
    if el['type'] == 'node':
        nodes[el['id']] = (el['lat'], el['lon'])
    elif el['type'] == 'way' and 'tags' in el:
        ways.append(el)

# Build platform geometries
platforms = []
for w in ways:
    name = w['tags'].get('name', 'Platform')
    way_id = w['id']
    # Convert node IDs to [lat, lon] coordinates
    coords = []
    for nid in w['nodes']:
        if nid in nodes:
            lat, lon = nodes[nid]
            coords.append([lat, lon])
    
    if len(coords) >= 2:
        platforms.append({
            'id': way_id,
            'name': name,
            'geometry': coords,
        })

print(f"{len(platforms)} platform way geometrisi")

# Generate TypeScript
platforms_json = json.dumps(platforms, ensure_ascii=False)

ts = f"""// Platform geometrileri — Overpass platform way verileri
// Sorgu: way["public_transport"="platform"] metrobus durakları
// {len(platforms)} platform

export interface PlatformGeometry {{
    id: number;
    name: string;
    geometry: [number, number][];
}}

export const PLATFORM_GEOMETRIES: PlatformGeometry[] = {platforms_json};
"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(ts)
print(f"Saved to {OUT}")
