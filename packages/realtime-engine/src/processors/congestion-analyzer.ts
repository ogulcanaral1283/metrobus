// =============================================
// Tıkanıklık (Congestion) Analiz Modülü
// =============================================

import {
    CONGESTION_CONFIG,
    getCongestionLevel,
    type StationCongestion,
    type CongestionLevel,
    type RouteDirection,
} from '@metrobus/shared';

export interface CongestionAnalysis {
    stationId: number;
    stationName: string;
    direction: RouteDirection;
    congestionScore: number;
    level: CongestionLevel;
    vehicleCount: number;
    trend: 'increasing' | 'stable' | 'decreasing';
    recommendation: string;
}

/**
 * Durak ve segment bazlı tıkanıklık analizi
 */
export class CongestionAnalyzer {
    private history: Map<number, StationCongestion[]> = new Map();
    private readonly maxHistory = 10; // Son 10 ölçüm

    /**
     * Yeni yoğunluk verisi ekle ve analiz yap
     */
    analyze(congestion: StationCongestion, stationName: string, direction: RouteDirection): CongestionAnalysis {
        // Geçmişe ekle
        const stationHistory = this.history.get(congestion.stationId) || [];
        stationHistory.push(congestion);
        if (stationHistory.length > this.maxHistory) {
            stationHistory.shift();
        }
        this.history.set(congestion.stationId, stationHistory);

        // Trend hesapla
        const trend = this.calculateTrend(stationHistory);
        const level = getCongestionLevel(congestion.congestionScore);

        // Öneri oluştur
        const recommendation = this.generateRecommendation(
            congestion.congestionScore,
            level,
            trend,
            congestion.vehicleCount
        );

        return {
            stationId: congestion.stationId,
            stationName,
            direction,
            congestionScore: congestion.congestionScore,
            level,
            vehicleCount: congestion.vehicleCount,
            trend,
            recommendation,
        };
    }

    /**
     * Yoğunluk trendi hesapla
     */
    private calculateTrend(
        history: StationCongestion[]
    ): 'increasing' | 'stable' | 'decreasing' {
        if (history.length < 3) return 'stable';

        const recent = history.slice(-3);
        const scores = recent.map((h) => h.congestionScore);

        const diff = scores[2] - scores[0];
        if (diff > 10) return 'increasing';
        if (diff < -10) return 'decreasing';
        return 'stable';
    }

    /**
     * Duruma göre öneri oluştur
     */
    private generateRecommendation(
        score: number,
        level: CongestionLevel,
        trend: string,
        vehicleCount: number
    ): string {
        if (level === 'critical') {
            return `Durakta kritik yoğunluk (${score}/100). ` +
                `${vehicleCount} araç bekliyor. Yaklaşan araçlar yavaşlamalı.`;
        }
        if (level === 'high' && trend === 'increasing') {
            return `Yoğunluk artıyor (${score}/100). Araçların sıklığı artırılmalı.`;
        }
        if (level === 'high') {
            return `Durakta yüksek yoğunluk (${score}/100). Dikkatli yaklaşın.`;
        }
        if (level === 'moderate') {
            return `Normal yoğunluk (${score}/100). Standart seyir.`;
        }
        return `Düşük yoğunluk (${score}/100).`;
    }

    /** Belirli bir durak için güncel analiz al */
    getLatestAnalysis(stationId: number): StationCongestion | null {
        const history = this.history.get(stationId);
        if (!history || history.length === 0) return null;
        return history[history.length - 1];
    }

    /** Tüm kritik durakları listele */
    getCriticalStations(): number[] {
        const critical: number[] = [];
        for (const [stationId, history] of this.history) {
            const latest = history[history.length - 1];
            if (latest && latest.congestionScore >= CONGESTION_CONFIG.CRITICAL_THRESHOLD) {
                critical.push(stationId);
            }
        }
        return critical;
    }
}
