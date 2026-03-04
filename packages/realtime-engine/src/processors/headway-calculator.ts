// =============================================
// Headway (Araç Arası Mesafe) Hesaplayıcı
// =============================================

import {
    haversineDistance,
    estimateTravelTime,
    HEADWAY_CONFIG,
    type VehicleState,
    type HeadwayRecord,
    type RouteDirection,
} from '@metrobus/shared';

export interface HeadwayResult {
    leadingVehicleId: number;
    followingVehicleId: number;
    headwayMeters: number;
    headwaySeconds: number;
    isBunching: boolean;
    isGapping: boolean;
}

/**
 * Headway hesaplayıcı
 * 
 * Aynı yöndeki ardışık iki metrobüs arasındaki
 * mesafe ve zaman farkını hesaplar.
 */
export class HeadwayCalculator {
    /**
     * Belirli bir yöndeki tüm araçlar için headway hesapla
     * @param vehicles Yöne göre sıralanmış araç listesi
     * @param direction Yön
     */
    calculateAll(
        vehicles: VehicleState[],
        direction: RouteDirection
    ): HeadwayResult[] {
        // Sadece aktif araçları al ve hat üzerindeki sıraya göre sırala
        const sorted = vehicles
            .filter((v) => v.direction === direction && v.nearestStation)
            .sort((a, b) => {
                const aOrder = a.nearestStation!.id;
                const bOrder = b.nearestStation!.id;
                return direction === 'east' ? aOrder - bOrder : bOrder - aOrder;
            });

        const results: HeadwayResult[] = [];

        for (let i = 0; i < sorted.length - 1; i++) {
            const leading = sorted[i];
            const following = sorted[i + 1];

            const result = this.calculatePair(leading, following);
            results.push(result);
        }

        return results;
    }

    /**
     * İki araç arası headway hesapla
     */
    calculatePair(
        leading: VehicleState,
        following: VehicleState
    ): HeadwayResult {
        const distanceMeters = haversineDistance(
            leading.position.latitude,
            leading.position.longitude,
            following.position.latitude,
            following.position.longitude
        );

        // Ortalama hız ile tahmini süre
        const avgSpeed = (leading.speedKmh + following.speedKmh) / 2 || 30;
        const headwaySeconds = estimateTravelTime(distanceMeters, avgSpeed);

        return {
            leadingVehicleId: leading.vehicleId,
            followingVehicleId: following.vehicleId,
            headwayMeters: Math.round(distanceMeters),
            headwaySeconds: Math.round(headwaySeconds),
            isBunching: distanceMeters < HEADWAY_CONFIG.BUNCHING_THRESHOLD_METERS,
            isGapping: headwaySeconds > HEADWAY_CONFIG.GAPPING_THRESHOLD_SECONDS,
        };
    }

    /** Headway sonucunu veritabanı kaydı formatına dönüştür */
    toRecord(
        result: HeadwayResult,
        direction: RouteDirection,
        stationId: number | null
    ): HeadwayRecord {
        return {
            time: new Date(),
            leadingVehicleId: result.leadingVehicleId,
            followingVehicleId: result.followingVehicleId,
            headwaySeconds: result.headwaySeconds,
            headwayMeters: result.headwayMeters,
            stationId,
            direction,
        };
    }
}
