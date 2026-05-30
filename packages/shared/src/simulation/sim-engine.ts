// =============================================
// SimEngine — Ana Simülasyon Döngüsü
// Tüm modülleri birleştirip multi-vehicle yönetimi sağlar
// =============================================

import type { SimVehicle, SimConfig, SimState, TrafficZone, LinearStop } from './sim-types';
import { DEFAULT_SIM_CONFIG, VEHICLE_TYPES } from './sim-types';
import type { LinearRoute } from './route-linearizer';
import { linearizeRoute, meterToPosition } from './route-linearizer';
import { computeTargetSpeed, updateVehiclePhysics } from './physics';
import { updateStationFSM } from './station-fsm';
import { updateTrafficZones, checkRushHour } from './traffic';
import type { RouteEdge, NetworkStop } from '../types/route-network';

export class SimEngine {
    private config: SimConfig;
    private route: LinearRoute;
    private vehicles: SimVehicle[] = [];
    private trafficZones: TrafficZone[] = [];
    private simTime: number = 0;
    private running: boolean = false;
    private timeScale: number = 1;
    private nextId: number = 1;

    constructor(
        edges: RouteEdge[],
        stops: NetworkStop[],
        direction: 'gidis' | 'donus',
        config?: Partial<SimConfig>,
    ) {
        this.config = { ...DEFAULT_SIM_CONFIG, ...config };
        this.route = linearizeRoute(edges, stops, direction);
        this.timeScale = this.config.timeScale;
    }

    /** Simülasyonu başlat — araçları hat boyunca eşit aralıklarla yerleştir */
    init(vehicleCount?: number): void {
        const count = vehicleCount ?? this.config.vehicleCount;
        this.vehicles = [];
        this.nextId = 1;

        for (let i = 0; i < count; i++) {
            this.spawnVehicle();
        }

        this.trafficZones = [];
        this.simTime = 0;
        this.running = true;
    }

    /** Yeni araç ekle */
    spawnVehicle(): SimVehicle {
        const id = this.nextId++;
        // Hat boyunca rastgele pozisyon (mevcut araçlar arasına yerleştir)
        let pos: number;
        if (this.vehicles.length === 0) {
            pos = this.route.totalLength * 0.1;
        } else {
            // En büyük boşluğu bul ve oraya yerleştir
            const positions = this.vehicles
                .map(v => v.positionMeters)
                .sort((a, b) => a - b);
            let maxGap = 0, gapStart = 0;
            for (let i = 0; i < positions.length - 1; i++) {
                const gap = positions[i + 1] - positions[i];
                if (gap > maxGap) { maxGap = gap; gapStart = positions[i]; }
            }
            // Hat başı/sonu boşluğu da kontrol et
            const endGap = this.route.totalLength - positions[positions.length - 1];
            if (endGap > maxGap) { gapStart = positions[positions.length - 1]; maxGap = endGap; }
            const startGap = positions[0];
            if (startGap > maxGap) { gapStart = 0; maxGap = startGap; }

            pos = gapStart + maxGap / 2;
        }

        const { latitude, longitude, heading } = meterToPosition(this.route, pos);

        let nextStopIdx = 0;
        for (let si = 0; si < this.route.stops.length; si++) {
            if (this.route.stops[si].meterPosition > pos) {
                nextStopIdx = si;
                break;
            }
        }

        const dirLabel = this.route.direction === 'gidis' ? 'G' : 'D';
        // %60 Mercedes (20m), %40 Akia (25m)
        const vehicleType = Math.random() < 0.6 ? VEHICLE_TYPES[0] : VEHICLE_TYPES[1];
        const vehicle: SimVehicle = {
            id,
            code: `${dirLabel}${String(id).padStart(3, '0')}`,
            vehicleType,
            positionMeters: pos,
            speed: 5 + Math.random() * 5, // 5-10 m/s başlangıç
            acceleration: 0,
            phase: 'cruising',
            heading,
            latitude,
            longitude,
            direction: this.route.direction,
            dwellRemaining: 0,
            nextStopIndex: nextStopIdx,
            totalStops: 0,
            totalDistance: 0,
            manualOverride: null,
            isQueuing: false,
            queueWaitTime: 0,
            lastDwellTime: 0,
            assignedSlotIndex: -1,
            slotMeterPosition: 0,
        };

        this.vehicles.push(vehicle);
        return vehicle;
    }

    /** Araç kaldır */
    removeVehicle(vehicleId: number): boolean {
        const idx = this.vehicles.findIndex(v => v.id === vehicleId);
        if (idx === -1) return false;
        this.vehicles.splice(idx, 1);
        return true;
    }

    // ========================================
    // PER-VEHICLE KOMUTLAR
    // ========================================

    /** Aracı durdur (manualOverride = 0) */
    stopVehicle(vehicleId: number): void {
        const v = this.vehicles.find(v => v.id === vehicleId);
        if (v) v.manualOverride = 0;
    }

    /** Aracı yavaşlat (manualOverride = 5 m/s ≈ 18 km/h) */
    slowVehicle(vehicleId: number): void {
        const v = this.vehicles.find(v => v.id === vehicleId);
        if (v) v.manualOverride = 5;
    }

    /** Aracı hızlandır (manualOverride kaldır → normal seyir) */
    releaseVehicle(vehicleId: number): void {
        const v = this.vehicles.find(v => v.id === vehicleId);
        if (v) v.manualOverride = null;
    }

    /** Manuel hız ayarla (m/s cinsinden) */
    setVehicleSpeed(vehicleId: number, speedMs: number): void {
        const v = this.vehicles.find(v => v.id === vehicleId);
        if (v) v.manualOverride = Math.max(0, speedMs);
    }

