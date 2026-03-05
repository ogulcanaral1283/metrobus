/**
 * Lane Boundary Generator
 * 
 * 1. Metrobüs centerline'ını route-network-data'dan al
 * 2. Komşu yol centerline'larını Overpass'ten çek
 * 3. Her komşu yolun metrobüse bakan kenarını (iç kenar) hesapla
 * 4. Lane boundary polyline'ları üret
 * 
 * Kullanım: npx tsx scripts/generate-lane-boundaries.ts
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

/** Bir noktayı verilen bearing ve mesafe kadar kaydır */
function offsetPoint(lat: number, lon: number, bearingDeg: number, distMeters: number): [number, number] {
    const R = 6371000;
    const d = distMeters / R;
    const brng = bearingDeg * Math.PI / 180;
    const lat1 = lat * Math.PI / 180;
    const lon1 = lon * Math.PI / 180;

    const lat2 = Math.asin(Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(brng));
    const lon2 = lon1 + Math.atan2(Math.sin(brng) * Math.sin(d) * Math.cos(lat1), Math.cos(d) - Math.sin(lat1) * Math.sin(lat2));

    return [lat2 * 180 / Math.PI, lon2 * 180 / Math.PI];
}

/** Bir polyline'ı verilen metre kadar perpendicular olarak kaydır */
function offsetPolylineMeters(coords: [number, number][], offsetM: number): [number, number][] {
    if (coords.length < 2) return coords;
    const result: [number, number][] = [];

    for (let i = 0; i < coords.length; i++) {
        let dx: number, dy: number;
        if (i === 0) {
            dy = coords[1][0] - coords[0][0];
            dx = coords[1][1] - coords[0][1];
        } else if (i === coords.length - 1) {
            dy = coords[i][0] - coords[i - 1][0];
            dx = coords[i][1] - coords[i - 1][1];
        } else {
            dy = coords[i + 1][0] - coords[i - 1][0];
            dx = coords[i + 1][1] - coords[i - 1][1];
        }

        const len = Math.sqrt(dx * dx + dy * dy);
        if (len === 0) { result.push(coords[i]); continue; }

        // Perpendicular bearing (90° saat yönünde)
        const bearingRad = Math.atan2(dx, dy);
        const perpBearingDeg = ((bearingRad * 180 / Math.PI) + 90) % 360;

        result.push(offsetPoint(coords[i][0], coords[i][1], perpBearingDeg, offsetM));
    }
    return result;
}

/** Bir noktanın bir polyline'a en yakın mesafesini bul */
function distToPolyline(lat: number, lon: number, poly: [number, number][]): number {
    let minD = Infinity;
    for (const [plat, plon] of poly) {
        const d = haversineDist(lat, lon, plat, plon);
        if (d < minD) minD = d;
    }
    return minD;
}

/** Bir point'in polyline'ın hangi tarafında olduğunu belirle (-1 sol, +1 sağ) */
function sideOfPolyline(
    polyFrom: [number, number],
    polyTo: [number, number],
    point: [number, number]
): number {
    // Cross product: (to-from) × (point-from)
    const dx = polyTo[1] - polyFrom[1];
    const dy = polyTo[0] - polyFrom[0];
    const px = point[1] - polyFrom[1];
    const py = point[0] - polyFrom[0];
    const cross = dx * py - dy * px;
    return cross > 0 ? 1 : -1;
}

// ======================== MAIN ========================

