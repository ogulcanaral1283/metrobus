"""
IDM (Intelligent Driver Model) Fizik Motoru
TypeScript physics.ts'den Python'a taşındı.
Gerçekçi araç ivme/fren/takip hesaplamaları.
"""

from __future__ import annotations

import math

try:
    from .config import SimConfig, SimVehicle, TrafficZone, VEHICLE_LENGTH
    from .route_data import LinearStop
except ImportError:
    from config import SimConfig, SimVehicle, TrafficZone, VEHICLE_LENGTH
    from route_data import LinearStop


def compute_idm(
    v: float,
    v0: float,
    s: float,
    delta_v: float,
    config: SimConfig,
) -> float:
    """
    IDM ivme hesapla.

    a_IDM = a_max * [1 - (v/v0)^delta - (s_star/s)^2]
    s_star = s0 + v*T + (v * deltaV) / (2 * sqrt(a*b))

    Args:
        v:       Araç hızı (m/s)
        v0:      İstenen hız (m/s)
        s:       Öndeki araçla mesafe (m)
        delta_v: Hız farkı v - v_lead (m/s)
        config:  Simülasyon config
    """
    a = config.max_acceleration
    b = config.comfort_braking
    s0 = config.idm_min_gap
    T = config.idm_time_headway
    delta = config.idm_delta

    # İstenen mesafe s*
    s_star = s0 + max(0.0, v * T + (v * delta_v) / (2.0 * math.sqrt(a * b)))

    # Mesafe sıfır veya çok küçükse acil fren
    s_eff = max(s, 0.1)

    # IDM ivme
    accel = a * (1.0 - (v / max(v0, 0.01)) ** delta - (s_star / s_eff) ** 2)

    # Sınırla
    return max(-config.emergency_braking, min(config.max_acceleration, accel))


def compute_target_speed(
    vehicle: SimVehicle,
    config: SimConfig,
    stops: list[LinearStop],
    traffic_zones: list[TrafficZone],
    route_length: float,
) -> float:
    """
    Bir araç için hedef hız hesapla.
    Birden fazla kısıtlamanın en düşüğü seçilir:
    1. Yol hız limiti
    2. Durak yaklaşımı (frenleme eğrisi)
    3. Trafik bölgesi
    4. Hat sonu
    """
    target = config.max_speed

    # 1. Varsayılan segment hız limiti
    target = min(target, config.default_speed_limit)

    # 2. Durak yaklaşım frenleme — kademeli piecewise eğri (TS physics.ts ile senkron)
    if vehicle.next_stop_index < len(stops):
        next_stop = stops[vehicle.next_stop_index]
        dist_to_stop = next_stop.meter_position - vehicle.position_meters

        # Departing fazında kalkış koruması: durağı yeni terk ediyorsa
        # bir sonraki durağa hemen frenleme — en az 30m serbest ivmelenme
        is_departing = vehicle.phase == "departing"

        if 0 < dist_to_stop < config.approach_distance and not is_departing:
            if dist_to_stop > 30:
                # 150m-30m arası: kademeli yavaşlama
                # Mesafe oranıyla 60% max hızdan lineer düş
                ratio = (dist_to_stop - 30) / (config.approach_distance - 30)
                braking_target = 3.0 + ratio * (config.max_speed * 0.6 - 3.0)
            elif dist_to_stop > 10:
                # 30m-10m arası: güçlü frenleme, 3 m/s'e doğru
                ratio = (dist_to_stop - 10) / 20.0
                braking_target = 1.0 + ratio * 2.0  # 3.0 → 1.0
            elif dist_to_stop > 3:
                # 10m-3m: creep hız
                braking_target = 1.0
            else:
                # 3m altı: dur
                braking_target = 0.0

            target = min(target, braking_target)

    # 3. Trafik bölgeleri
    for zone in traffic_zones:
        if zone.start_meter <= vehicle.position_meters <= zone.end_meter:
            target = min(target, zone.max_speed_ms)
        # Yaklaşırken yavaşla
        dist_to_zone = zone.start_meter - vehicle.position_meters
        if 0 < dist_to_zone < 100:
            approach_speed = (
                zone.max_speed_ms
                + (target - zone.max_speed_ms) * (dist_to_zone / 100.0)
            )
            target = min(target, approach_speed)

    # 4. Hat sonu yakınında yavaşla
    dist_to_end = route_length - vehicle.position_meters
    if dist_to_end < 50:
        target = min(
            target,
            math.sqrt(2.0 * config.comfort_braking * max(dist_to_end, 0.1)),
        )

    return max(0.0, target)


def update_vehicle_physics(
    vehicle: SimVehicle,
    dt: float,
    target_speed: float,
    leader: SimVehicle | None,
    config: SimConfig,
) -> None:
    """
    Tek araç için tek tick fizik güncellemesi.
    Statik fazlarda (stopped, doorsClosed, queued, blocked, docking) fizik atlanır.
    """
    # Statik fazlar — FSM pozisyonu yönetir
    if vehicle.phase in ("stopped", "doorsClosed", "queued", "blocked", "docking"):
        return

    if leader is not None:
        # IDM: öndeki aracı takip et
        # Gap = öndeki aracın ARKA TAMPONU - bizim ön tamponumuz
        leader_rear = leader.position_meters - VEHICLE_LENGTH
        gap = max(0.1, leader_rear - vehicle.position_meters)
        delta_v = vehicle.speed - leader.speed
        accel = compute_idm(vehicle.speed, target_speed, gap, delta_v, config)
    else:
        # Serbest sürüş: hedef hıza doğru ivmelen
        speed_diff = target_speed - vehicle.speed
        if speed_diff > 0:
            accel = min(config.max_acceleration, speed_diff / dt)
        else:
            accel = max(-config.comfort_braking, speed_diff / dt)

    # Sınırla
    accel = max(-config.emergency_braking, min(config.max_acceleration, accel))

    # Hız güncelle
    vehicle.acceleration = accel
    vehicle.speed = max(0.0, vehicle.speed + accel * dt)

    # Pozisyon güncelle
    ds = vehicle.speed * dt + 0.5 * accel * dt * dt
    ds = max(0.0, ds)
    vehicle.position_meters += ds
    vehicle.total_distance += ds