    // ========================================

    /** Tek simülasyon tick'i */
    tick(realDt: number): SimState {
        if (!this.running || this.vehicles.length === 0) {
            return this.getState();
        }

        const dt = realDt * this.timeScale;
        this.simTime += dt;

        const isRush = checkRushHour(this.simTime);

        // 1. Trafik bölgelerini güncelle
        this.trafficZones = updateTrafficZones(
            this.trafficZones, dt, this.route.totalLength, this.config, isRush,
        );

        // 2. Her durakta kaç araç durduğunu ve hangi slot'ların dolu olduğunu hesapla
        const stationOccupancy = new Map<number, number>();
        const occupiedSlots = new Map<string, Set<number>>();
        for (const v of this.vehicles) {
            // Perondaki tüm araçları say: stopped, doorsClosed, blocked, docking
            if (v.phase === 'stopped' || v.phase === 'doorsClosed' ||
                v.phase === 'blocked' || v.phase === 'docking') {
                const stopIdx = v.nextStopIndex;
                stationOccupancy.set(stopIdx, (stationOccupancy.get(stopIdx) ?? 0) + 1);

                // Hangi slot dolu?
                if (v.assignedSlotIndex >= 0) {
                    const key = `s${stopIdx}`;
                    if (!occupiedSlots.has(key)) occupiedSlots.set(key, new Set());
                    occupiedSlots.get(key)!.add(v.assignedSlotIndex);
                }
            }
        }

        // 3. Araçları pozisyona göre sırala (öndeki araç tespiti için)
        const sorted = [...this.vehicles].sort((a, b) => a.positionMeters - b.positionMeters);

        // 4. Her araç için fizik + durak FSM güncelle
        for (let i = 0; i < sorted.length; i++) {
            const vehicle = sorted[i];

            // Manuel durdurulmuş araç
            if (vehicle.manualOverride === 0) {
                // Frenleme uygula
                if (vehicle.speed > 0) {
                    vehicle.acceleration = -this.config.comfortBraking;
                    vehicle.speed = Math.max(0, vehicle.speed + vehicle.acceleration * dt);
                    vehicle.positionMeters += vehicle.speed * dt;
                } else {
                    vehicle.speed = 0;
                    vehicle.acceleration = 0;
                }
                this.updatePosition(vehicle);
                continue;
            }

            // Durak FSM (manuel override yoksa)
            if (vehicle.manualOverride === null) {
                updateStationFSM(vehicle, dt, this.route.stops, this.config, isRush, stationOccupancy, occupiedSlots, this.vehicles);
            }

            // Peronda statik fazlar: FSM pozisyonu yönetir, fizik ATLAMA
            // Paralel operasyon: araç nerede durduysa orada kalır
            if ((vehicle.phase === 'stopped' || vehicle.phase === 'doorsClosed' ||
                vehicle.phase === 'queued' || vehicle.phase === 'blocked') &&
                vehicle.manualOverride === null) {
                // FSM zaten pozisyonu ayarladı — sadece lat/lng güncelle
                this.updatePosition(vehicle);
                continue;
            }

            // Docking fazında fizik FSM tarafından yönetilir
            if (vehicle.phase === 'docking' && vehicle.manualOverride === null) {
                this.updatePosition(vehicle);
                continue;
            }

            // Hedef hız hesapla
            let targetSpeed = computeTargetSpeed(
                vehicle, this.config, this.route.stops, this.trafficZones, this.route.totalLength,
            );

            // Manuel override varsa hedef hızı sınırla
            if (vehicle.manualOverride !== null) {
                targetSpeed = Math.min(targetSpeed, vehicle.manualOverride);
            }

            // Öndeki araç (aynı yöndeki bir sonraki)
            const leader = i < sorted.length - 1 ? sorted[i + 1] : null;

            // Fizik güncelle
            updateVehiclePhysics(vehicle, dt, targetSpeed, leader, this.config);

            // Hat sonuna ulaştıysa başa dön
            if (vehicle.positionMeters >= this.route.totalLength) {
                vehicle.positionMeters = 0;
                vehicle.nextStopIndex = 0;
                vehicle.phase = 'cruising';
                vehicle.isQueuing = false;
                vehicle.queueWaitTime = 0;
            }

            // Lat/lng güncelle
            this.updatePosition(vehicle);
        }

        return this.getState();
    }

    /** Araç lat/lng ve heading'ini metre pozisyonundan güncelle */
    private updatePosition(vehicle: SimVehicle): void {
        const { latitude, longitude, heading } = meterToPosition(this.route, vehicle.positionMeters);
        vehicle.latitude = latitude;
        vehicle.longitude = longitude;
        vehicle.heading = heading;
    }

    /** Simülasyon durumunu al */
    getState(): SimState {
        return {
            time: this.simTime,
            vehicles: [...this.vehicles],
            trafficZones: [...this.trafficZones],
            isRushHour: checkRushHour(this.simTime),
            running: this.running,
            timeScale: this.timeScale,
        };
    }

    /** Hız çarpanını ayarla */
    setTimeScale(scale: number): void {
        this.timeScale = Math.max(0.1, Math.min(20, scale));
    }

    /** Duraklat/devam et */
    togglePause(): boolean {
        this.running = !this.running;
        return this.running;
    }

    /** Araç sayısı */
    getVehicleCount(): number {
        return this.vehicles.length;
    }

    /** Rota bilgisi */
    getRouteInfo(): { totalLength: number; stopCount: number; direction: string } {
        return {
            totalLength: this.route.totalLength,
            stopCount: this.route.stops.length,
            direction: this.route.direction,
        };
    }

    /** Durak listesi */
    getStops(): LinearStop[] {
        return this.route.stops;
    }
}