async function main() {
    console.log('🔍 Lane Boundary oluşturuluyor...\n');

    // ---- STEP 1: Mevcut metrobüs centerline'ını al ----
    const { ROUTE_NETWORK } = require('../packages/shared/src/constants/route-network-data');

    // Tüm gidiş edge geometry'lerini birleştir → metrobüs centerline
    const metrobusCenterline: [number, number][] = [];
    for (const edge of ROUTE_NETWORK.edges.gidis) {
        for (const c of edge.geometry) {
            const last = metrobusCenterline[metrobusCenterline.length - 1];
            if (!last || Math.abs(last[0] - c[0]) > 0.00001 || Math.abs(last[1] - c[1]) > 0.00001) {
                metrobusCenterline.push(c as [number, number]);
            }
        }
    }
    console.log(`📍 Metrobüs centerline: ${metrobusCenterline.length} nokta`);

    // ---- STEP 2: Komşu yol centerline'larını Overpass'ten çek ----
    console.log('📡 Komşu yol centerline\'ları çekiliyor...');

    const q = `[out:json][timeout:180];
area["name"="İstanbul"]["admin_level"="4"]->.istanbul;

(
  relation(area.istanbul)["type"="route"]["route"="bus"]["from"~"Beylikdüzü", i]["to"~"Söğütlüçeşme", i];
  relation(area.istanbul)["type"="route"]["route"="bus"]["from"~"Söğütlüçeşme", i]["to"~"Beylikdüzü", i];
)->.rotalar;

way(r.rotalar)->.metrobus_wayler;

(
  way(around.metrobus_wayler:15)["highway"~"motorway|trunk|primary|secondary"];
)->.yakin_ana_yollar;

(
  .yakin_ana_yollar;
  - way.yakin_ana_yollar["highway"~".*_link"];
)->.linksiz;

(
  .linksiz;
  - .metrobus_wayler;
)->.komsu_yol_centerline;

.komsu_yol_centerline out body;
>;
out skel qt;`;

    const res = await fetch(OVERPASS, {
        method: 'POST',
        body: `data=${encodeURIComponent(q)}`,
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });

    if (!res.ok) {
        console.error(`❌ Overpass HTTP ${res.status}`);
        // Komşu yol çekilemezse → basit offset kullan
        console.log('⚠️ Komşu yol çekilemedi — basit offset kullanılacak');
        generateSimpleOffset(ROUTE_NETWORK);
        return;
    }

    const data = await res.json() as any;
    const elements = data.elements;

    // Parse nodes ve ways
    const nodeMap = new Map<number, { lat: number; lon: number }>();
    const ways: { id: number; nodeIds: number[]; tags: any }[] = [];

    for (const e of elements) {
        if (e.type === 'node' && e.lat !== undefined) nodeMap.set(e.id, { lat: e.lat, lon: e.lon });
        if (e.type === 'way' && e.nodes) ways.push({ id: e.id, nodeIds: e.nodes, tags: e.tags || {} });
    }

    console.log(`📦 Komşu yollar: ${ways.length} way, ${nodeMap.size} node`);

    // ---- STEP 3: Her komşu yolun geometry'sini çıkar ----
    const neighborRoads: { id: number; coords: [number, number][]; highway: string }[] = [];

    for (const way of ways) {
        const coords: [number, number][] = [];
        for (const nid of way.nodeIds) {
            const n = nodeMap.get(nid);
            if (n) coords.push([n.lat, n.lon]);
        }
        if (coords.length >= 2) {
            neighborRoads.push({ id: way.id, coords, highway: way.tags.highway || 'unknown' });
        }
    }

    console.log(`🛣️ ${neighborRoads.length} komşu yol geometry'si`);

    // ---- STEP 4: İç kenar hesapla ----
    // Her komşu yol centerline'ını metrobüs tarafına offset al
    // Yol yarı genişliği: motorway=7m, trunk=5m, primary=4m, secondary=3.5m
    const HALF_WIDTH: Record<string, number> = {
        motorway: 7, trunk: 5, primary: 4, secondary: 3.5,
    };

    const laneBoundaries: {
        gidis: [number, number][][];
        donus: [number, number][][];
    } = { gidis: [], donus: [] };

    // Metrobüs dönüş centerline
    const donusCenterline: [number, number][] = [];
    for (const edge of ROUTE_NETWORK.edges.donus) {
        for (const c of edge.geometry) {
            const last = donusCenterline[donusCenterline.length - 1];
            if (!last || Math.abs(last[0] - c[0]) > 0.00001 || Math.abs(last[1] - c[1]) > 0.00001) {
                donusCenterline.push(c as [number, number]);
            }
        }
    }

    for (const road of neighborRoads) {
        const halfW = HALF_WIDTH[road.highway] || 4;

        // Bu yol metrobüsün hangi tarafında?
        // Yolun orta noktasının metrobüs centerline'a göre tarafını belirle
        const midIdx = Math.floor(road.coords.length / 2);
        const midPt = road.coords[midIdx];

        // En yakın metrobüs centerline segmentini bul
        let bestIdx = 0, bestDist = Infinity;
        for (let i = 0; i < metrobusCenterline.length - 1; i++) {
            const d = haversineDist(midPt[0], midPt[1], metrobusCenterline[i][0], metrobusCenterline[i][1]);
            if (d < bestDist) { bestDist = d; bestIdx = i; }
        }

        if (bestDist > 100) continue; // 100m'den uzak yolları atla

        // Metrobüse bakan tarafa offset al (yolun iç kenarı)
        const metroSeg1 = metrobusCenterline[bestIdx];
        const metroSeg2 = metrobusCenterline[Math.min(bestIdx + 1, metrobusCenterline.length - 1)];
        const side = sideOfPolyline(metroSeg1, metroSeg2, midPt);

        // İç kenar = yol centerline'ından metrobüs tarafına yarı genişlik kadar offset
        const innerEdge = offsetPolylineMeters(road.coords, -side * halfW);

        // Gidiş mi dönüş mü tarafta?
        const distToGidis = distToPolyline(midPt[0], midPt[1], metrobusCenterline);
        const distToDonus = distToPolyline(midPt[0], midPt[1], donusCenterline);

        if (distToGidis <= distToDonus) {
            laneBoundaries.gidis.push(innerEdge);
        } else {
            laneBoundaries.donus.push(innerEdge);
        }
    }

    console.log(`\n🚧 Lane Boundaries:`);
    console.log(`   Gidiş tarafı: ${laneBoundaries.gidis.length} sınır`);
    console.log(`   Dönüş tarafı: ${laneBoundaries.donus.length} sınır`);

    // ---- STEP 5: Gidiş ve dönüş lane polyline'larını üret ----
    // Metrobüs centerline'ını yarı genişlik kadar offset alarak lane üret
    const LANE_OFFSET = 5; // metre — metrobüs şerit genişliği (yarısı)

    const gidisLane = offsetPolylineMeters(metrobusCenterline, LANE_OFFSET);
    const donusLane = offsetPolylineMeters(donusCenterline, -LANE_OFFSET);

    console.log(`\n🛤️ Simülasyon Lane'leri:`);
    console.log(`   Gidiş: ${gidisLane.length} nokta`);
    console.log(`   Dönüş: ${donusLane.length} nokta`);

    // ---- STEP 6: Kaydet ----
    const fs = require('fs');
    const path = require('path');

    const output = `// =============================================
// Lane Boundaries & Simulation Lanes
// Generated: ${new Date().toISOString()}
// Gidiş lane: ${gidisLane.length} nokta
// Dönüş lane: ${donusLane.length} nokta
// Komşu yol iç kenarları: ${laneBoundaries.gidis.length + laneBoundaries.donus.length}
// =============================================

/** Gidiş simülasyon lane'i (+${LANE_OFFSET}m offset) */
export const GIDIS_LANE: [number, number][] = ${JSON.stringify(gidisLane)};

/** Dönüş simülasyon lane'i (-${LANE_OFFSET}m offset) */
export const DONUS_LANE: [number, number][] = ${JSON.stringify(donusLane)};

/** Komşu yol iç kenarları — koridor sınırları */
export const LANE_BOUNDARIES = {
    gidis: ${JSON.stringify(laneBoundaries.gidis)} as [number, number][][],
    donus: ${JSON.stringify(laneBoundaries.donus)} as [number, number][][],
};
`;

    const outPath = path.join(__dirname, '..', 'packages', 'shared', 'src', 'constants', 'lane-boundaries.ts');
    fs.writeFileSync(outPath, output);
    console.log(`\n💾 ${outPath}`);
    console.log('✅ Lane boundary üretimi tamamlandı!');
}

