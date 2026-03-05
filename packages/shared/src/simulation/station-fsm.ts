// =============================================
// Durak State Machine (FSM)
// Yaklaşım → Durma → Yolcu Alımı → Kalkış
// =============================================

import type { SimVehicle, SimConfig, LinearStop } from './sim-types';

/**
 * Durak state machine güncelleme.
 * Her tick'te araç fazını ve durak etkileşimini yönetir.
 * 
 * State geçişleri:
 *   cruising   → approaching  (durağa approachDistance metre kala)
 *   approaching → stopped      (hız ~0 ve durağa ≤3m)
 *   stopped    → departing     (dwell süresi doldu)
 *   departing  → cruising      (hız > 3 m/s)
 */
export function updateStationFSM(
    vehicle: SimVehicle,
    dt: number,
    stops: LinearStop[],
    config: SimConfig,
    isRushHour: boolean,
): void {
    if (vehicle.nextStopIndex >= stops.length) return;

    const nextStop = stops[vehicle.nextStopIndex];
    const distToStop = nextStop.meterPosition - vehicle.positionMeters;

    switch (vehicle.phase) {
        case 'cruising': {
            // Durağa yaklaşma bölgesine girildiyse
            if (distToStop > 0 && distToStop < config.approachDistance) {
                vehicle.phase = 'approaching';
            }
            // Durağı geçtiyse (atlandı)
            if (distToStop <= 0) {
                vehicle.nextStopIndex++;
            }
            break;
        }

        case 'approaching': {
            // Hız yeterince düştü ve durağa yakın
            if (vehicle.speed < 0.5 && distToStop < 5) {
                vehicle.phase = 'stopped';
                vehicle.speed = 0;
                vehicle.acceleration = 0;

                // Dwell süresi hesapla
                const passengerCount = computePassengerLoad(nextStop, isRushHour);
                vehicle.dwellRemaining = computeDwellTime(passengerCount, config);
                vehicle.totalStops++;
            }
            // Durağı geçtiyse (hızlı geçiş durumu)
            if (distToStop <= -5) {
                vehicle.phase = 'cruising';
                vehicle.nextStopIndex++;
            }
            break;
        }

        case 'stopped': {
            // Dwell süresini düşür
            vehicle.dwellRemaining -= dt;

            if (vehicle.dwellRemaining <= 0) {
                vehicle.phase = 'departing';
                vehicle.dwellRemaining = 0;
                vehicle.nextStopIndex++;
            }
            break;
        }

        case 'departing': {
            // Yeterince hızlandığında cruising'e geç
            if (vehicle.speed > 3.0) {
                vehicle.phase = 'cruising';
            }
            break;
        }
    }
}

/**
 * Duraktaki yolcu sayısını hesapla.
 * Rush hour'da 2-3× fazla yolcu.
 */
function computePassengerLoad(stop: LinearStop, isRushHour: boolean): number {
    // Bazal yolcu: 5-20 arası rastgele
    const base = 5 + Math.floor(Math.random() * 15);
    const rushMultiplier = isRushHour ? 2.5 : 1.0;

    // Merkezi duraklar daha kalabalık (pozisyona göre)
    // Hat ortasındaki duraklar daha yoğun
    const centerBonus = stop.index > 10 && stop.index < 30 ? 1.3 : 1.0;

    return Math.round(base * rushMultiplier * centerBonus);
}

/**
 * Dwell süresi hesapla.
 * doorTime + yolcu × perPassengerTime, min/max ile sınırlı.
 */
function computeDwellTime(passengerCount: number, config: SimConfig): number {
    const raw = config.doorTime + passengerCount * config.perPassengerTime;
    return Math.max(config.minDwellTime, Math.min(config.maxDwellTime, raw));
}
