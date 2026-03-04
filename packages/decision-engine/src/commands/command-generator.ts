// =============================================
// Komut Üretici — Karar Motoru → Şoför Komutu
// =============================================

import { RuleEngine, type RuleContext } from '../rules/rule-engine';
import {
    criticalProximityRule,
    bunchingSlowDownRule,
    gappingSpeedUpRule,
    delaySpeedUpRule,
} from '../rules/speed-rules';
import {
    skipStopRule,
    cautionStopRule,
    holdAtStopRule,
    rushHourCautionRule,
} from '../rules/stop-rules';
import {
    approachSpeedOptimizeRule,
    approachQueueWarningRule,
} from '../rules/approach-rules';
import {
    isRushHour,
    type VehicleState,
    type DriverCommand,
} from '@metrobus/shared';

/**
 * Komut Üretici
 * 
 * Tüm kuralları bir araya getirerek her araç için
 * uygun şoför komutunu üretir.
 */
export class CommandGenerator {
    private engine: RuleEngine;
    private activeCommands: Map<number, DriverCommand> = new Map();

    constructor() {
        this.engine = new RuleEngine();
        this.registerDefaultRules();
    }

    /** Varsayılan kuralları kaydet */
    private registerDefaultRules(): void {
        // Hız kuralları (yüksek öncelikli)
        this.engine.addRule('critical-proximity', criticalProximityRule, 100);

        // 🎯 Çift durma önleme kuralları
        this.engine.addRule('approach-speed-optimize', approachSpeedOptimizeRule, 90);
        this.engine.addRule('approach-queue-warning', approachQueueWarningRule, 85);

        this.engine.addRule('bunching-slowdown', bunchingSlowDownRule, 80);

        // Durak kuralları
        this.engine.addRule('skip-stop', skipStopRule, 70);
        this.engine.addRule('hold-at-stop', holdAtStopRule, 60);

        // Orta öncelikli kurallar
        this.engine.addRule('gapping-speedup', gappingSpeedUpRule, 50);
        this.engine.addRule('caution-stop', cautionStopRule, 45);
        this.engine.addRule('delay-speedup', delaySpeedUpRule, 40);

        // Düşük öncelikli kurallar
        this.engine.addRule('rush-hour-caution', rushHourCautionRule, 30);

        console.log('[CommandGenerator] 10 kural kaydedildi (çift durma önleme dahil)');
    }

    /**
     * Araç için komut üret
     */
    generateCommand(
        vehicle: VehicleState,
        headway: {
            headwayMeters: number;
            headwaySeconds: number;
            isBunching: boolean;
            isGapping: boolean;
        } | null,
        nextStationCongestionScore: number,
        delayMinutes: number = 0,
        /** Çift durma önleme: Slot optimizasyon bilgisi */
        slotInfo: {
            targetStationId: number;
            targetStationName: string;
            distanceToStationMeters: number;
            slotOccupied: boolean;
            queueLength: number;
            estimatedSlotClearanceSec: number;
            optimalSpeedKmh: number;
            timeSavedSec: number;
            isActive: boolean;
        } | null = null
    ): DriverCommand | null {
        const context: RuleContext = {
            vehicle,
            headway,
            nextStationCongestionScore,
            delayMinutes,
            isRushHour: isRushHour(),
            nextStationSlotInfo: slotInfo,
        };

        const command = this.engine.evaluate(context);

        if (command) {
            // Aynı tip komut zaten aktifse ve süresi dolmamışsa tekrar gönderme
            const existing = this.activeCommands.get(vehicle.vehicleId);
            if (
                existing &&
                existing.commandType === command.commandType &&
                existing.expiresAt > new Date()
            ) {
                return null; // Tekrar göndermeye gerek yok
            }

            this.activeCommands.set(vehicle.vehicleId, command);
        }

        return command;
    }

    /** Aktif komutu onayla */
    acknowledgeCommand(vehicleId: number): void {
        const command = this.activeCommands.get(vehicleId);
        if (command) {
            command.acknowledged = true;
            command.acknowledgedAt = new Date();
        }
    }

    /** Araç için aktif komutu getir */
    getActiveCommand(vehicleId: number): DriverCommand | null {
        const command = this.activeCommands.get(vehicleId);
        if (!command) return null;
        if (command.expiresAt < new Date()) {
            this.activeCommands.delete(vehicleId);
            return null;
        }
        return command;
    }

    /** Tüm aktif komutları getir */
    getAllActiveCommands(): DriverCommand[] {
        const now = new Date();
        const active: DriverCommand[] = [];

        for (const [vehicleId, command] of this.activeCommands) {
            if (command.expiresAt < now) {
                this.activeCommands.delete(vehicleId);
            } else {
                active.push(command);
            }
        }

        return active;
    }
}
