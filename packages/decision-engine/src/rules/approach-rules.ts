// =============================================
// Yaklaşım Kuralları (Çift Durma Önleme)
// =============================================

import { APPROACH_CONFIG, SPEED_CONFIG } from '@metrobus/shared';
import type { Rule, RuleContext, RuleResult } from './rule-engine';

/**
 * 🎯 ANA KURAL: Durak Yaklaşım Hız Optimizasyonu
 * Öncelik: 90 (Kritik yakınlıktan sonra en yüksek)
 * 
 * Tetiklenme koşulu:
 *   - Araç durağa ≤ 500m mesafede
 *   - Sonraki duraktaki slot dolu
 *   - Optimizasyon aktif ve geçerli
 * 
 * Ne yapar:
 *   Slotun ne zaman boşalacağını tahmin eder ve aracın
 *   tam o anda varması için hızını ayarlar.
 *   
 * Sonuç:
 *   Araç durmadan doğrudan slota girer → çift durma önlenir → 
 *   sefer başına 15-25sn tasarruf
 */
export const approachSpeedOptimizeRule: Rule = (ctx: RuleContext): RuleResult | null => {
    const slotInfo = ctx.nextStationSlotInfo;
    if (!slotInfo || !slotInfo.isActive) return null;

    // Optimizasyon geçerli mi kontrol et
    if (slotInfo.optimalSpeedKmh <= APPROACH_CONFIG.MIN_APPROACH_SPEED_KMH) {
        return null;
    }

    // Slot boşalma süresi çok kısaysa (< buffer), optimize etmeye gerek yok
    if (slotInfo.estimatedSlotClearanceSec < APPROACH_CONFIG.SLOT_CLEARANCE_BUFFER_SECONDS) {
        return null;
    }

    // Hedef hız mevcut hızdan çok farklı değilse optimize etmeye gerek yok (±5 km/s)
    const speedDiff = Math.abs(ctx.vehicle.speedKmh - slotInfo.optimalSpeedKmh);
    if (speedDiff < 5) {
        return null;
    }

    // Yavaşlaması mı hızlanması mı gerekiyor?
    const needsSlowDown = slotInfo.optimalSpeedKmh < ctx.vehicle.speedKmh;

    if (needsSlowDown) {
        return {
            commandType: 'SLOW_DOWN',
            severity: 'medium',
            messageTr:
                `🎯 ${slotInfo.targetStationName} durağında slot dolu. ` +
                `Hızınızı ${Math.round(slotInfo.optimalSpeedKmh)} km/s'e düşürün — ` +
                `slot ~${slotInfo.estimatedSlotClearanceSec}sn sonra boşalacak. ` +
                `(${slotInfo.distanceToStationMeters}m kaldı, ` +
                `${slotInfo.timeSavedSec}sn tasarruf)`,
            reason:
                `Çift durma önleme: Slot ${slotInfo.estimatedSlotClearanceSec}sn sonra boşalacak, ` +
                `${slotInfo.distanceToStationMeters}m mesafe → ideal hız ${slotInfo.optimalSpeedKmh} km/s`,
            targetSpeedKmh: slotInfo.optimalSpeedKmh,
            targetStationId: slotInfo.targetStationId,
            priority: 90,
        };
    } else {
        // Daha hızlı gitmesi gerekiyor (slot çok uzun sürecek durumlar nadir)
        const cappedSpeed = Math.min(
            SPEED_CONFIG.MAX_SPEED_KMH,
            slotInfo.optimalSpeedKmh
        );

        return {
            commandType: 'SPEED_UP',
            severity: 'low',
            messageTr:
                `⏩ ${slotInfo.targetStationName} durağına hızınızı ` +
                `${Math.round(cappedSpeed)} km/s'e artırın — slot açılmak üzere.`,
            reason:
                `Çift durma önleme: Slot hemen boşalacak, hızlanarak zamanında varılabilir`,
            targetSpeedKmh: cappedSpeed,
            targetStationId: slotInfo.targetStationId,
            priority: 90,
        };
    }
};

/**
 * Kural: Durakta kuyruk uyarısı
 * Öncelik: 85
 * 
 * Durağa yaklaşırken birden fazla araç kuyruktaysa ekstra dikkat
 */
export const approachQueueWarningRule: Rule = (ctx: RuleContext): RuleResult | null => {
    const slotInfo = ctx.nextStationSlotInfo;
    if (!slotInfo || !slotInfo.isActive) return null;

    // Sadece kuyruk 2+ araç varsa
    if (slotInfo.queueLength < 2) return null;

    const targetSpeed = Math.max(
        APPROACH_CONFIG.MIN_APPROACH_SPEED_KMH,
        ctx.vehicle.speedKmh * 0.5
    );

    return {
        commandType: 'SLOW_DOWN',
        severity: 'high',
        messageTr:
            `⚠️ ${slotInfo.targetStationName} durağında ${slotInfo.queueLength} araç kuyrukta! ` +
            `Ciddi bekleme bekleniyor. Hızınızı ${Math.round(targetSpeed)} km/s'e düşürün.`,
        reason:
            `Durakta uzun kuyruk: ${slotInfo.queueLength} araç bekliyor`,
        targetSpeedKmh: targetSpeed,
        targetStationId: slotInfo.targetStationId,
        priority: 85,
    };
};
