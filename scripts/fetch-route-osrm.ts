/**
 * Metrobüs rotasını OSM relation'larından çek.
 * D-100 way'leri yerine doğrudan metrobüs güzergah relation'ı kullanılıyor.
 * 
 * Kullanım: npx tsx scripts/fetch-route-osrm.ts
 */

import { STATIONS_EAST } from '../packages/shared/src/constants/stations';

const OVERPASS = 'https://overpass-api.de/api/interpreter';

async function main() {
    console.log('🔍 Metrobüs rota relation çekiliyor...\n');

    const q = `[out:json][timeout:120];
area["name"="İstanbul"]["admin_level"="4"]->.istanbul;

/* Gidiş: Beylikdüzü -> Söğütlüçeşme */
relation(area.istanbul)
  ["type"="route"]["route"="bus"]
  ["from"~"Beylikdüzü", i]
  ["to"~"Söğütlüçeşme", i]
  ->.gidis;

/* Dönüş: Söğütlüçeşme -> Beylikdüzü */
relation(area.istanbul)
  ["type"="route"]["route"="bus"]
  ["from"~"Söğütlüçeşme", i]
  ["to"~"Beylikdüzü", i]
  ->.donus;

/* İki yön bir arada */
(.gidis; .donus;)->.rotalar;

/* Rota geometrisi (çizgi için) */
(.rotalar; >;)->.rota_geometri;

/* Durak / platform objelerini topla */
(
  node(r.rotalar)["public_transport"~"platform|stop_position"];
  way(r.rotalar)["public_transport"~"platform|stop_position"];
  node(r.rotalar)["highway"="bus_stop"];
  way(r.rotalar)["highway"="bus_stop"];
)->.duraklar;

/* Çıktılar */
.rotalar out body;
.rota_geometri out skel qt;
.duraklar out body qt;`;

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

    // Relation'ları ayıkla
    const relations = elements.filter((e: any) => e.type === 'relation');
    console.log(`� ${relations.length} rota relation bulundu`);
    for (const r of relations) {
        console.log(`   - ${r.tags?.name || r.id} (${r.tags?.from} → ${r.tags?.to})`);
    }

    // Way'leri topla (rota geometrisi)
    const wayMap = new Map<number, { lat: number; lon: number }[]>();
    const nodeMap = new Map<number, { lat: number; lon: number }>();

    for (const e of elements) {
        if (e.type === 'node' && e.lat !== undefined) {
            nodeMap.set(e.id, { lat: e.lat, lon: e.lon });
        }
        if (e.type === 'way' && e.nodes) {
            wayMap.set(e.id, e.nodes);
        }
    }

    console.log(`\n📦 ${nodeMap.size} node, ${wayMap.size} way`);

    // Gidiş + Dönüş relation'larını bul
    const gidisRelation = relations.find((r: any) =>
        r.tags?.from?.toLowerCase().includes('beylikdüzü')
    );
    const donusRelation = relations.find((r: any) =>
        r.tags?.from?.toLowerCase().includes('söğütlüçeşme')
    );

    function extractRouteGeometry(relation: any, label: string): [number, number][] {
        if (!relation) {
            console.log(`⚠️ ${label} rotası bulunamadı`);
            return [];
        }
        console.log(`\n🚌 ${label}: ${relation.tags?.name || relation.id}`);

        const routeCoords: [number, number][] = [];
        const members = (relation.members || []).filter((m: any) => m.type === 'way' && !m.role?.includes('platform'));
        console.log(`   ${members.length} way üyesi`);

        for (const member of members) {
            const wayNodes = wayMap.get(member.ref);
            if (!wayNodes || !Array.isArray(wayNodes)) continue;

            const coords: [number, number][] = [];
            for (const nid of wayNodes as any[]) {
                const node = nodeMap.get(nid as number);
                if (node) coords.push([node.lat, node.lon]);
            }
            if (coords.length === 0) continue;

            if (routeCoords.length > 0) {
                const lastPt = routeCoords[routeCoords.length - 1];
                const dFirst = Math.hypot(lastPt[0] - coords[0][0], lastPt[1] - coords[0][1]);
                const dLast = Math.hypot(lastPt[0] - coords[coords.length - 1][0], lastPt[1] - coords[coords.length - 1][1]);
                if (dLast < dFirst) coords.reverse();
            }

            for (const c of coords) {
                const last = routeCoords[routeCoords.length - 1];
                if (!last || Math.abs(last[0] - c[0]) > 0.00001 || Math.abs(last[1] - c[1]) > 0.00001) {
                    routeCoords.push(c);
                }
            }
        }

        console.log(`   ✅ ${routeCoords.length} nokta`);
        return routeCoords;
    }

    const gidisCoords = extractRouteGeometry(gidisRelation, 'Gidiş');
    const donusCoords = extractRouteGeometry(donusRelation, 'Dönüş');

    // Durakları ayıkla
    const stops = elements.filter((e: any) =>
        e.type === 'node' && e.tags &&
        (e.tags.public_transport || e.tags.highway === 'bus_stop')
    );
    console.log(`\n🚏 ${stops.length} durak bulundu`);

    // route-geometry.ts kaydet — gidiş + dönüş ayrı
    const routeOutput = `// Metrobüs Rota Geometrisi — OSM Relation
// ${new Date().toISOString()}
// Gidiş: ${gidisCoords.length} nokta, Dönüş: ${donusCoords.length} nokta

/** Gidiş hattı: Beylikdüzü → Söğütlüçeşme */
export const METROBUS_ROUTE_EAST: [number, number][] = ${JSON.stringify(gidisCoords)};

/** Dönüş hattı: Söğütlüçeşme → Beylikdüzü */
export const METROBUS_ROUTE_WEST: [number, number][] = ${JSON.stringify(donusCoords)};

/** Eski uyumluluk */
export const METROBUS_ROUTE_GEOMETRY = METROBUS_ROUTE_EAST;
`;

    const fs = require('fs');
    const path = require('path');
    const routePath = path.join(__dirname, '..', 'packages', 'shared', 'src', 'constants', 'route-geometry.ts');
    fs.writeFileSync(routePath, routeOutput);
    console.log(`\n💾 Rota: ${routePath}`);

    // OSM durakları JSON olarak kaydet
    const stopsPath = path.join(__dirname, '..', 'packages', 'shared', 'src', 'constants', 'osm-stops.json');
    fs.writeFileSync(stopsPath, JSON.stringify(stops.map((s: any) => ({
        name: s.tags?.name || 'İsimsiz',
        lat: s.lat,
        lon: s.lon,
        tags: s.tags,
    })), null, 2));
    console.log(`💾 Duraklar: ${stopsPath}`);
}

main().catch(err => { console.error('❌', err.message); process.exit(1); });
