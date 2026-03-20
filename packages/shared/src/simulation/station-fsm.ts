// =============================================
// Durak State Machine (FSM) — Paralel Peron Operasyonu
//
// TEMEL PRENSİP: Araçlar peron alanı içine girdiği anda
// yolcu operasyonuna BAŞLAR. En öne gitmeyi BEKLEMEZler.
//
// Paralel Operasyon:
//   - Peron üzerinde 3 araç aynı anda kapı açık olabilir
//   - Her araç kendi dwellRemaining'ini bağımsız sayar
//   - Süre dolan araç, önü açılınca kalkış yapar
//   - İleri kayma YOK — araç durduğu yerde kalır
//
// State Machine:
//   cruising    → approaching  (approachDistance metre kala)
//   approaching → queued       (peron dolu — yer yok)
//   approaching → docking      (peron alanında yer var)
//   queued      → docking      (yer boşaldı)
//   docking     → stopped      (pozisyona ulaştı → ANINDA yolcu op.)
//   stopped     → doorsClosed  (dwell doldu)
//   doorsClosed → blocked      (gap < SAFE_GAP)
//   doorsClosed → departing    (gap >= SAFE_GAP veya önde araç yok)
//   blocked     → departing    (önü açıldı)
//   departing   → cruising     (hız > 3 m/s)
//
// ÖNEMLİ:
//   - İleri kayma (shifting) YOK — araç nerede durduysa orada kalır
//   - Dwell süresi ARACA aittir, pozisyona bağlı değildir
//   - Peron alanı = [stop.meterPosition - platformLengthMeters, stop.meterPosition]
// =============================================

import type { SimVehicle, SimConfig, LinearStop } from './sim-types';
import { VEHICLE_GAP } from './sim-types';

/** Güvenli kalkış mesafesi (metre) */
const SAFE_GAP = 0.5;

// ============================================
// Yardımcı Fonksiyonlar
// ============================================

/**
 * Araç peron alanı içinde mi?
 * Peron alanı = [stop.meterPosition - platformLengthMeters, stop.meterPosition + 2]
 */
function isInsidePlatformZone(
    vehiclePosition: number,
    vehicleLength: number,
    stop: LinearStop,
): boolean {
    const vehicleRear = vehiclePosition - vehicleLength;
    const platformStart = stop.meterPosition - stop.platformLengthMeters;
    const platformEnd = stop.meterPosition + 2; // 2m tolerans

    return vehiclePosition <= platformEnd && vehicleRear >= platformStart - 1;
}

/**
 * Perondaki tüm araçları al (fiziksel olarak orada olanlar).
 * stopped + doorsClosed + blocked + docking hepsi peronda.
 * En öndeki (yüksek meter) → en arkadaki (düşük meter) sırasıyla.
 */
function getVehiclesOnPlatform(
    stopIndex: number,
    allVehicles: SimVehicle[],
): SimVehicle[] {
    return allVehicles
        .filter(v =>
            (v.phase === 'stopped' || v.phase === 'doorsClosed' ||
                v.phase === 'blocked' || v.phase === 'docking') &&
            v.nextStopIndex === stopIndex
        )
        .sort((a, b) => b.positionMeters - a.positionMeters);
}

/**
 * Araç için durma pozisyonu hesapla.
 * Peronun en önüne (boşsa) veya en arkadaki aracın arkasına durur.
 */
function computeEntryPosition(
    stop: LinearStop,
    platformVehicles: SimVehicle[],
): number {
    if (platformVehicles.length === 0) {
        return stop.meterPosition;
    }
    const lastVehicle = platformVehicles[platformVehicles.length - 1];
    const lastRear = lastVehicle.positionMeters - lastVehicle.vehicleType.lengthMeters;
    return lastRear - VEHICLE_GAP;
}

/**
 * Aracın tamamı peron alanına sığıyor mu?
 */
function fitsInPlatform(
    stopPosition: number,
    vehicleLengthMeters: number,
    stop: LinearStop,
): boolean {
    const vehicleRear = stopPosition - vehicleLengthMeters;
    const platformStart = stop.meterPosition - stop.platformLengthMeters;
    const frontOk = stopPosition <= stop.meterPosition + 2;
    const rearOk = vehicleRear >= platformStart - 1;
    return frontOk && rearOk;
}

