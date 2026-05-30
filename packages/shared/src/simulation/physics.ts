// =============================================
// IDM (Intelligent Driver Model) Fizik Motoru
// Gerçekçi araç ivme/fren/takip hesaplamaları
// =============================================

import type { SimVehicle, SimConfig, LinearStop, TrafficZone } from './sim-types';

/**
 * IDM ivme hesapla.
 *
 * a_IDM = a_max * [1 - (v/v0)^delta - (s_star/s)^2]
 *
 * s_star = s0 + v*T + (v*deltaV) / (2*sqrt(a*b))
 *
 * @param v      Arac hizi (m/s)
 * @param v0     Istenen hiz (m/s)
 * @param s      Ondeki aracla mesafe (m)
 * @param deltaV Hiz farki v - v_lead (m/s)
 * @param config Simulasyon config
 */
export function computeIDM(
    v: number,
    v0: number,
    s: number,
    deltaV: number,
    config: SimConfig,
): number {
    const { maxAcceleration: a, comfortBraking: b, idmMinGap: s0, idmTimeHeadway: T, idmDelta: delta } = config;

    // İstenen mesafe s*
    const sStar = s0 + Math.max(0, v * T + (v * deltaV) / (2 * Math.sqrt(a * b)));

    // Mesafe sıfır veya çok küçükse acil fren
    const sEff = Math.max(s, 0.1);

    // IDM ivme
    const accel = a * (1 - Math.pow(v / Math.max(v0, 0.01), delta) - Math.pow(sStar / sEff, 2));

    // Sınırla
    return Math.max(-config.emergencyBraking, Math.min(config.maxAcceleration, accel));
}

/**
 * Bir araç için hedef hız hesapla.
 * Birden fazla kısıtlamanın en düşüğü seçilir:
 * 1. Yol hız limiti
 * 2. Durak yaklaşımı (frenleme eğrisi)
 * 3. Trafik bölgesi
 * 4. Max hız
 */
export function computeTargetSpeed(
    vehicle: SimVehicle,
    config: SimConfig,
    stops: LinearStop[],
    trafficZones: TrafficZone[],
    routeLength: number,
): number {
    let target = config.maxSpeed;

    // 1. Varsayılan segment hız limiti
    target = Math.min(target, config.defaultSpeedLimit);

    // 2. Durak yaklaşım frenleme — kademeli piecewise eğri
    if (vehicle.nextStopIndex < stops.length) {
        const nextStop = stops[vehicle.nextStopIndex];
        const distToStop = nextStop.meterPosition - vehicle.positionMeters;

        // Departing fazında kalkış koruması: durağı yeni terk ediyorsa
        // bir sonraki durağa hemen frenleme — en az 30m serbest ivmelenme
        const isDeparting = vehicle.phase === 'departing';

        if (distToStop > 0 && distToStop < config.approachDistance && !isDeparting) {
            let brakingTarget: number;

            if (distToStop > 30) {
                // 150m-30m arası: kademeli yavaşlama
                // Mesafe oranıyla 60% max hızdan lineer düş
                const ratio = (distToStop - 30) / (config.approachDistance - 30);
                brakingTarget = 3.0 + ratio * (config.maxSpeed * 0.6 - 3.0);
            } else if (distToStop > 10) {
                // 30m-10m arası: güçlü frenleme, 3 m/s'e doğru
                const ratio = (distToStop - 10) / 20;
                brakingTarget = 1.0 + ratio * 2.0; // 3.0 → 1.0
            } else if (distToStop > 3) {
                // 10m-3m: creep hız
                brakingTarget = 1.0;
            } else {
                // 3m altı: dur
                brakingTarget = 0;
            }

            target = Math.min(target, brakingTarget);
        }
    }

    // 3. Trafik bölgeleri
    for (const zone of trafficZones) {
        if (vehicle.positionMeters >= zone.startMeter && vehicle.positionMeters <= zone.endMeter) {
            target = Math.min(target, zone.maxSpeedMs);
        }
        // Yaklaşırken yavaşla
        const distToZone = zone.startMeter - vehicle.positionMeters;
        if (distToZone > 0 && distToZone < 100) {
            const approachSpeed = zone.maxSpeedMs + (target - zone.maxSpeedMs) * (distToZone / 100);
            target = Math.min(target, approachSpeed);
        }
    }

    // 4. Hat sonu yakınında yavaşla
    const distToEnd = routeLength - vehicle.positionMeters;
    if (distToEnd < 50) {
        target = Math.min(target, Math.sqrt(2 * config.comfortBraking * Math.max(distToEnd, 0.1)));
    }

    return Math.max(0, target);
}

/**
 * Tek araç için tek tick güncellemesi.
 * 
 * Hedef hız → mevcut hızla karşılaştır → ivme/fren uygula → pozisyon güncelle
 * 
 * @param vehicle     Güncellenecek araç
 * @param dt          Zaman adımı (sn)
 * @param targetSpeed Hesaplanmış hedef hız (m/s)
 * @param leader      Öndeki araç (varsa)
 * @param config      Simülasyon config
 */
export function updateVehiclePhysics(
    vehicle: SimVehicle,
    dt: number,
    targetSpeed: number,
    leader: SimVehicle | null,
    config: SimConfig,
): void {
    // Statik fazlar — FSM pozisyonu yönetir, fizik güncelleme yapma
    // Paralel operasyonda araçlar yerinde kalır, ileri kayma yok
    if (vehicle.phase === 'stopped' || vehicle.phase === 'doorsClosed' ||
        vehicle.phase === 'queued' || vehicle.phase === 'blocked' ||
        vehicle.phase === 'docking') return;

    let accel: number;

    if (leader) {
        // IDM: öndeki aracı takip et
        // Gap = öndeki aracın ARKA TAMPONU - bizim ön tamponumuz
        const leaderRear = leader.positionMeters - (leader.vehicleType?.lengthMeters ?? 20);
        const gap = leaderRear - vehicle.positionMeters;
        const deltaV = vehicle.speed - leader.speed;
        accel = computeIDM(vehicle.speed, targetSpeed, Math.max(0.1, gap), deltaV, config);
    } else {
        // Serbest sürüş: hedef hıza doğru ivmelen
        const speedDiff = targetSpeed - vehicle.speed;
        if (speedDiff > 0) {
            accel = Math.min(config.maxAcceleration, speedDiff / dt);
        } else {
            accel = Math.max(-config.comfortBraking, speedDiff / dt);
        }
    }

    // Sınırla
    accel = Math.max(-config.emergencyBraking, Math.min(config.maxAcceleration, accel));

    // Hız güncelle
    vehicle.acceleration = accel;
    vehicle.speed = Math.max(0, vehicle.speed + accel * dt);

    // Pozisyon güncelle
    const ds = vehicle.speed * dt + 0.5 * accel * dt * dt;
    vehicle.positionMeters += Math.max(0, ds);
    vehicle.totalDistance += Math.max(0, ds);
}
