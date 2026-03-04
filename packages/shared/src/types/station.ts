// =============================================
// Durak Veri Modelleri
// =============================================

import type { RouteDirection } from './vehicle';

/** Durak tanımı */
export interface Station {
    id: number;
    code: string;
    name: string;
    latitude: number;
    longitude: number;
    direction: RouteDirection;
    sequenceOrder: number;
    isActive: boolean;
}

/** Durak yoğunluk verisi */
export interface StationCongestion {
    time: Date;
    stationId: number;
    congestionScore: number;    // 0-100 arası
    passengerCount: number | null;
    vehicleCount: number;
    avgWaitTimeSec: number | null;
}

/** Durak yoğunluk seviyesi */
export type CongestionLevel = 'low' | 'moderate' | 'high' | 'critical';

/** Yoğunluk skorundan seviye hesaplama */
export function getCongestionLevel(score: number): CongestionLevel {
    if (score < 30) return 'low';
    if (score < 60) return 'moderate';
    if (score < 80) return 'high';
    return 'critical';
}

// =============================================
// Durak Slot Modelleri (Çift Durma Önleme)
// =============================================

/** Durak slot tanımı — her durakta kaç araç aynı anda durabilir */
export interface StationSlot {
    stationId: number;
    totalSlots: number;          // Duraktaki toplam slot sayısı (genelde 1-2)
    occupiedSlots: number;       // Dolu slot sayısı
    queueLength: number;         // Kuyrukta bekleyen araç sayısı
}

/** Slot doluluk detayı — hangi araç hangi slotta */
export interface SlotOccupancy {
    stationId: number;
    slotIndex: number;           // 0-based slot numarası
    vehicleId: number;
    vehicleCode: string;
    enteredAt: Date;             // Slota girdiği zaman
    estimatedDwellSec: number;   // Tahmini kalış süresi (sn)
    estimatedDepartureAt: Date;  // Tahmini ayrılış zamanı
}

/** Yaklaşım hızı optimizasyon sonucu */
export interface ApproachOptimization {
    vehicleId: number;
    targetStationId: number;
    targetStationName: string;
    distanceToStationMeters: number;
    currentSpeedKmh: number;

    /** Slotlar dolu mu? */
    slotOccupied: boolean;
    /** Kuyrukta bekleyen araç sayısı */
    queueLength: number;
    /** Tahmini slot boşalma süresi (sn) */
    estimatedSlotClearanceSec: number;

    /** Hesaplanan ideal hız (km/s) */
    optimalSpeedKmh: number;
    /** Mevcut hızla devam etse kaç sn beklerdi */
    waitTimeWithoutOptimizationSec: number;
    /** Optimizasyonla tasarruf edilen süre (sn) */
    timeSavedSec: number;

    /** Bu optimizasyon aktif mi? (slot doluysa ve bölgedeyse) */
    isActive: boolean;
}