/**
 * PHYSICAL GAP KONTROLÜ — önde engel var mı?
 *
 * Kalkış şartı: önde hiç araç yok VEYA öndeki aracın
 * arka tamponu ile bizim ön tamponumuz arasında >= SAFE_GAP
 *
 * @returns true = blokeli (gap < SAFE_GAP), kalkaMAZ
 */
function isBlockedByGap(
    vehicle: SimVehicle,
    stopIndex: number,
    allVehicles: SimVehicle[],
): boolean {
    for (const v of allVehicles) {
        if (v.id === vehicle.id) continue;
        if (v.positionMeters <= vehicle.positionMeters) continue;

        // Aynı duraktaki statik araçlar → kesin engel
        if ((v.phase === 'stopped' || v.phase === 'doorsClosed' || v.phase === 'blocked') &&
            v.nextStopIndex === stopIndex) {
            return true;
        }

        // Departing araç — fiziksel gap kontrolü
        if (v.phase === 'departing') {
            const vRear = v.positionMeters - v.vehicleType.lengthMeters;
            const gap = vRear - vehicle.positionMeters;
            if (gap < SAFE_GAP) {
                return true;
            }
        }
    }
    return false;
}

/**
 * Peron üzerinde bu aracın EN YAKIN önündeki aracı bul.
 * Sadece aynı durakta duran/docking/blocked/doorsClosed araçları kontrol eder.
 *
 * @returns En yakın öndeki araç veya null
 */
function findNearestLeaderOnPlatform(
    vehicle: SimVehicle,
    allVehicles: SimVehicle[],
): SimVehicle | null {
    let nearest: SimVehicle | null = null;
    let nearestDist = Infinity;

    for (const v of allVehicles) {
        if (v.id === vehicle.id) continue;
        if (v.nextStopIndex !== vehicle.nextStopIndex) continue;
        if (v.positionMeters <= vehicle.positionMeters) continue;

        if (v.phase === 'stopped' || v.phase === 'doorsClosed' ||
            v.phase === 'blocked' || v.phase === 'docking') {
            const dist = v.positionMeters - vehicle.positionMeters;
            if (dist < nearestDist) {
                nearestDist = dist;
                nearest = v;
            }
        }
    }
    return nearest;
}

// ============================================
// Ana FSM Güncelleme
// ============================================

/**
 * Durak state machine — PARALEL PERON OPERASYONU.
 *
 * Araç peron alanına girip durduğu anda yolcu operasyonu başlar.
 * En öne gitmeyi beklemez. Birden fazla araç aynı anda kapı açık.
 */
