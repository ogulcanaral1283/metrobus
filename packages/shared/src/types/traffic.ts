// =============================================
// Trafik Veri Modelleri
// =============================================

/** Trafik seviyesi */
export type TrafficLevel = 'free' | 'light' | 'moderate' | 'heavy' | 'standstill';

/** Segment trafik verisi (iki durak arası) */
export interface TrafficSegment {
    time: Date;
    segmentStartStationId: number;
    segmentEndStationId: number;
    trafficSpeedKmh: number;
    trafficLevel: TrafficLevel;
    travelTimeSec: number;
}

/** Hat geneli trafik özeti */
export interface RouteTrafficSummary {
    direction: 'east' | 'west';
    avgSpeedKmh: number;
    totalTravelTimeSec: number;
    worstSegment: {
        startStation: string;
        endStation: string;
        trafficLevel: TrafficLevel;
        travelTimeSec: number;
    } | null;
    timestamp: Date;
}

/** Headway (araç arası mesafe) verisi */
export interface HeadwayRecord {
    time: Date;
    leadingVehicleId: number;
    followingVehicleId: number;
    headwaySeconds: number;
    headwayMeters: number;
    stationId: number | null;
    direction: 'east' | 'west';
}

/** Headway durumu */
export type HeadwayStatus = 'too_close' | 'close' | 'normal' | 'far' | 'too_far';

/** Headway'den durum hesaplama */
export function getHeadwayStatus(headwaySeconds: number): HeadwayStatus {
    if (headwaySeconds < 60) return 'too_close';
    if (headwaySeconds < 120) return 'close';
    if (headwaySeconds < 240) return 'normal';
    if (headwaySeconds < 360) return 'far';
    return 'too_far';
}
