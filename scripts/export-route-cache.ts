/**
 * JS linearization'ı JSON cache dosyasına dışa aktar.
 * Python tarafı bu cache'i yükleyerek JS ile birebir aynı
 * segment ve durak pozisyonlarını kullanır.
 *
 * Kullanım:
 *   npx tsx scripts/export-route-cache.ts
 */

import * as fs from 'fs';
import * as path from 'path';
import { linearizeRoute, meterToPosition } from '../packages/shared/src/simulation/route-linearizer';

const routeDataPath = path.join(__dirname, '..', 'rl_env', 'data', 'route_network.json');
const routeData = JSON.parse(fs.readFileSync(routeDataPath, 'utf-8'));

for (const direction of ['gidis', 'donus'] as const) {
    const edges = routeData.edges[direction];
    const stops = routeData.stops[direction];

    if (!edges || !stops) {
        console.log(`  ${direction}: veri yok, atlanıyor`);
        continue;
    }

    const route = linearizeRoute(edges, stops, direction);

    // Segment verilerini dışa aktar
    const segments = route.segments.map(s => ({
        start_meter: Math.round(s.startMeter * 1000) / 1000,
        end_meter: Math.round(s.endMeter * 1000) / 1000,
        lat1: s.startLat,
        lng1: s.startLng,
        lat2: s.endLat,
        lng2: s.endLng,
        length: Math.round(s.length * 1000) / 1000,
        bearing: Math.round(s.bearing * 100) / 100,
    }));

    // Durak verilerini dışa aktar — hem meter position hem de bu pozisyondan
    // hesaplanan lat/lng (meterToPosition ile)
    const stopsExport = route.stops.map(s => {
        const pos = meterToPosition(route, s.meterPosition);
        return {
            index: s.index,
            name: s.name,
            meter_position: Math.round(s.meterPosition * 1000) / 1000,
            // Orijinal lat/lng (OSM'den)
            original_latitude: s.latitude,
            original_longitude: s.longitude,
            // Linearized lat/lng (segment üzerine project edilmiş)
            latitude: pos.latitude,
            longitude: pos.longitude,
            heading: Math.round(pos.heading * 100) / 100,
            slot_count: s.slotCount,
            platform_length_meters: s.platformLengthMeters,
        };
    });

    const cache = {
        direction,
        total_length: Math.round(route.totalLength * 1000) / 1000,
        segment_count: segments.length,
        stop_count: stopsExport.length,
        segments,
        stops: stopsExport,
    };

    const outPath = path.join(
        __dirname, '..', 'rl_env', 'data', `route_cache_${direction}.json`
    );
    fs.writeFileSync(outPath, JSON.stringify(cache, null, 2), 'utf-8');
    console.log(`✓ ${direction}: ${segments.length} segment, ${stopsExport.length} durak → ${outPath}`);
    console.log(`  Toplam uzunluk: ${(route.totalLength / 1000).toFixed(2)} km`);
}

console.log('\nTamamlandı!');
