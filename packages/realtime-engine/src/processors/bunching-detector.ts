// =============================================
// Bunching (Araç Yığılması) Tespit Modülü
// =============================================

import {
    HEADWAY_CONFIG,
    type VehicleState,
    type RouteDirection,
} from '@metrobus/shared';
import { type HeadwayResult } from './headway-calculator';

export interface BunchingAlert {
    type: 'bunching';
    severity: 'warning' | 'critical';
    vehicleIds: number[];
    direction: RouteDirection;
    location: {
        latitude: number;
        longitude: number;
    };
    distanceMeters: number;
    message: string;
    timestamp: Date;
}

/**
 * Araç yığılması (bus bunching) tespit edici
 *
 * Bunching, ardışık araçların birbirine çok yaklaşmasıdır.
 * Bu durum, bir durağa aynı anda birden fazla metrobüs gelmesine
 * ve hizmetin dengesizleşmesine neden olur.
 */
export class BunchingDetector {
    private readonly bunchingThreshold: number;
    private readonly criticalThreshold: number;

    constructor() {
        this.bunchingThreshold = HEADWAY_CONFIG.BUNCHING_THRESHOLD_METERS;
        this.criticalThreshold = this.bunchingThreshold * 0.5; // 100m
    }

    /**
     * Headway sonuçlarından bunching tespiti yap
     */
    detect(
        headways: HeadwayResult[],
        vehicles: Map<number, VehicleState>,
        direction: RouteDirection
    ): BunchingAlert[] {
        const alerts: BunchingAlert[] = [];

        for (const hw of headways) {
            if (!hw.isBunching) continue;

            const following = vehicles.get(hw.followingVehicleId);
            if (!following) continue;

            const severity =
                hw.headwayMeters < this.criticalThreshold ? 'critical' : 'warning';

            alerts.push({
                type: 'bunching',
                severity,
                vehicleIds: [hw.leadingVehicleId, hw.followingVehicleId],
                direction,
                location: {
                    latitude: following.position.latitude,
                    longitude: following.position.longitude,
                },
                distanceMeters: hw.headwayMeters,
                message:
                    severity === 'critical'
                        ? `KRİTİK: ${hw.followingVehicleId} ve ${hw.leadingVehicleId} araçları sadece ${hw.headwayMeters}m mesafede!`
                        : `UYARI: ${hw.followingVehicleId} ve ${hw.leadingVehicleId} araçları ${hw.headwayMeters}m mesafede yakınlaşıyor`,
                timestamp: new Date(),
            });
        }

        return alerts;
    }

    /**
     * Ardışık bunching gruplarını tespit et
     * (3 veya daha fazla aracın peşpeşe yığılması)
     */
    detectClusters(
        headways: HeadwayResult[]
    ): Array<{ vehicleIds: number[]; avgDistance: number }> {
        const clusters: Array<{ vehicleIds: number[]; avgDistance: number }> = [];

        let currentCluster: number[] = [];
        let distances: number[] = [];

        for (const hw of headways) {
            if (hw.isBunching) {
                if (currentCluster.length === 0) {
                    currentCluster.push(hw.leadingVehicleId);
                }
                currentCluster.push(hw.followingVehicleId);
                distances.push(hw.headwayMeters);
            } else {
                if (currentCluster.length >= 3) {
                    clusters.push({
                        vehicleIds: [...currentCluster],
                        avgDistance:
                            distances.reduce((a, b) => a + b, 0) / distances.length,
                    });
                }
                currentCluster = [];
                distances = [];
            }
        }

        // Son cluster kontrolü
        if (currentCluster.length >= 3) {
            clusters.push({
                vehicleIds: [...currentCluster],
                avgDistance:
                    distances.reduce((a, b) => a + b, 0) / distances.length,
            });
        }

        return clusters;
    }
}
