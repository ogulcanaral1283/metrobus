// =============================================
// Yaklaşım Hızı Optimizasyonu (Approach Speed Optimizer)
// Çift Durma Problemi Çözümü — Hız Hesaplayıcı
// =============================================

import {
    APPROACH_CONFIG,
    SPEED_CONFIG,
    type ApproachOptimization,
    type VehicleState,
    type StationSlot,
} from '@metrobus/shared';

/**
 * Yaklaşım Hızı Optimizasyonu
 * 
 * Durağa yaklaşan aracın, slot boşaldığı anda durağa varması için
 * gereken ideal hızı hesaplar.
 * 
 * Temel formül:
 *   idealHız (km/s) = mesafe (m) / tahminiBosalmaSüresi (sn) × 3.6
 * 
 * Örnek:
 *   - Durağa 500m mesafe
 *   - Slot tahmini 35sn sonra boşalacak
 *   - İdeal hız = 500 / 35 × 3.6 = ~51 km/s
 *   → Araç bu hızda giderse, slot tam boşaldığında durağa varır!
 */
export class ApproachSpeedOptimizer {
    /**
     * 🎯 ANA FONKSİYON: Yaklaşım hızı optimizasyonu yap
     * 
     * @param vehicle — Yaklaşan araç durumu
     * @param distanceToStationMeters — Durağa mesafe (m)
     * @param estimatedSlotClearanceSec — Tahmini slot boşalma süresi (sn)
     * @param slotStatus — Durak slot durumu
     * @param stationName — Durak adı (HUD mesajı için)
     */
    optimize(
        vehicle: VehicleState,
        distanceToStationMeters: number,
        estimatedSlotClearanceSec: number,
        slotStatus: StationSlot,
        stationName: string
    ): ApproachOptimization {
        const isInApproachZone = distanceToStationMeters <= APPROACH_CONFIG.APPROACH_ZONE_METERS;
        const slotOccupied = slotStatus.occupiedSlots >= slotStatus.totalSlots;

        // Optimizasyon aktif değilse (bölge dışı veya slot boş)
        if (!isInApproachZone || !slotOccupied) {
            return {
                vehicleId: vehicle.vehicleId,
                targetStationId: slotStatus.stationId,
                targetStationName: stationName,
                distanceToStationMeters,
                currentSpeedKmh: vehicle.speedKmh,
                slotOccupied: false,
                queueLength: slotStatus.queueLength,
                estimatedSlotClearanceSec: 0,
                optimalSpeedKmh: vehicle.speedKmh,
                waitTimeWithoutOptimizationSec: 0,
                timeSavedSec: 0,
                isActive: false,
            };
        }

        // Güvenlik tamponu ekle
        const totalClearanceTime = estimatedSlotClearanceSec + APPROACH_CONFIG.SLOT_CLEARANCE_BUFFER_SECONDS;

        // İdeal hız hesapla: mesafe / süre → m/s → km/s
        const optimalSpeedMps = distanceToStationMeters / totalClearanceTime;
        let optimalSpeedKmh = optimalSpeedMps * 3.6;

        // Hız sınırlarını uygula
        optimalSpeedKmh = Math.max(APPROACH_CONFIG.MIN_APPROACH_SPEED_KMH, optimalSpeedKmh);
        optimalSpeedKmh = Math.min(APPROACH_CONFIG.MAX_APPROACH_SPEED_KMH, optimalSpeedKmh);

        // Mevcut hızla devam etse ne olurdu?
        const arrivalTimeAtCurrentSpeed = this.calculateArrivalTime(
            distanceToStationMeters,
            vehicle.speedKmh
        );

        // Mevcut hızla slot boşalmadan önce varırsa → bekleme süresi
        const waitTimeWithoutOptimization = Math.max(
            0,
            totalClearanceTime - arrivalTimeAtCurrentSpeed
        );

        // Optimizasyonla tasarruf edilen süre
        // (çift durma + kalkma süresi dahil, tipik olarak 10-15sn ekstra)
        const doubleStopPenalty = waitTimeWithoutOptimization > 0 ? 10 : 0; // deceleration + acceleration
        const timeSaved = waitTimeWithoutOptimization + doubleStopPenalty;

        return {
            vehicleId: vehicle.vehicleId,
            targetStationId: slotStatus.stationId,
            targetStationName: stationName,
            distanceToStationMeters,
            currentSpeedKmh: vehicle.speedKmh,
            slotOccupied: true,
            queueLength: slotStatus.queueLength,
            estimatedSlotClearanceSec: totalClearanceTime,
            optimalSpeedKmh: Math.round(optimalSpeedKmh * 10) / 10,
            waitTimeWithoutOptimizationSec: Math.round(waitTimeWithoutOptimization),
            timeSavedSec: Math.round(timeSaved),
            isActive: true,
        };
    }

    /**
     * Mevcut hızla tahmini varış süresi hesapla
     * @returns saniye
     */
    private calculateArrivalTime(distanceMeters: number, speedKmh: number): number {
        if (speedKmh <= 0) return Infinity;
        const speedMps = speedKmh / 3.6;
        return distanceMeters / speedMps;
    }

    /**
     * Optimizasyonun anlamlı olup olmadığını kontrol et
     * - Optimal hız minimum hızdan düşükse → yapma
     * - Boşalma süresi çok uzunsa → yapma, dur
     */
    isOptimizationViable(optimization: ApproachOptimization): boolean {
        if (!optimization.isActive) return false;

        // Eğer hesaplanan hız minimum hızın altına düşüyorsa, anlamlı değil
        if (optimization.optimalSpeedKmh <= APPROACH_CONFIG.MIN_APPROACH_SPEED_KMH) {
            return false;
        }

        // Slot zaten çok yakında boşalacaksa (< 5sn) optimize etmeye gerek yok
        if (optimization.estimatedSlotClearanceSec < APPROACH_CONFIG.SLOT_CLEARANCE_BUFFER_SECONDS) {
            return false;
        }

        return true;
    }

    /**
     * Günlük tasarruf tahmini
     * @param avgOptimizationsPerDay — Günlük ortalama optimizasyon sayısı
     * @param avgTimeSavedPerOptimization — Optimizasyon başına ortalama tasarruf (sn)
     */
    static estimateDailySavings(
        avgOptimizationsPerDay: number = 200,
        avgTimeSavedPerOptimization: number = 20
    ): { totalSecondsSaved: number; totalMinutesSaved: number; percentageImprovement: number } {
        const totalSec = avgOptimizationsPerDay * avgTimeSavedPerOptimization;
        return {
            totalSecondsSaved: totalSec,
            totalMinutesSaved: Math.round(totalSec / 60),
            percentageImprovement: Math.round((totalSec / (16 * 3600)) * 100 * 10) / 10,
        };
    }
}