function generateSimpleOffset(network: any) {
    const LANE_OFFSET = 5;
    const fs = require('fs');
    const path = require('path');

    function buildCenterline(edges: any[]): [number, number][] {
        const coords: [number, number][] = [];
        for (const edge of edges) {
            for (const c of edge.geometry) {
                const last = coords[coords.length - 1];
                if (!last || Math.abs(last[0] - c[0]) > 0.00001 || Math.abs(last[1] - c[1]) > 0.00001) {
                    coords.push(c as [number, number]);
                }
            }
        }
        return coords;
    }

    const gidisCL = buildCenterline(network.edges.gidis);
    const donusCL = buildCenterline(network.edges.donus);
    const gidisLane = offsetPolylineMeters(gidisCL, LANE_OFFSET);
    const donusLane = offsetPolylineMeters(donusCL, -LANE_OFFSET);

    const output = `// Lane Boundaries — Simple Offset Fallback
// Generated: ${new Date().toISOString()}

export const GIDIS_LANE: [number, number][] = ${JSON.stringify(gidisLane)};
export const DONUS_LANE: [number, number][] = ${JSON.stringify(donusLane)};
export const LANE_BOUNDARIES = { gidis: [] as [number, number][][], donus: [] as [number, number][][] };
`;

    const outPath = path.join(__dirname, '..', 'packages', 'shared', 'src', 'constants', 'lane-boundaries.ts');
    fs.writeFileSync(outPath, output);
    console.log(`\n💾 ${outPath}`);
}

main().catch(err => { console.error('❌', err.message); process.exit(1); });
