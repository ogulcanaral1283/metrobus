// =============================================
// Hız Ayarlama Kuralları
// =============================================

import { HEADWAY_CONFIG, SPEED_CONFIG } from '@metrobus/shared';
import type { Rule, RuleContext, RuleResult } from './rule-engine';

export interface HeadwayResult {
    headwayMeters: number;
    headwaySeconds: number;
    isBunching: boolean;
    isGapping: boolean;
}

/**
 * Kural: Kritik yakınlık — Acil yavaşla
 * Öndeki araçla mesafe çok az (< 100m)
 */
export const criticalProximityRule: Rule = (ctx: RuleContext): RuleResult | null => {
    if (!ctx.headway) return null;

    const criticalDistance = HEADWAY_CONFIG.BUNCHING_THRESHOLD_METERS * 0.5;
    if (ctx.headway.headwayMeters < criticalDistance) {
        const targetSpeed = Math.max(
            SPEED_CONFIG.MIN_SPEED_KMH,
            ctx.vehicle.speedKmh * (1 - SPEED_CONFIG.SLOW_DOWN_FACTOR * 1.5)
        );

        return {
            commandType: 'SLOW_DOWN',
            severity: 'critical',
            messageTr: `⚠️ KRİTİK: Öndeki araç sadece ${ctx.headway.headwayMeters}m mesafede! Hızınızı ${Math.round(targetSpeed)} km/s'e düşürün.`,
            reason: `Öndeki araçla kritik yakınlık: ${ctx.headway.headwayMeters}m`,
            targetSpeedKmh: targetSpeed,
            targetStationId: null,
            priority: 100,
        };
    }

    return null;
};

/**
 * Kural: Yığılma — Yavaşla
 * Öndeki araçla mesafe düşük (< 200m)
 */
export const bunchingSlowDownRule: Rule = (ctx: RuleContext): RuleResult | null => {
    if (!ctx.headway || !ctx.headway.isBunching) return null;

    const targetSpeed = Math.max(
        SPEED_CONFIG.MIN_SPEED_KMH,
        ctx.vehicle.speedKmh * (1 - SPEED_CONFIG.SLOW_DOWN_FACTOR)
    );

    return {
        commandType: 'SLOW_DOWN',
        severity: 'high',
        messageTr: `🐢 Öndeki araçla mesafe ${ctx.headway.headwayMeters}m. Hızınızı ${Math.round(targetSpeed)} km/s'e düşürün.`,
        reason: `Araç yığılması tespiti: ${ctx.headway.headwayMeters}m`,
        targetSpeedKmh: targetSpeed,
        targetStationId: null,
        priority: 80,
    };
};

/**
 * Kural: Arkada boşluk — Hızlan
 * Arkadaki araçtan çok uzakta (> 360sn)
 */
export const gappingSpeedUpRule: Rule = (ctx: RuleContext): RuleResult | null => {
    if (!ctx.headway || !ctx.headway.isGapping) return null;

    // Sadece arkada boşluk varsa (following araç çok geride)
    const targetSpeed = Math.min(
        SPEED_CONFIG.MAX_SPEED_KMH,
        ctx.vehicle.speedKmh * (1 + SPEED_CONFIG.SPEED_UP_FACTOR)
    );

    return {
        commandType: 'SPEED_UP',
        severity: 'medium',
        messageTr: `⏩ Arkadaki araçla aranız ${Math.round(ctx.headway.headwaySeconds / 60)}dk. Hızınızı ${Math.round(targetSpeed)} km/s'e artırın.`,
        reason: `Araçlar arası boşluk: ${ctx.headway.headwaySeconds}sn`,
        targetSpeedKmh: targetSpeed,
        targetStationId: null,
        priority: 50,
    };
};

/**
 * Kural: Sefer planından gecikme — Hızlan
 */
export const delaySpeedUpRule: Rule = (ctx: RuleContext): RuleResult | null => {
    if (ctx.delayMinutes < 5) return null;

    const targetSpeed = Math.min(
        SPEED_CONFIG.MAX_SPEED_KMH,
        ctx.vehicle.speedKmh * (1 + SPEED_CONFIG.SPEED_UP_FACTOR)
    );

    return {
        commandType: 'SPEED_UP',
        severity: ctx.delayMinutes > 10 ? 'high' : 'medium',
        messageTr: `⏩ Sefer planından ${ctx.delayMinutes}dk gecikmedesiniz. Hızınızı artırın.`,
        reason: `Sefer gecikmesi: ${ctx.delayMinutes}dk`,
        targetSpeedKmh: targetSpeed,
        targetStationId: null,
        priority: 40,
    };
};
