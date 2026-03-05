/**
 * Directed Edge Network Builder
 * 
 * 1. Overpass'ten gidiş/dönüş relation + shared way analizi
 * 2. Her yön için ayrı directed edge listesi üret
 * 3. Shared geometry'de dönüş yönü ters çevirilir
 * 4. Durakları edge'lere bağla
 * 
 * Çıktı: route-network-data.ts
 * 
 * Kullanım: npx tsx scripts/fetch-route-osrm.ts
 */

const OVERPASS = 'https://overpass-api.de/api/interpreter';

// ======================== GEO UTILS ========================

function haversineDist(lat1: number, lon1: number, lat2: number, lon2: number): number {
    const R = 6371000;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function polylineLength(coords: [number, number][]): number {
    let total = 0;
    for (let i = 1; i < coords.length; i++) {
        total += haversineDist(coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1]);
    }
    return total;
}

function findPositionAlongPolyline(coords: [number, number][], lat: number, lon: number): number {
    let bestDist = Infinity, bestProgress = 0, cumLen = 0;
    const totalLen = polylineLength(coords);
    if (totalLen === 0) return 0;

    for (let i = 0; i < coords.length; i++) {
        const d = haversineDist(lat, lon, coords[i][0], coords[i][1]);
        if (d < bestDist) {
            bestDist = d;
            bestProgress = cumLen / totalLen;
        }
        if (i < coords.length - 1) {
            cumLen += haversineDist(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1]);
        }
    }
    return Math.max(0, Math.min(1, bestProgress));
}

// ======================== MAIN ========================

