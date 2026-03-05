/**
 * Synthetic Dual Lane Generator — v7
 * 
 * Yeni: Offset tarafı otomatik tespit edilir.
 * Her koridorun öncesindeki/sonrasındaki non-shared GİDİŞ edge'inin
 * pozisyonuna bakarak +offset mi -offset mi olduğu belirlenir.
 * Böylece kuzey-güney, doğu-batı fark etmez — gidiş/dönüş her zaman
 * doğru tarafta olur.
 */

const fs = require('fs');
const path = require('path');

const AVG_LAT = 41.0;
const LAT_DEG_PER_M = 1 / 111320;
const LON_DEG_PER_M = 1 / (111320 * Math.cos(AVG_LAT * Math.PI / 180));

function haversineDist(lat1: number, lon1: number, lat2: number, lon2: number): number {
    const R = 6371000;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function ptDist(a: [number, number], b: [number, number]): number {
    return haversineDist(a[0], a[1], b[0], b[1]);
}

function variableOffsetLine(coords: [number, number][], offsetPerPoint: number[]): [number, number][] {
    if (coords.length < 2) return coords;
    const MITER_LIMIT = 2.0;
    const segNormals: { nx: number; ny: number }[] = [];
    for (let i = 0; i < coords.length - 1; i++) {
        const dy = (coords[i + 1][0] - coords[i][0]) / LAT_DEG_PER_M;
        const dx = (coords[i + 1][1] - coords[i][1]) / LON_DEG_PER_M;
        const len = Math.sqrt(dx * dx + dy * dy);
        segNormals.push(len === 0 ? { nx: 0, ny: 0 } : { nx: -dy / len, ny: dx / len });
    }
    const result: [number, number][] = [];
    for (let i = 0; i < coords.length; i++) {
        let nx: number, ny: number;
        if (i === 0) { nx = segNormals[0].nx; ny = segNormals[0].ny; }
        else if (i === coords.length - 1) { nx = segNormals[segNormals.length - 1].nx; ny = segNormals[segNormals.length - 1].ny; }
        else {
            const n1 = segNormals[i - 1], n2 = segNormals[i];
            nx = n1.nx + n2.nx; ny = n1.ny + n2.ny;
            const ml = Math.sqrt(nx * nx + ny * ny);
            if (ml < 0.001) { nx = n1.nx; ny = n1.ny; }
            else {
                nx /= ml; ny /= ml;
                const dot = n1.nx * n2.nx + n1.ny * n2.ny;
                if (1 / Math.max(0.5, (1 + dot) / 2) > MITER_LIMIT) { nx = n1.nx; ny = n1.ny; }
            }
        }
        result.push([
            coords[i][0] + nx * offsetPerPoint[i] * LAT_DEG_PER_M,
            coords[i][1] + ny * offsetPerPoint[i] * LON_DEG_PER_M,
        ]);
    }
    return result;
}

function densify(coords: [number, number][], maxSeg: number = 10): [number, number][] {
    if (coords.length < 2) return coords;
    const result: [number, number][] = [coords[0]];
    for (let i = 1; i < coords.length; i++) {
        const d = ptDist(coords[i - 1], coords[i]);
        if (d > maxSeg) {
            const steps = Math.ceil(d / maxSeg);
            for (let s = 1; s < steps; s++) {
                const t = s / steps;
                result.push([
                    coords[i - 1][0] + t * (coords[i][0] - coords[i - 1][0]),
                    coords[i - 1][1] + t * (coords[i][1] - coords[i - 1][1]),
                ]);
            }
        }
        result.push(coords[i]);
    }
    return result;
}

function chaikinSmooth(coords: [number, number][], iterations: number = 1): [number, number][] {
    let pts = coords;
    for (let iter = 0; iter < iterations; iter++) {
        if (pts.length < 3) break;
        const s: [number, number][] = [pts[0]];
        for (let i = 0; i < pts.length - 1; i++) {
            s.push([pts[i][0] * 0.75 + pts[i + 1][0] * 0.25, pts[i][1] * 0.75 + pts[i + 1][1] * 0.25]);
            s.push([pts[i][0] * 0.25 + pts[i + 1][0] * 0.75, pts[i][1] * 0.25 + pts[i + 1][1] * 0.75]);
        }
        s.push(pts[pts.length - 1]);
        pts = s;
    }
    return pts;
}

function cumulativeDistances(coords: [number, number][]): number[] {
    const d = [0];
    for (let i = 1; i < coords.length; i++) d.push(d[i - 1] + ptDist(coords[i - 1], coords[i]));
    return d;
}

function buildTaperOffsets(coords: [number, number][], maxOff: number, taperDist: number, tapS: boolean, tapE: boolean): number[] {
    const dists = cumulativeDistances(coords);
    const total = dists[dists.length - 1];
    return coords.map((_, i) => {
        let f = 1;
        if (tapS && dists[i] < taperDist) f = Math.min(f, Math.sin(dists[i] / taperDist * Math.PI / 2));
        if (tapE && (total - dists[i]) < taperDist) f = Math.min(f, Math.sin((total - dists[i]) / taperDist * Math.PI / 2));
        return maxOff * f;
    });
}

/**
 * Offset tarafını otomatik belirle.
 * Komşu non-shared DONUS edge'inin pozisyonuna bak.
 * +offset ve -offset'ten hangisi dönüş edge'ine daha yakınsa,
 * dönüş o tarafa, gidiş diğer tarafa.
 */
function detectOffsetSign(
    centerline: [number, number][],
    donusEdges: any[],
    sharedWayIds: Set<number>,
    gidisRunStart: number,
    gidisRunEnd: number,
    gidisEdges: any[],
): number {
    // Centerline'ın ortasındaki noktayı al
    const midIdx = Math.floor(centerline.length / 2);
    const midPt = centerline[midIdx];

    // +1m ve -1m test offset
    const testDist = 3.0;
    // Centerline'daki yön
    const i0 = Math.max(0, midIdx - 1);
    const i1 = Math.min(centerline.length - 1, midIdx + 1);
    const dy = (centerline[i1][0] - centerline[i0][0]) / LAT_DEG_PER_M;
    const dx = (centerline[i1][1] - centerline[i0][1]) / LON_DEG_PER_M;
    const len = Math.sqrt(dx * dx + dy * dy);
    if (len === 0) return 1;
    const nx = -dy / len, ny = dx / len;

    const testPlus: [number, number] = [
        midPt[0] + nx * testDist * LAT_DEG_PER_M,
        midPt[1] + ny * testDist * LON_DEG_PER_M,
    ];
    const testMinus: [number, number] = [
        midPt[0] - nx * testDist * LAT_DEG_PER_M,
        midPt[1] - ny * testDist * LON_DEG_PER_M,
    ];

    // En yakın non-shared DÖNÜŞ edge noktasını bul
    let minDistPlus = Infinity, minDistMinus = Infinity;
    for (const e of donusEdges) {
        if (sharedWayIds.has(e.osmWayId)) continue;
        for (const pt of e.geometry) {
            const dp = ptDist(testPlus, pt);
            const dm = ptDist(testMinus, pt);
            if (dp < minDistPlus) minDistPlus = dp;
            if (dm < minDistMinus) minDistMinus = dm;
        }
    }

    // Dönüş +offset'e daha yakınsa → gidiş = -offset
    // Dönüş -offset'e daha yakınsa → gidiş = +offset
    if (minDistPlus < minDistMinus) {
        return -1; // gidiş = -offset (dönüş + tarafta)
    }
    return 1; // gidiş = +offset (dönüş - tarafta)
}

async function main() {
    console.log('🔧 Synthetic Dual Lane v7 (auto side detection)\n');
    const { ROUTE_NETWORK } = require('../packages/shared/src/constants/route-network-data');
    const { SHARED_WAY_IDS } = require('../packages/shared/src/constants/shared-way-ids');

    const MAX_OFFSET = 3.5;
    const TAPER_DIST = 50;
    const gidisEdges = ROUTE_NETWORK.edges.gidis;
    const donusEdges = ROUTE_NETWORK.edges.donus;

    function isShared(edge: any): boolean { return SHARED_WAY_IDS.has(edge.osmWayId); }

    function findRuns(edges: any[]): { start: number; end: number }[] {
        const runs: { start: number; end: number }[] = [];
        let i = 0;
        while (i < edges.length) {
            if (isShared(edges[i])) {
                const s = i;
                while (i < edges.length && isShared(edges[i])) i++;
                runs.push({ start: s, end: i - 1 });
            } else i++;
        }
        return runs;
    }

    function mergeCorridor(edges: any[], start: number, end: number): [number, number][] {
        const merged: [number, number][] = [];
        for (let i = start; i <= end; i++) {
            for (const pt of edges[i].geometry) {
                const last = merged[merged.length - 1];
                if (!last || ptDist(last, pt) > 0.3) merged.push(pt);
            }
        }
        return merged;
    }

    interface SyntheticLane { corridorIndex: number; geometry: [number, number][]; }

    const runs = findRuns(gidisEdges);
    console.log(`📊 ${runs.length} shared koridor\n`);

    const gidisLanes: SyntheticLane[] = [];
    const donusLanes: SyntheticLane[] = [];

    for (let ri = 0; ri < runs.length; ri++) {
        const run = runs[ri];
        let centerline = mergeCorridor(gidisEdges, run.start, run.end);
        centerline = densify(centerline, 10);

        // Otomatik taraf tespiti
        const sign = detectOffsetSign(centerline, donusEdges, SHARED_WAY_IDS, run.start, run.end, gidisEdges);

        const hasPrev = run.start > 0;
        const hasNext = run.end < gidisEdges.length - 1;

        // Gidiş offset = sign * MAX_OFFSET, Dönüş = -sign * MAX_OFFSET
        const gOffsets = buildTaperOffsets(centerline, sign * MAX_OFFSET, TAPER_DIST, hasPrev, hasNext);
        const dOffsets = buildTaperOffsets(centerline, -sign * MAX_OFFSET, TAPER_DIST, hasPrev, hasNext);

        let gidisLine = variableOffsetLine(centerline, gOffsets);
        let donusLine = variableOffsetLine(centerline, dOffsets);

        gidisLine = chaikinSmooth(gidisLine, 1);
        donusLine = chaikinSmooth(donusLine, 1);

        // Dönüş ters yön
        donusLine = donusLine.reverse();

        gidisLanes.push({ corridorIndex: ri, geometry: gidisLine });
        donusLanes.push({ corridorIndex: ri, geometry: donusLine });

        const totalLen = cumulativeDistances(centerline);
        console.log(`   K${ri}: [${run.start}..${run.end}] ${Math.round(totalLen[totalLen.length - 1])}m sign=${sign > 0 ? '+' : '-'} → g:${gidisLine.length} d:${donusLine.length}`);
    }

    const output = `// Synthetic Dual Lanes — ±${MAX_OFFSET}m (auto-side, taper, smooth)
// Generated: ${new Date().toISOString()}
// ${gidisLanes.length} koridor

export interface SyntheticLane {
    corridorIndex: number;
    geometry: [number, number][];
}

export const GIDIS_SYNTHETIC_LANES: SyntheticLane[] = ${JSON.stringify(gidisLanes)};
export const DONUS_SYNTHETIC_LANES: SyntheticLane[] = ${JSON.stringify(donusLanes)};
`;

    const outPath = path.join(__dirname, '..', 'packages', 'shared', 'src', 'constants', 'synthetic-lanes.ts');
    fs.writeFileSync(outPath, output);
    console.log(`\n💾 ${outPath}`);
    console.log('✅ Tamamlandı!');
}

main().catch(err => { console.error('❌', err); process.exit(1); });
