/**
 * Platform Way Geometry Fetcher
 * 
 * Metrobüs durak platformlarının fiziksel şerit çizgilerini OSM'den çeker.
 * 
 * Kullanım: npx tsx scripts/fetch-platforms.ts
 */

async function main() {
    const OVERPASS = 'https://overpass-api.de/api/interpreter';

    console.log('🔍 Platform way geometrileri çekiliyor...\n');

    const q = `[out:json][timeout:180];
area["name"="İstanbul"]["admin_level"="4"]->.istanbul;

(
  relation(area.istanbul)["type"="route"]["route"="bus"]["from"~"Beylikdüzü|TÜYAP", i]["to"~"Söğütlüçeşme", i];
  relation(area.istanbul)["type"="route"]["route"="bus"]["from"~"Söğütlüçeşme", i]["to"~"Beylikdüzü|TÜYAP", i];
)->.rotalar;

way(r.rotalar)->.rota_wayler;

(
  way(r.rotalar)["public_transport"="platform"];
  way(around.rota_wayler:35)["public_transport"="platform"];
)->.platform_wayleri;

.platform_wayleri out body;
>;
out skel qt;`;

    const res = await fetch(OVERPASS, {
        method: 'POST',
        body: `data=${encodeURIComponent(q)}`,
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });

    if (!res.ok) {
        console.error(`❌ Overpass HTTP ${res.status}`);
        process.exit(1);
    }

    const data = await res.json() as any;
    const elements = data.elements;

    // Parse nodes
    const nodeMap = new Map<number, { lat: number; lon: number }>();
    for (const e of elements) {
        if (e.type === 'node' && e.lat !== undefined) {
            nodeMap.set(e.id, { lat: e.lat, lon: e.lon });
        }
    }

    // Parse platform ways
    const platformWays = elements.filter((e: any) => e.type === 'way' && e.tags);
    console.log(`📦 ${nodeMap.size} node, ${platformWays.length} platform way`);

    const platforms: {
        id: number;
        name: string;
        geometry: [number, number][];
    }[] = [];

    for (const way of platformWays) {
        const coords: [number, number][] = [];
        for (const nid of (way.nodes || [])) {
            const n = nodeMap.get(nid);
            if (n) coords.push([n.lat, n.lon]);
        }
        if (coords.length >= 2) {
            platforms.push({
                id: way.id,
                name: way.tags?.name || 'Platform',
                geometry: coords,
            });
        }
    }

    console.log(`🚏 ${platforms.length} platform geometrisi`);

    // İlk 10'u göster
    for (const p of platforms.slice(0, 10)) {
        console.log(`   - ${p.name}: ${p.geometry.length} nokta`);
    }
    if (platforms.length > 10) console.log(`   ... ve ${platforms.length - 10} platform daha`);

    // Kaydet
    const fs = require('fs');
    const path = require('path');

    const output = `// =============================================
// Metrobüs Durak Platform Geometrileri
// Generated: ${new Date().toISOString()}
// ${platforms.length} platform
// =============================================

export interface PlatformGeometry {
    id: number;
    name: string;
    geometry: [number, number][];
}

export const PLATFORM_GEOMETRIES: PlatformGeometry[] = ${JSON.stringify(platforms)};
`;

    const outPath = path.join(__dirname, '..', 'packages', 'shared', 'src', 'constants', 'platform-geometries.ts');
    fs.writeFileSync(outPath, output);
    console.log(`\n💾 ${outPath}`);
    console.log('✅ Platform geometrileri hazır!');
}

main().catch(err => { console.error('❌', err.message); process.exit(1); });
