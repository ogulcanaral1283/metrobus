// =============================================
// Kural Motoru Çekirdeği
// =============================================

import type {
    VehicleState,
    DriverCommand,
    CommandType,
    CommandSeverity,
} from '@metrobus/shared';
import { DECISION_CONFIG } from '@metrobus/shared';
import { v4 as uuidv4 } from 'uuid';
import type { HeadwayResult } from './speed-rules';

export interface RuleContext {
    vehicle: VehicleState;
    headway: HeadwayResult | null;
    nextStationCongestionScore: number;
    delayMinutes: number;
    isRushHour: boolean;
    /** Çift Durma Önleme: Sonraki durak slot bilgisi */
    nextStationSlotInfo: {
        targetStationId: number;
        targetStationName: string;
        distanceToStationMeters: number;
        slotOccupied: boolean;
        queueLength: number;
        estimatedSlotClearanceSec: number;
        optimalSpeedKmh: number;
        timeSavedSec: number;
        isActive: boolean;
    } | null;
}

export interface RuleResult {
    commandType: CommandType;
    severity: CommandSeverity;
    messageTr: string;
    reason: string;
    targetSpeedKmh: number | null;
    targetStationId: number | null;
    priority: number; // Yüksek = daha öncelikli
}

export type Rule = (context: RuleContext) => RuleResult | null;

/**
 * Kural Motoru
 * 
 * Kayıtlı kuralları öncelik sırasına göre çalıştırır.
 * İlk eşleşen kural komutu üretir.
 */
export class RuleEngine {
    private rules: Array<{ name: string; rule: Rule; priority: number }> = [];

    /** Kural ekle */
    addRule(name: string, rule: Rule, priority: number = 0): void {
        this.rules.push({ name, rule, priority });
        // Yüksek öncelikli kurallar önce çalışır
        this.rules.sort((a, b) => b.priority - a.priority);
    }

    /** Kuralları değerlendir ve komut üret */
    evaluate(context: RuleContext): DriverCommand | null {
        for (const { name, rule } of this.rules) {
            const result = rule(context);
            if (result) {
                console.log(`[RuleEngine] Kural eşleşti: ${name} → ${result.commandType}`);
                return this.createCommand(context.vehicle.vehicleId, result);
            }
        }

        // Hiçbir kural eşleşmezse NORMAL komutu
        return this.createCommand(context.vehicle.vehicleId, {
            commandType: 'NORMAL',
            severity: 'low',
            messageTr: 'Normal seyir. Akış düzgün.',
            reason: 'Tüm metrikler normal aralıkta',
            targetSpeedKmh: null,
            targetStationId: null,
            priority: 0,
        });
    }

    /** DriverCommand nesnesi oluştur */
    private createCommand(
        vehicleId: number,
        result: RuleResult
    ): DriverCommand {
        const now = new Date();
        const expiresAt = new Date(
            now.getTime() + DECISION_CONFIG.COMMAND_TTL_SECONDS * 1000
        );

        return {
            id: uuidv4(),
            time: now,
            vehicleId,
            commandType: result.commandType,
            severity: result.severity,
            messageTr: result.messageTr,
            reason: result.reason,
            targetSpeedKmh: result.targetSpeedKmh,
            targetStationId: result.targetStationId,
            acknowledged: false,
            acknowledgedAt: null,
            expiresAt,
        };
    }
}
