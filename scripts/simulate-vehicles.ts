// =============================================
// Araç Simülasyonu
// Geliştirme/test ortamı için metrobüs hareketi simülasyonu
// =============================================

import {
    STATIONS_EAST,
    haversineDistance,
    calculateBearing,
    moveAlongBearing,
    isRushHour,
    formatDuration,
    COMMAND_DISPLAY_MAP,
    type VehicleState,
    type RouteDirection,
} from '../packages/shared/src/index';

// Simülasyon parametreleri
const NUM_VEHICLES = 8;
const UPDATE_INTERVAL_MS = 3000;
const BASE_SPEED_KMH = 40;
const SPEED_VARIANCE = 15;

interface SimulatedVehicle {
    id: number;
    code: string;
    stationIndex: number;
    progressBetweenStations: number; // 0-1
    speedKmh: number;
    direction: RouteDirection;
    latitude: number;
    longitude: number;
}

// Araçları başlat
const vehicles: SimulatedVehicle[] = [];
for (let i = 0; i < NUM_VEHICLES; i++) {
    const stationIndex = Math.floor((i / NUM_VEHICLES) * STATIONS_EAST.length);
    const station = STATIONS_EAST[stationIndex];
    vehicles.push({
        id: i + 1,
        code: `MB${String(i + 1).padStart(3, '0')}`,
        stationIndex,
        progressBetweenStations: 0,
        speedKmh: BASE_SPEED_KMH + (Math.random() - 0.5) * SPEED_VARIANCE,
        direction: 'east',
        latitude: station.latitude,
        longitude: station.longitude,
    });
}

function updateVehicle(vehicle: SimulatedVehicle): void {
    const stations = STATIONS_EAST;
    const currentStation = stations[vehicle.stationIndex];
    const nextIndex = vehicle.stationIndex + 1;

    if (nextIndex >= stations.length) {
        // Hat sonuna ulaştı, başa dön
        vehicle.stationIndex = 0;
        vehicle.progressBetweenStations = 0;
        vehicle.latitude = stations[0].latitude;
        vehicle.longitude = stations[0].longitude;
        return;
    }

    const nextStation = stations[nextIndex];

    // İki durak arası mesafe
    const segmentDistance = haversineDistance(
        currentStation.latitude,
        currentStation.longitude,
        nextStation.latitude,
        nextStation.longitude
    );

    // Hız varyasyonu (rush hour'da yavaşla)
    const rushFactor = isRushHour() ? 0.6 : 1.0;
    const randomFactor = 0.85 + Math.random() * 0.3;
    vehicle.speedKmh = BASE_SPEED_KMH * rushFactor * randomFactor;

    // İlerleme hesapla
    const metersPerUpdate = (vehicle.speedKmh * 1000 / 3600) * (UPDATE_INTERVAL_MS / 1000);
    vehicle.progressBetweenStations += metersPerUpdate / segmentDistance;

    if (vehicle.progressBetweenStations >= 1) {
        // Sonraki durağa ulaştı
        vehicle.stationIndex = nextIndex;
        vehicle.progressBetweenStations = 0;
        vehicle.latitude = nextStation.latitude;
        vehicle.longitude = nextStation.longitude;
    } else {
        // Ara pozisyon hesapla
        const bearing = calculateBearing(
            currentStation.latitude,
            currentStation.longitude,
            nextStation.latitude,
            nextStation.longitude
        );
        const traveled = segmentDistance * vehicle.progressBetweenStations;
        const pos = moveAlongBearing(
            currentStation.latitude,
            currentStation.longitude,
            bearing,
            traveled
        );
        vehicle.latitude = pos.latitude;
        vehicle.longitude = pos.longitude;
    }
}

function calculateHeadways(): void {
    const sorted = [...vehicles].sort((a, b) => {
        const aPos = a.stationIndex + a.progressBetweenStations;
        const bPos = b.stationIndex + b.progressBetweenStations;
        return aPos - bPos;
    });

    console.log('\n' + '='.repeat(80));
    console.log(`🚍 METROBÜS SİMÜLASYONU — ${new Date().toLocaleTimeString('tr-TR')}`);
    console.log(`   Rush Hour: ${isRushHour() ? '🔴 EVET' : '🟢 HAYIR'}`);
    console.log('='.repeat(80));

    for (let i = 0; i < sorted.length; i++) {
        const v = sorted[i];
        const station = STATIONS_EAST[v.stationIndex];
        const nextStation = STATIONS_EAST[Math.min(v.stationIndex + 1, STATIONS_EAST.length - 1)];

        let headwayInfo = '';
        let command = '';

        if (i > 0) {
            const prev = sorted[i - 1];
            const distance = haversineDistance(v.latitude, v.longitude, prev.latitude, prev.longitude);
            const headwaySeconds = (distance / 1000 / v.speedKmh) * 3600;

            headwayInfo = `  ↕️ ${Math.round(distance)}m (${formatDuration(headwaySeconds)})`;

            // Basit karar simülasyonu
            if (distance < 100) {
                command = `  ${COMMAND_DISPLAY_MAP.SLOW_DOWN.icon} ${COMMAND_DISPLAY_MAP.SLOW_DOWN.title} — Çok yakınsınız!`;
            } else if (distance < 200) {
                command = `  ${COMMAND_DISPLAY_MAP.SLOW_DOWN.icon} ${COMMAND_DISPLAY_MAP.SLOW_DOWN.title}`;
            } else if (distance > 2000) {
                command = `  ${COMMAND_DISPLAY_MAP.SPEED_UP.icon} ${COMMAND_DISPLAY_MAP.SPEED_UP.title} — Arkadaki çok geride`;
            } else {
                command = `  ${COMMAND_DISPLAY_MAP.NORMAL.icon} ${COMMAND_DISPLAY_MAP.NORMAL.title}`;
            }
        }

        console.log(
            `\n  ${v.code} | ${station.name} → ${nextStation.name}` +
            `\n         📍 (${v.latitude.toFixed(4)}, ${v.longitude.toFixed(4)}) | ` +
            `🏎️ ${v.speedKmh.toFixed(0)} km/s` +
            (headwayInfo ? `\n        ${headwayInfo}` : '') +
            (command ? `\n        ${command}` : '')
        );
    }

    console.log('\n' + '-'.repeat(80));
}

// Simülasyonu çalıştır
console.log('🚀 Simülasyon başlatılıyor...');
console.log(`   ${NUM_VEHICLES} araç, ${STATIONS_EAST.length} durak`);
console.log(`   Güncelleme aralığı: ${UPDATE_INTERVAL_MS}ms`);
console.log('   Ctrl+C ile durdurun\n');

setInterval(() => {
    vehicles.forEach(updateVehicle);
    calculateHeadways();
}, UPDATE_INTERVAL_MS);

// İlk çıktıyı hemen göster
calculateHeadways();
