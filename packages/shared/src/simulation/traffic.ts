// =============================================
// Trafik Bölge Yönetimi
// Rastgele tıkanıklık oluşturma/çözme + rush hour
// =============================================

import type { TrafficZone, SimConfig } from './sim-types';

/**
 * Trafik bölgelerini güncelle:
 * - Mevcut bölgelerin süresini düşür
 * - Süresi dolan bölgeleri kaldır
 * - Rastgele yeni bölge oluştur
 */
export function updateTrafficZones(
    zones: TrafficZone[],
    dt: number,
    routeLength: number,
    config: SimConfig,
    isRushHour: boolean,
): TrafficZone[] {
    // Süreleri düşür, bitenleri kaldır
    const active = zones.filter(z => {
        z.remainingSeconds -= dt;
        return z.remainingSeconds > 0;
    });

    // Yeni bölge oluştur (rastgele)
    const spawnRate = isRushHour ? config.trafficSpawnRate * 3 : config.trafficSpawnRate;
    if (Math.random() < spawnRate * dt && active.length < 5) {
        const severity = pickSeverity(isRushHour);
        const start = 500 + Math.random() * (routeLength - 1000);
        const length = 200 + Math.random() * 500;

        active.push({
            startMeter: start,
            endMeter: start + length,
            maxSpeedMs: severityToSpeed(severity),
            remainingSeconds: config.trafficDuration * (0.5 + Math.random()),
            severity,
        });
    }

    return active;
}

function pickSeverity(isRushHour: boolean): 'light' | 'moderate' | 'heavy' {
    const r = Math.random();
    if (isRushHour) {
        if (r < 0.3) return 'heavy';
        if (r < 0.7) return 'moderate';
        return 'light';
    }
    if (r < 0.1) return 'heavy';
    if (r < 0.3) return 'moderate';
    return 'light';
}

function severityToSpeed(severity: 'light' | 'moderate' | 'heavy'): number {
    switch (severity) {
        case 'light': return 11.0;    // ~40 km/h
        case 'moderate': return 5.5;  // ~20 km/h
        case 'heavy': return 2.0;     // ~7 km/h (dur-kalk)
    }
}

/**
 * Simülasyon saatine göre rush hour kontrolü.
 * Sabah: 07:00-09:30, Akşam: 17:00-19:30
 */
export function checkRushHour(simTimeSeconds: number): boolean {
    // Simülasyon zamanını gün içindeki saat'e çevir
    // Başlangıç: 06:00 olarak kabul et
    const startHour = 6;
    const hourOfDay = startHour + (simTimeSeconds / 3600) % 24;

    return (hourOfDay >= 7 && hourOfDay <= 9.5) ||
        (hourOfDay >= 17 && hourOfDay <= 19.5);
}
