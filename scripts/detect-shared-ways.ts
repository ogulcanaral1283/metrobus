/**
 * Shared Way Detector — Kullanıcının Overpass QL sorgusunu çalıştırır
 * ve shared way ID'lerini tespit eder.
 *
 * Çıktı: shared-way-ids.ts (SHARED_WAY_IDS set)
 *
 * Kullanım: npx tsx scripts/detect-shared-ways.ts
 */

const OVERPASS = 'https://overpass-api.de/api/interpreter';

const QUERY = `[out:json][timeout:120];
area["name"="İstanbul"]["admin_level"="4"]->.istanbul;

relation(area.istanbul)
  ["type"="route"]["route"="bus"]
  ["from"~"Beylikdüzü|TÜYAP", i]
  ["to"~"Söğütlüçeşme", i]
  ->.gidis_rel;

relation(area.istanbul)
  ["type"="route"]["route"="bus"]
  ["from"~"Söğütlüçeşme", i]
  ["to"~"Beylikdüzü|TÜYAP", i]
  ->.donus_rel;

way(r.gidis_rel)->.gidis_ways;
way(r.donus_rel)->.donus_ways;

way.gidis_ways.donus_ways->.shared_ways;

.shared_ways out body;
>;
out skel qt;`;

async function fetchWithRetry(): Promise<any> {
    for (let attempt = 1; ; attempt++) {
        console.log(`📡 Deneme ${attempt}...`);
        try {
            const res = await fetch(OVERPASS, {
                method: 'POST',
                body: `data=${encodeURIComponent(QUERY)}`,
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            });
            if (res.ok) {
                const data = await res.json();
                console.log(`✅ Başarılı — deneme ${attempt}`);
                return data;
            }
            console.log(`⚠️ HTTP ${res.status}`);
        } catch (err: any) {
            console.log(`⚠️ Hata: ${err.message}`);
        }
        const wait = Math.min(10 * Math.pow(2, attempt - 1), 120);
        console.log(`⏳ ${wait}s bekleniyor...`);
        await new Promise(r => setTimeout(r, wait * 1000));
    }
}

async function main() {
    console.log('🔍 Shared Way Detector\n');

    const data = await fetchWithRetry();
    const elements = data.elements;
    console.log(`📦 ${elements.length} element alındı`);

    // Sadece way'leri topla — bunlar shared way'ler
    const sharedWayIds: number[] = [];
    for (const e of elements) {
        if (e.type === 'way') {
            sharedWayIds.push(e.id);
        }
    }

    console.log(`🔴 ${sharedWayIds.length} shared way tespit edildi`);
    console.log(`   IDs: ${sharedWayIds.slice(0, 10).join(', ')}${sharedWayIds.length > 10 ? '...' : ''}`);

    // Kaydet
    const fs = require('fs');
    const path = require('path');

    const output = `// =============================================
// Shared Way IDs — Gidiş ∩ Dönüş ortak way'ler
// Generated: ${new Date().toISOString()}
// Count: ${sharedWayIds.length} shared way
// =============================================

/** Gidiş ve dönüş rotalarının ortak kullandığı OSM way ID'leri */
export const SHARED_WAY_IDS: Set<number> = new Set(${JSON.stringify(sharedWayIds)});
`;

    const outPath = path.join(__dirname, '..', 'packages', 'shared', 'src', 'constants', 'shared-way-ids.ts');
    fs.writeFileSync(outPath, output);
    console.log(`💾 ${outPath}`);
    console.log('✅ Tamamlandı!');
}

main().catch(err => { console.error('❌', err); process.exit(1); });