export function updateStationFSM(
    vehicle: SimVehicle,
    dt: number,
    stops: LinearStop[],
    config: SimConfig,
    _isRushHour: boolean,
    _stationOccupancy: Map<number, number>,
    _occupiedSlots?: Map<string, Set<number>>,
    allVehicles?: SimVehicle[],
): void {
    if (vehicle.nextStopIndex >= stops.length) return;

    const nextStop = stops[vehicle.nextStopIndex];
    const distToStop = nextStop.meterPosition - vehicle.positionMeters;
    const vehicleList = allVehicles ?? [];

    switch (vehicle.phase) {

        // ============================================
        // CRUISING
        // ============================================
        case 'cruising': {
            // Peron alanına girildiyse → approaching'e geç
            // (uzun peronlarda approachDistance'dan ÖNCE girilebilir)
            const vLen = vehicle.vehicleType.lengthMeters;
            const inPlatformZone = isInsidePlatformZone(vehicle.positionMeters, vLen, nextStop);

            if (inPlatformZone && distToStop > 0) {
                vehicle.phase = 'approaching';
                break;
            }

            // Normal yaklaşma mesafesi
            if (distToStop > 0 && distToStop < config.approachDistance) {
                vehicle.phase = 'approaching';
            }
            if (distToStop <= 0) {
                vehicle.nextStopIndex++;
            }
            break;
        }

        // ============================================
        // APPROACHING — Durağa frenleme
        //
        // ALAN TABANLI GİRİŞ (Zone-Based Entry):
        //   Araç peron alanına girdiğinde:
        //   - Önde araç varsa → arkasında dur (early stop)
        //   - Önde araç yoksa → peronun önüne git
        //   - Peron dolu → queued
        // ============================================
        case 'approaching': {
            const vLen = vehicle.vehicleType.lengthMeters;
            const inZone = isInsidePlatformZone(vehicle.positionMeters, vLen, nextStop);

            // === PERON ALANI İÇİNDE Mİ? ===
            if (inZone && vehicle.speed < 0.5) {
                // Araç peron alanı içinde ve neredeyse durmuş
                // → DOĞRUDAN stopped fazına geç (en yakın boşlukta dur)
                vehicle.phase = 'stopped';
                vehicle.speed = 0;
                vehicle.acceleration = 0;
                vehicle.slotMeterPosition = vehicle.positionMeters;
                vehicle.isQueuing = false;
                vehicle.queueWaitTime = 0;

                // Dwell ANINDA başlar
                const dwellTime = computeDwellTime(config);
                vehicle.dwellRemaining = 1.0 + dwellTime;
                vehicle.lastDwellTime = dwellTime;
                vehicle.totalStops++;
                break;
            }

            // === PERON ALANI İÇİNDE AMA HÂLÂ HAREKET EDİYOR ===
            if (inZone && vehicle.speed >= 0.5) {
                // Önde duran araç var mı? Varsa ona göre hedef pozisyon belirle
                const leader = findNearestLeaderOnPlatform(vehicle, vehicleList);
                if (leader) {
                    const leaderRear = leader.positionMeters - leader.vehicleType.lengthMeters;
                    const gap = leaderRear - vehicle.positionMeters;

                    if (gap < SAFE_GAP) {
                        // Öndeki araca çok yakın → BURADA DUR, dwell başlat
                        vehicle.phase = 'stopped';
                        vehicle.speed = 0;
                        vehicle.acceleration = 0;
                        vehicle.slotMeterPosition = vehicle.positionMeters;
                        vehicle.isQueuing = false;

                        const dwellTime = computeDwellTime(config);
                        vehicle.dwellRemaining = 1.0 + dwellTime;
                        vehicle.lastDwellTime = dwellTime;
                        vehicle.totalStops++;
                        break;
                    }
                }
                // Önde araç yok veya yeterli gap var → frenlemeye devam, fizik yönetir
                break;
            }

            // === PERON ALANI DIŞINDA — eski mantık (yaklaşma) ===
            const platformVehicles = getVehiclesOnPlatform(vehicle.nextStopIndex, vehicleList);
            const entryPos = computeEntryPosition(nextStop, platformVehicles);

            if (vehicle.speed < 3.0 && distToStop < 8 && distToStop > -5) {
                if (fitsInPlatform(entryPos, vehicle.vehicleType.lengthMeters, nextStop)) {
                    vehicle.phase = 'docking';
                    vehicle.isQueuing = false;
                    vehicle.queueWaitTime = 0;
                    vehicle.slotMeterPosition = entryPos;
                } else {
                    vehicle.phase = 'queued';
                    vehicle.isQueuing = true;
                    vehicle.speed = 0;
                    vehicle.acceleration = 0;
                }
            }

            // Durağı geçtiyse → zorla docking
            if (distToStop <= -5) {
                vehicle.phase = 'docking';
                vehicle.isQueuing = false;
                vehicle.slotMeterPosition = entryPos;
            }
            break;
        }

        // ============================================
        // QUEUED — Peron girişinde bekleme (semaphore)
        // ============================================
        case 'queued': {
            vehicle.queueWaitTime += dt;
            vehicle.speed = 0;
            vehicle.acceleration = 0;

            const platformVehicles = getVehiclesOnPlatform(vehicle.nextStopIndex, vehicleList);
            const entryPos = computeEntryPosition(nextStop, platformVehicles);

            if (fitsInPlatform(entryPos, vehicle.vehicleType.lengthMeters, nextStop)) {
                vehicle.phase = 'docking';
                vehicle.isQueuing = false;
                vehicle.slotMeterPosition = entryPos;
            }
            break;
        }

        // ============================================
        // DOCKING — Atanmış pozisyona yavaş ilerleme (2 m/s)
        //
        // Pozisyona ulaştığı anda → ANINDA stopped + dwell başlar
        // En öne gitmeyi beklemez!
        // ============================================
        case 'docking': {
            const distToSlot = vehicle.slotMeterPosition - vehicle.positionMeters;

            if (Math.abs(distToSlot) < 1.0 || distToSlot < 0) {
                // Pozisyona ulaştı → ANINDA yolcu operasyonu başla
                vehicle.phase = 'stopped';
                vehicle.speed = 0;
                vehicle.acceleration = 0;
                vehicle.positionMeters = vehicle.slotMeterPosition;

                // Dwell = 1s kapı açılma + Uniform(15, 30)
                const dwellTime = computeDwellTime(config);
                vehicle.dwellRemaining = 1.0 + dwellTime;
                vehicle.lastDwellTime = dwellTime;
                vehicle.totalStops++;
            } else {
                // Pozisyona doğru ilerle
                vehicle.speed = Math.min(2.0, vehicle.speed + config.maxAcceleration * dt);
                vehicle.positionMeters += vehicle.speed * dt;
            }
            break;
        }

        // ============================================
        // STOPPED — Kapılar açık, yolcu operasyonu
        //
        // PARALEL: Araç peron üzerinde NEREDE DURDUYSA ORADA KALIR.
        // İleri kayma YOK. Dwell süresi bağımsız sayar.
        // ============================================
        case 'stopped': {
            // Araç sabit — ileri kayma yok
            vehicle.positionMeters = vehicle.slotMeterPosition;
            vehicle.speed = 0;

            // Dwell countdown — araçta tutulan süre
            vehicle.dwellRemaining -= dt;

            if (vehicle.dwellRemaining <= 0) {
                vehicle.phase = 'doorsClosed';
                vehicle.dwellRemaining = 2.0; // Kapı kapanma 2s
            }
            break;
        }

        // ============================================
        // DOORS CLOSED — Kapılar kapanıyor (2s)
        // ============================================
        case 'doorsClosed': {
            vehicle.positionMeters = vehicle.slotMeterPosition;
            vehicle.speed = 0;

            vehicle.dwellRemaining -= dt;

            if (vehicle.dwellRemaining <= 0) {
                // Fiziksel gap kontrolü
                if (isBlockedByGap(vehicle, vehicle.nextStopIndex, vehicleList)) {
                    vehicle.phase = 'blocked';
                    vehicle.dwellRemaining = 0;
                } else {
                    // Önü açık → kalkış!
                    vehicle.phase = 'departing';
                    vehicle.dwellRemaining = 0;
                    vehicle.nextStopIndex++;
                }
            }
            break;
        }

        // ============================================
        // BLOCKED — Önde engel var
        //
        // Araç yerinde kalır (ileri kayma yok).
        // Öndeki >= SAFE_GAP uzaklaştığında → departing
        // ============================================
        case 'blocked': {
            vehicle.positionMeters = vehicle.slotMeterPosition;
            vehicle.speed = 0;

            if (!isBlockedByGap(vehicle, vehicle.nextStopIndex, vehicleList)) {
                vehicle.phase = 'departing';
                vehicle.dwellRemaining = 0;
                vehicle.nextStopIndex++;
            }
            break;
        }

        // ============================================
        // DEPARTING — Kalkış ivmelenmesi
        // ============================================
        case 'departing': {
            vehicle.acceleration = config.maxAcceleration;
            if (vehicle.speed > 3.0) {
                vehicle.phase = 'cruising';
            }
            break;
        }
    }
}

// ============================================
// Dwell Time Hesaplama
// ============================================

/**
 * Dwell süresi — Uniform(min, max) random.
 */
function computeDwellTime(config: SimConfig): number {
    const min = config.minDwellTime;
    const max = config.maxDwellTime;
    return min + Math.random() * (max - min);
}