async function main() {
    console.log('🔍 Directed Edge Network oluşturuluyor...\n');

    // ---- STEP 1: Overpass Query ----
    const q = `[out:json][timeout:120];
area["name"="İstanbul"]["admin_level"="4"]->.istanbul;

relation(area.istanbul)
  ["type"="route"]["route"="bus"]
  ["from"~"Beylikdüzü", i]
  ["to"~"Söğütlüçeşme", i]
  ->.gidis_rel;

relation(area.istanbul)
  ["type"="route"]["route"="bus"]
  ["from"~"Söğütlüçeşme", i]
  ["to"~"Beylikdüzü", i]
  ->.donus_rel;

(.gidis_rel; .donus_rel;)->.rotalar;
(.rotalar; >;)->.rota_geometri;

(
  node(r.rotalar)["public_transport"~"platform|stop_position"];
  node(r.rotalar)["highway"="bus_stop"];
)->.duraklar;

.rotalar out body;
.rota_geometri out skel qt;
.duraklar out body qt;`;

    console.log('📡 Overpass sorgusu gönderiliyor...');
    const res = await fetch(OVERPASS, {
        method: 'POST',
        body: `data=${encodeURIComponent(q)}`,
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    if (!res.ok) { console.error(`❌ Overpass HTTP ${res.status}`); process.exit(1); }
    const data = await res.json() as any;
    const elements = data.elements;

    // ---- STEP 2: Parse elements ----
    const relations = elements.filter((e: any) => e.type === 'relation');
    const nodeMap = new Map<number, { lat: number; lon: number }>();
    const wayNodeMap = new Map<number, number[]>();

    for (const e of elements) {
        if (e.type === 'node' && e.lat !== undefined) nodeMap.set(e.id, { lat: e.lat, lon: e.lon });
        if (e.type === 'way' && e.nodes) wayNodeMap.set(e.id, e.nodes);
    }

    console.log(`📦 ${relations.length} relation, ${nodeMap.size} node, ${wayNodeMap.size} way\n`);

    const gidisRel = relations.find((r: any) => r.tags?.from?.toLowerCase().includes('beylikdüzü'));
    const donusRel = relations.find((r: any) => r.tags?.from?.toLowerCase().includes('söğütlüçeşme'));

    if (!gidisRel || !donusRel) {
        console.error('❌ Gidiş veya dönüş relation bulunamadı!');
        process.exit(1);
    }

    console.log(`🚌 Gidiş: ${gidisRel.tags?.name} (${gidisRel.members?.length} üye)`);
    console.log(`🚌 Dönüş: ${donusRel.tags?.name} (${donusRel.members?.length} üye)`);

    // ---- STEP 3: Shared way analysis ----
    const gidisWayIds = new Set(
        (gidisRel.members || []).filter((m: any) => m.type === 'way' && !m.role?.includes('platform')).map((m: any) => m.ref)
    );
    const donusWayIds = new Set(
        (donusRel.members || []).filter((m: any) => m.type === 'way' && !m.role?.includes('platform')).map((m: any) => m.ref)
    );

    const sharedWayIds: number[] = [];
    for (const id of gidisWayIds) {
        if (donusWayIds.has(id)) sharedWayIds.push(id);
    }
    const sharedSet = new Set(sharedWayIds);

    console.log(`\n📊 Way analizi:`);
    console.log(`   Gidiş way: ${gidisWayIds.size}`);
    console.log(`   Dönüş way: ${donusWayIds.size}`);
    console.log(`   Shared: ${sharedWayIds.length}`);
    console.log(`   Sadece gidiş: ${gidisWayIds.size - sharedWayIds.length}`);
    console.log(`   Sadece dönüş: ${donusWayIds.size - sharedWayIds.length}`);

    // ---- STEP 4: Build directed edges ----
    function buildEdges(relation: any, direction: 'gidis' | 'donus') {
        const prefix = direction === 'gidis' ? 'G' : 'D';
        const members = (relation.members || []).filter((m: any) => m.type === 'way' && !m.role?.includes('platform'));
        const edges: any[] = [];
        let prevEndNode: number | null = null;

        for (let i = 0; i < members.length; i++) {
            const wayId: number = members[i].ref;
            const nodeIds = wayNodeMap.get(wayId);
            if (!nodeIds || nodeIds.length < 2) continue;

            // Geometry oluştur
            let coords: [number, number][] = [];
            for (const nid of nodeIds) {
                const n = nodeMap.get(nid);
                if (n) coords.push([n.lat, n.lon]);
            }
            if (coords.length < 2) continue;

            // Yön kontrolü — önceki edge'in son noktasına bağlanmalı
            if (prevEndNode !== null) {
                const firstNode = nodeIds[0];
                const lastNode = nodeIds[nodeIds.length - 1];
                if (lastNode === prevEndNode) {
                    // Ters çevir
                    coords.reverse();
                    prevEndNode = firstNode;
                } else {
                    prevEndNode = lastNode;
                }
            } else {
                prevEndNode = nodeIds[nodeIds.length - 1];
            }

            const isShared = sharedSet.has(wayId);
            const lengthM = polylineLength(coords);

            edges.push({
                id: `${prefix}_${wayId}`,
                osmWayId: wayId,
                direction,
                geometry: coords,
                sequenceIndex: i,
                isSharedGeometry: isShared,
                lengthMeters: Math.round(lengthM),
            });
        }
        return edges;
    }

    const gidisEdges = buildEdges(gidisRel, 'gidis');
    const donusEdges = buildEdges(donusRel, 'donus');

    console.log(`\n🔗 Edge'ler:`);
    console.log(`   Gidiş: ${gidisEdges.length} edge`);
    console.log(`   Dönüş: ${donusEdges.length} edge`);

    // ---- STEP 5: Stops ----
    const stopNodes = elements.filter((e: any) =>
        e.type === 'node' && e.tags &&
        (e.tags.public_transport || e.tags.highway === 'bus_stop')
    );

    function assignStopsToEdges(edges: any[], direction: 'gidis' | 'donus') {
        const stops: any[] = [];
        const prefix = direction === 'gidis' ? 'GS' : 'DS';

        // Her relation'daki stop member'ları da dikkate al
        const rel = direction === 'gidis' ? gidisRel : donusRel;
        const stopMembers = (rel.members || []).filter((m: any) =>
            m.type === 'node' && (m.role === 'stop' || m.role === 'platform' || m.role === 'stop_entry_only' || m.role === 'stop_exit_only')
        );

        const relStopIds = new Set(stopMembers.map((m: any) => m.ref));

        // Durakları filtrele — bu yöne ait olanlar
        const dirStops = stopNodes.filter((s: any) => relStopIds.has(s.id));

        for (const stop of dirStops) {
            // En yakın edge'i bul
            let bestEdge = edges[0];
            let bestDist = Infinity;

            for (const edge of edges) {
                for (const [lat, lon] of edge.geometry) {
                    const d = haversineDist(stop.lat, stop.lon, lat, lon);
                    if (d < bestDist) {
                        bestDist = d;
                        bestEdge = edge;
                    }
                }
            }

            if (bestDist > 500) continue; // 500m'den uzak — bu yöne ait değildir

            const pos = findPositionAlongPolyline(bestEdge.geometry, stop.lat, stop.lon);

            stops.push({
                id: `${prefix}_${stop.id}`,
                osmId: stop.id,
                name: stop.tags?.name || 'İsimsiz',
                direction,
                latitude: stop.lat,
                longitude: stop.lon,
                edgeId: bestEdge.id,
                positionAlongEdge: Math.round(pos * 10000) / 10000,
            });
        }

        // Sırala — edge sequence + position along edge
        stops.sort((a: any, b: any) => {
            const aEdge = edges.findIndex((e: any) => e.id === a.edgeId);
            const bEdge = edges.findIndex((e: any) => e.id === b.edgeId);
            if (aEdge !== bEdge) return aEdge - bEdge;
            return a.positionAlongEdge - b.positionAlongEdge;
        });

        // Dedup by name (aynı isimli durak birden fazla olmasın)
        const seen = new Set<string>();
        return stops.filter((s: any) => {
            if (seen.has(s.name)) return false;
            seen.add(s.name);
            return true;
        });
    }

    const gidisStops = assignStopsToEdges(gidisEdges, 'gidis');
    const donusStops = assignStopsToEdges(donusEdges, 'donus');

    console.log(`\n🚏 Duraklar:`);
    console.log(`   Gidiş: ${gidisStops.length} durak`);
    console.log(`   Dönüş: ${donusStops.length} durak`);

    // ---- STEP 6: Build network ----
    const gidisLenTotal = gidisEdges.reduce((s: number, e: any) => s + e.lengthMeters, 0);
    const donusLenTotal = donusEdges.reduce((s: number, e: any) => s + e.lengthMeters, 0);

    const network = {
        edges: { gidis: gidisEdges, donus: donusEdges },
        stops: { gidis: gidisStops, donus: donusStops },
        sharedWayIds,
        stats: {
            totalEdgesGidis: gidisEdges.length,
            totalEdgesDonus: donusEdges.length,
            totalStopsGidis: gidisStops.length,
            totalStopsDonus: donusStops.length,
            sharedWayCount: sharedWayIds.length,
            totalLengthGidisMeters: Math.round(gidisLenTotal),
            totalLengthDonusMeters: Math.round(donusLenTotal),
        },
    };

    console.log(`\n📏 Toplam uzunluk:`);
    console.log(`   Gidiş: ${(gidisLenTotal / 1000).toFixed(1)} km`);
    console.log(`   Dönüş: ${(donusLenTotal / 1000).toFixed(1)} km`);

    // ---- STEP 7: Save ----
    const fs = require('fs');
    const path = require('path');

    // route-network-data.ts
    const networkOutput = `// =============================================
// Route Network Data — Directed Graph
// Generated: ${new Date().toISOString()}
// Gidiş: ${gidisEdges.length} edges, ${gidisStops.length} stops
// Dönüş: ${donusEdges.length} edges, ${donusStops.length} stops
// Shared ways: ${sharedWayIds.length}
// =============================================

import type { RouteNetwork } from '../types/route-network';

export const ROUTE_NETWORK: RouteNetwork = ${JSON.stringify(network, null, 0)};
`;

    const networkPath = path.join(__dirname, '..', 'packages', 'shared', 'src', 'constants', 'route-network-data.ts');
    fs.writeFileSync(networkPath, networkOutput);
    console.log(`\n💾 ${networkPath}`);

    // route-geometry.ts (eski uyumluluk) — edge geometry'lerinden düz polyline
    function edgesToPolyline(edges: any[]): [number, number][] {
        const coords: [number, number][] = [];
        for (const e of edges) {
            for (const c of e.geometry) {
                const last = coords[coords.length - 1];
                if (!last || Math.abs(last[0] - c[0]) > 0.00001 || Math.abs(last[1] - c[1]) > 0.00001) {
                    coords.push(c);
                }
            }
        }
        return coords;
    }

    const gidisLine = edgesToPolyline(gidisEdges);
    const donusLine = edgesToPolyline(donusEdges);

    const routeOutput = `// Metrobüs Rota Geometrisi — OSM Relation
// ${new Date().toISOString()}
// Gidiş: ${gidisLine.length} nokta, Dönüş: ${donusLine.length} nokta

export const METROBUS_ROUTE_EAST: [number, number][] = ${JSON.stringify(gidisLine)};
export const METROBUS_ROUTE_WEST: [number, number][] = ${JSON.stringify(donusLine)};
export const METROBUS_ROUTE_GEOMETRY = METROBUS_ROUTE_EAST;
`;

    const routePath = path.join(__dirname, '..', 'packages', 'shared', 'src', 'constants', 'route-geometry.ts');
    fs.writeFileSync(routePath, routeOutput);
    console.log(`💾 ${routePath}`);

    console.log(`\n✅ Directed Edge Network hazır!`);
}

main().catch(err => { console.error('❌', err.message); process.exit(1); });
