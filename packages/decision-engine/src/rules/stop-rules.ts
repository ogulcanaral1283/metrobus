// =============================================
// Durak Kuralları
// =============================================

import { CONGESTION_CONFIG, DECISION_CONFIG } from '@metrobus/shared';
import type { Rule, RuleContext, RuleResult } from './rule-engine';

/**
 * Kural: Sonraki durakta kritik yoğunluk — Durakta durma, devam et
 * Durağa fazla araç yığılmışsa ve gecikme varsa
 */
export const skipStopRule: Rule = (ctx: RuleContext): RuleResult | null => {
    if (
        ctx.nextStationCongestionScore >= CONGESTION_CONFIG.CRITICAL_THRESHOLD &&
        ctx.delayMinutes >= DECISION_CONFIG.SKIP_STOP_DELAY_MINUTES
    ) {
        return {
            commandType: 'SKIP_STOP',
            severity: 'high',
            messageTr: `🚀 Sonraki durakta aşırı yoğunluk (${ctx.nextStationCongestionScore}/100) ve ${ctx.delayMinutes}dk gecikme var. Durakta durmadan devam edin.`,
            reason: `Durak yoğunluğu: ${ctx.nextStationCongestionScore} + gecikme: ${ctx.delayMinutes}dk`,
            targetSpeedKmh: null,
            targetStationId: ctx.vehicle.nextStation?.id || null,
            priority: 70,
        };
    }

    return null;
};

/**
 * Kural: Sonraki durakta yüksek yoğunluk — Dikkat
 */
export const cautionStopRule: Rule = (ctx: RuleContext): RuleResult | null => {
    if (ctx.nextStationCongestionScore >= CONGESTION_CONFIG.WARNING_THRESHOLD) {
        return {
            commandType: 'CAUTION',
            severity: 'medium',
            messageTr: `⚠️ Sonraki durakta yoğunluk yüksek (${ctx.nextStationCongestionScore}/100). Dikkatli yaklaşın.`,
            reason: `Durak yoğunluğu: ${ctx.nextStationCongestionScore}`,
            targetSpeedKmh: null,
            targetStationId: ctx.vehicle.nextStation?.id || null,
            priority: 45,
        };
    }

    return null;
};

/**
 * Kural: Durakta bekleme — Yığılma önleme
 * Araçlar arası mesafe az ve önde araç durağa yaklaşıyorsa
 */
export const holdAtStopRule: Rule = (ctx: RuleContext): RuleResult | null => {
    if (
        ctx.headway &&
        ctx.headway.headwayMeters < 300 &&
        ctx.vehicle.nearestStation &&
        ctx.vehicle.nearestStation.distanceMeters < 50
    ) {
        return {
            commandType: 'HOLD',
            severity: 'medium',
            messageTr: `⏸️ Durakta ${Math.round(ctx.headway.headwaySeconds / 3)}sn bekleyin. Öndeki araçla mesafeniz kısa.`,
            reason: `Durakta bekleme: Öndeki araçla ${ctx.headway.headwayMeters}m mesafe`,
            targetSpeedKmh: 0,
            targetStationId: ctx.vehicle.nearestStation.id,
            priority: 60,
        };
    }

    return null;
};

/**
 * Rush hour ek kuralı — Yoğun saatlerde eşikler düşer
 */
export const rushHourCautionRule: Rule = (ctx: RuleContext): RuleResult | null => {
    if (!ctx.isRushHour) return null;

    // Rush hour'da yoğunluk eşiğini düşür
    const adjustedThreshold = CONGESTION_CONFIG.WARNING_THRESHOLD * 0.8;

    if (
        ctx.nextStationCongestionScore >= adjustedThreshold &&
        ctx.nextStationCongestionScore < CONGESTION_CONFIG.WARNING_THRESHOLD
    ) {
        return {
            commandType: 'CAUTION',
            severity: 'low',
            messageTr: `⚠️ Yoğun saat! Sonraki durak yoğunluğu artabilir (${ctx.nextStationCongestionScore}/100).`,
            reason: `Rush hour dikkat: Yoğunluk ${ctx.nextStationCongestionScore}`,
            targetSpeedKmh: null,
            targetStationId: null,
            priority: 30,
        };
    }

    return null;
};
