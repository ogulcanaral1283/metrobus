// =============================================
// Araç Veri Modelleri
// =============================================

import type { DriverCommand } from './command';

/** Araç durumu */
export type VehicleStatus = 'active' | 'inactive' | 'maintenance';

/** Araç tanımı */
export interface Vehicle {
    id: number;
    plateNumber: string;
    vehicleCode: string;
    capacity: number;
    currentStatus: VehicleStatus;
}

/** Araç anlık konum verisi */
export interface VehiclePosition {
    time: Date;
    vehicleId: number;
    latitude: number;
    longitude: number;
    speedKmh: number;
    heading: number;
    nearestStationId: number | null;
    distanceToStation: number | null;
}

/** Araç durum özeti (gerçek zamanlı) */
export interface VehicleState {
    vehicleId: number;
    vehicleCode: string;
    position: {
        latitude: number;
        longitude: number;
    };
    speedKmh: number;
    heading: number;
    direction: RouteDirection;
    nearestStation: {
        id: number;
        code: string;
        name: string;
        distanceMeters: number;
    } | null;
    nextStation: {
        id: number;
        code: string;
        name: string;
        etaSeconds: number;
    } | null;
    headway: {
        leadingVehicleId: number | null;
        followingVehicleId: number | null;
        leadingHeadwaySeconds: number | null;
        followingHeadwaySeconds: number | null;
    };
    currentCommand: DriverCommand | null;
    lastUpdated: Date;
}

/** Yön tipi */
export type RouteDirection = 'east' | 'west';
