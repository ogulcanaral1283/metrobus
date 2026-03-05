/**
 * Fetch bus stop_position nodes from Overpass
 * These are the exact points where metrobuses stop at each station.
 * Multiple stop_positions per station = multiple slots.
 */

const fs = require('fs');
const path = require('path');

const OVERPASS = 'https://overpass-api.de/api/interpreter';

const QUERY = `[out:json][timeout:120];
area["name"="İstanbul"]["admin_level"="4"]->.istanbul;

(
  relation(area.istanbul)["type"="route"]["route"="bus"]["from"~"Beylikdüzü|TÜYAP|TUYAP", i]["to"~"Söğütlüçeşme", i];
  relation(area.istanbul)["type"="route"]["route"="bus"]["from"~"Söğütlüçeşme", i]["to"~"Beylikdüzü|TÜYAP|TUYAP", i];
)->.routes;

node(r.routes)
  ["public_transport"="stop_position"]
  ["bus"="yes"]->.bus_stop_positions;

.bus_stop_positions out body qt;`;

interface StopPositionNode {
    type: 'node';
    id: number;
    lat: number;
    lon: number;
    tags: Record<string, string>;
}

async function fetchWithRetry(maxRetries = 8): Promise<StopPositionNode[]> {
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
        try {
            console.log(`🔄 Overpass sorgusu (deneme ${attempt}/${maxRetries})...`);
            const res = await fetch(OVERPASS, {
                method: 'POST',
                body: `data=${encodeURIComponent(QUERY)}`,
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            });
            if (res.status === 504 || res.status === 429) {
                const wait = 15000 * attempt;
                console.log(`   ⚠️ ${res.status} — ${Math.round(wait / 1000)}sn bekleniyor...`);
                await new Promise(r => setTimeout(r, wait));
                continue;
            }
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            return data.elements as StopPositionNode[];
        } catch (err: any) {
            console.error(`   ❌ Hata: ${err.message}`);
            if (attempt === maxRetries) throw err;
            await new Promise(r => setTimeout(r, 15000 * attempt));
        }
    }
    throw new Error('Tüm denemeler başarısız');
}

function haversine(lat1: number, lon1: number, lat2: number, lon2: number): number {
    const R = 6371000;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

async function main() {
    console.log('🚏 Stop Position Fetcher\n');

    const nodes = await fetchWithRetry();
    console.log(`\n✅ ${nodes.length} stop_position node bulundu\n`);

    // Durak adlarına göre grupla
    const groups = new Map<string, StopPositionNode[]>();
    for (const n of nodes) {
        const name = n.tags?.name || n.tags?.['name:tr'] || `unknown_${n.id}`;
        if (!groups.has(name)) groups.set(name, []);
        groups.get(name)!.push(n);
    }

    console.log(`📊 ${groups.size} benzersiz durak adı\n`);

    // Her durak grubu için: slot sayısı ve platform uzunluğu hesapla
    interface StationSlotInfo {
        name: string;
        stopPositions: { id: number; lat: number; lon: number }[];
        slotCount: number;
        platformLengthMeters: number;
    }

    const stationSlots: StationSlotInfo[] = [];

    for (const [name, positions] of groups) {
        // Lat'a göre sırala (yaklaşık hat boyunca pozisyon)
        positions.sort((a, b) => {
            // Lon farkı genelde daha büyük (batı-doğu hattı)
            const lonDiff = a.lon - b.lon;
            const latDiff = a.lat - b.lat;
            return Math.abs(lonDiff) > Math.abs(latDiff) ? lonDiff : latDiff;
        });

        // Platform uzunluğu: en uzak iki stop_position arası mesafe
        let maxDist = 0;
        for (let i = 0; i < positions.length; i++) {
            for (let j = i + 1; j < positions.length; j++) {
                const d = haversine(positions[i].lat, positions[i].lon, positions[j].lat, positions[j].lon);
                if (d > maxDist) maxDist = d;
            }
        }

        stationSlots.push({
            name,
            stopPositions: positions.map(p => ({ id: p.id, lat: p.lat, lon: p.lon })),
            slotCount: positions.length,
            platformLengthMeters: Math.round(maxDist),
        });

        const emoji = positions.length >= 3 ? '🟢' : positions.length >= 2 ? '🟡' : '🔴';
        console.log(`   ${emoji} ${name}: ${positions.length} slot, ${Math.round(maxDist)}m platform`);
    }

    // Sort by slot count desc for summary
    stationSlots.sort((a, b) => b.slotCount - a.slotCount);

    console.log(`\n📈 Özet:`);
    console.log(`   Toplam stop_position: ${nodes.length}`);
    console.log(`   Durak sayısı: ${stationSlots.length}`);
    console.log(`   Max slot: ${Math.max(...stationSlots.map(s => s.slotCount))} (${stationSlots[0]?.name})`);
    console.log(`   Min slot: ${Math.min(...stationSlots.map(s => s.slotCount))}`);
    console.log(`   Ort platform: ${Math.round(stationSlots.reduce((s, x) => s + x.platformLengthMeters, 0) / stationSlots.length)}m`);

    // TypeScript dosyası olarak kaydet
    const output = `// Station Stop Positions — Overpass API'den
// Generated: ${new Date().toISOString()}
// ${stationSlots.length} durak, ${nodes.length} stop_position

export interface StopPosition {
    id: number;
    lat: number;
    lon: number;
}

export interface StationSlotInfo {
    /** Durak adı */
    name: string;
    /** Bu duraktaki stop_position noktaları */
    stopPositions: StopPosition[];
    /** Slot sayısı (kaç otobüs aynı anda durabilir) */
    slotCount: number;
    /** Platform uzunluğu (metre) — en uzak iki slot arası */
    platformLengthMeters: number;
}

export const STATION_SLOTS: StationSlotInfo[] = ${JSON.stringify(stationSlots, null, 2)};
`;

    const outPath = path.join(__dirname, '..', 'packages', 'shared', 'src', 'constants', 'station-slots.ts');
    fs.writeFileSync(outPath, output);
    console.log(`\n💾 ${outPath}`);
    console.log('✅ Tamamlandı!');
}

main().catch(err => { console.error('❌', err); process.exit(1); });
