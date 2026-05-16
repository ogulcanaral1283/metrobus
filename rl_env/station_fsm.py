"""
Durak State Machine (FSM) — Paralel Peron Operasyonu
TypeScript station-fsm.ts'den Python'a taşındı.

TEMEL PRENSİP: Araçlar peron alanı içine girdiği anda
yolcu operasyonuna BAŞLAR. En öne gitmeyi BEKLEMEZler.

Paralel Operasyon:
  - Peron üzerinde birden fazla araç aynı anda kapı açık
  - Her araç kendi dwell_remaining'ini bağımsız sayar
  - Süre dolan araç, önü açılınca kalkış yapar
  - İleri kayma YOK — araç durduğu yerde kalır

State Machine:
  cruising    → approaching  (approachDistance veya platformZone)
  approaching → queued       (peron dolu — yer yok)
  approaching → docking      (peron alanında yer var)
  approaching → stopped      (platformZone içinde + hız ≈ 0)
  queued      → docking      (yer boşaldı)
  docking     → stopped      (pozisyona ulaştı → ANINDA yolcu op.)
  stopped     → doorsClosed  (dwell doldu)
  doorsClosed → blocked      (gap < SAFE_GAP)
  doorsClosed → departing    (gap >= SAFE_GAP veya önde araç yok)
  blocked     → departing    (önü açıldı)
  departing   → cruising     (hız > 3 m/s)
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

try:
    from .config import SimConfig, SimVehicle, VEHICLE_LENGTH
    from .route_data import LinearStop
except ImportError:
    from config import SimConfig, SimVehicle, VEHICLE_LENGTH
    from route_data import LinearStop

# Istanbul metrobus araci uzunlugu (metre) — TS VEHICLE_TYPES ile senkron
BUS_LENGTH_METERS = 20.0

# Araçlar arası boşluk (metre) — peron içi park mesafesi
VEHICLE_GAP_METERS = 5.0

# Güvenli kalkış mesafesi (metre)
SAFE_GAP = 0.5


# Varsayılan platform uzunluğu (metre) — veri eksik duraklarda kullanılır
DEFAULT_PLATFORM_LENGTH = 60.0


# ============================================
# Yardımcı Fonksiyonlar
# ============================================

def _effective_platform_length(stop: LinearStop) -> float:
    """Durağın efektif platform uzunluğu. Veri eksikse varsayılan kullan."""
    if stop.platform_length_meters > 0:
        return stop.platform_length_meters
    return DEFAULT_PLATFORM_LENGTH


def is_inside_platform_zone(
    vehicle_position: float,
    vehicle_length: float,
    stop: LinearStop,
) -> bool:
    """
    Araç peron alanı içinde mi?
    Peron alanı = [stop.meter_position - platform_length, stop.meter_position + 15]
    """
    platform_len = _effective_platform_length(stop)
    vehicle_rear = vehicle_position - vehicle_length
    platform_start = stop.meter_position - platform_len
    platform_end = stop.meter_position + vehicle_length  # araç uzunluğu kadar tolerans

    return vehicle_position <= platform_end and vehicle_rear >= platform_start - 2


def compute_max_buses_at_stop(stop: LinearStop) -> int:
    """
    Platform kapasitesi: platform_uzunluğu / (araç_uzunluğu + araçlar_arası_boşluk).

    Her otobüs BUS_LENGTH_METERS (20m) + VEHICLE_GAP_METERS (5m) = 25m yer kaplar.
    Platform uzunluğu bu değere bölünerek slot sayısı hesaplanır.

    Örnek: 118m platform → 118 / 25 = 4 slot
           91m platform  → 91 / 25  = 3 slot
           55m platform  → 55 / 25  = 2 slot
    """
    platform_len = _effective_platform_length(stop)
    slot_size = BUS_LENGTH_METERS + VEHICLE_GAP_METERS  # 25m
    return max(1, math.floor(platform_len / slot_size))


def get_vehicles_on_platform(
    stop_index: int,
    all_vehicles: list[SimVehicle],
) -> list[SimVehicle]:
    """
    Perondaki TÜM araçları al.
    stopped + doorsClosed + blocked + docking hepsi peronda.
    En öndeki → en arkadaki sırasıyla.
    """
    result = []
    for v in all_vehicles:
        if v.phase in ("stopped", "doorsClosed", "blocked", "docking"):
            if v.next_stop_index == stop_index:
                result.append(v)
    result.sort(key=lambda v: v.position_meters, reverse=True)
    return result


def compute_entry_position(
    stop: LinearStop,
    platform_vehicles: list[SimVehicle],
) -> float:
    """Perondaki en arkaya yeni araç için durma pozisyonu."""
    if not platform_vehicles:
        return stop.meter_position
    last_vehicle = platform_vehicles[-1]
    last_rear = last_vehicle.position_meters - VEHICLE_LENGTH
    return last_rear - SAFE_GAP


def fits_in_platform(
    stop_position: float,
    vehicle_length: float,
    stop: LinearStop,
) -> bool:
    """Aracın tamamı peron alanına sığıyor mu? (TS fitsInPlatform ile senkron)"""
    platform_len = _effective_platform_length(stop)
    vehicle_rear = stop_position - vehicle_length
    platform_start = stop.meter_position - platform_len
    front_ok = stop_position <= stop.meter_position + 2   # TS: +2m
    rear_ok = vehicle_rear >= platform_start - 1           # TS: -1m
    return front_ok and rear_ok


def is_blocked_by_gap(
    vehicle: SimVehicle,
    stop_index: int,
    all_vehicles: list[SimVehicle],
) -> bool:
    """
    Fiziksel gap kontrolü — önde engel var mı?
    Kalkış şartı: önde hiç araç yok VEYA öndeki aracın
    arka tamponu ile bizim ön tamponumuz arasında >= SAFE_GAP
    """
    for v in all_vehicles:
        if v.id == vehicle.id:
            continue
        if v.position_meters <= vehicle.position_meters:
            continue

        # Aynı duraktaki statik araçlar → kesin engel
        if v.phase in ("stopped", "doorsClosed", "blocked"):
            if v.next_stop_index == stop_index:
                return True

        # Departing araç — fiziksel gap kontrolü
        if v.phase == "departing":
            v_rear = v.position_meters - VEHICLE_LENGTH
            gap = v_rear - vehicle.position_meters
            if gap < SAFE_GAP:
                return True

    return False


def find_nearest_leader_on_platform(
    vehicle: SimVehicle,
    all_vehicles: list[SimVehicle],
) -> SimVehicle | None:
    """Peron üzerinde bu aracın en yakın önündeki aracı bul."""
    nearest = None
    nearest_dist = float("inf")

    for v in all_vehicles:
        if v.id == vehicle.id:
            continue
        if v.next_stop_index != vehicle.next_stop_index:
            continue
        if v.position_meters <= vehicle.position_meters:
            continue

        if v.phase in ("stopped", "doorsClosed", "blocked", "docking"):
            dist = v.position_meters - vehicle.position_meters
            if dist < nearest_dist:
                nearest_dist = dist
                nearest = v

    return nearest


# ============================================
# Ana FSM Güncelleme
# ============================================

def update_station_fsm(
    vehicle: SimVehicle,
    dt: float,
    stops: list[LinearStop],
    config: SimConfig,
    is_rush_hour: bool,
    all_vehicles: list[SimVehicle] | None = None,
    use_fixed_dwell: bool = False,
    fixed_dwell_seconds: float = 15.0,
    rng: Optional[np.random.Generator] = None,
    demand_profile=None,
    current_hour: float = 8.0,
) -> None:
    """
    Durak state machine — PARALEL PERON OPERASYONU.

    Araç peron alanına girip durduğu anda yolcu operasyonu başlar.
    En öne gitmeyi beklemez. Birden fazla araç aynı anda kapı açık.
    """
    if rng is None:
        rng = np.random.default_rng()

    if vehicle.next_stop_index >= len(stops):
        return

    next_stop = stops[vehicle.next_stop_index]
    dist_to_stop = next_stop.meter_position - vehicle.position_meters
    vehicle_list = all_vehicles if all_vehicles is not None else []

    # ============================================
    # CRUISING
    # ============================================
    if vehicle.phase == "cruising":
        vehicle.is_queuing = False
        vehicle.queue_wait_time = 0.0

        v_len = VEHICLE_LENGTH
        in_zone = is_inside_platform_zone(vehicle.position_meters, v_len, next_stop)

        if in_zone:
            # RL aksiyonu: durak atlama
            if vehicle.skip_next_stop:
                vehicle.next_stop_index += 1
                vehicle.skip_next_stop = False
                return
            vehicle.phase = "approaching"
            return

        # Normal yaklaşma mesafesi
        if 0 < dist_to_stop < config.approach_distance:
            if vehicle.skip_next_stop:
                vehicle.next_stop_index += 1
                vehicle.skip_next_stop = False
                return
            vehicle.phase = "approaching"

        # Sadece peronu tamamen geçtiyse ve peron içinde değilse
        if dist_to_stop < -15 and not in_zone:
            vehicle.next_stop_index += 1

    # ============================================
    # APPROACHING — Alan Tabanlı Giriş
    # ============================================
    elif vehicle.phase == "approaching":
        v_len = VEHICLE_LENGTH
        in_zone = is_inside_platform_zone(vehicle.position_meters, v_len, next_stop)

        # === PERON ALANI İÇİNDE VE DURMUŞ ===
        if in_zone and vehicle.speed < 0.5:
            # Slot pozisyonunu doğru hesapla (üst üste binme önleme)
            platform_vehicles = get_vehicles_on_platform(vehicle.next_stop_index, vehicle_list)
            # Kendini listeden çıkar
            platform_vehicles = [pv for pv in platform_vehicles if pv.id != vehicle.id]
            entry_pos = compute_entry_position(next_stop, platform_vehicles)
            # Mevcut pozisyon ile hesaplanan slot arasında makul olanı seç
            # Araç zaten peron içindeyse, geriye gitmesine gerek yok
            slot_pos = max(entry_pos, vehicle.position_meters) if platform_vehicles else vehicle.position_meters

            vehicle.phase = "stopped"
            vehicle.speed = 0.0
            vehicle.acceleration = 0.0
            vehicle.slot_meter_position = slot_pos
            vehicle.position_meters = slot_pos
            vehicle.is_queuing = False
            vehicle.queue_wait_time = 0.0
            vehicle.total_stops += 1

            dwell = _compute_realistic_dwell(
                next_stop, config, is_rush_hour, rng,
                use_fixed_dwell, fixed_dwell_seconds,
                demand_profile, current_hour,
            )
            dwell += vehicle.holding_extra
            vehicle.holding_extra = 0.0
            vehicle.dwell_remaining = dwell
            vehicle.last_dwell_time = dwell
            return

        # === PERON ALANI İÇİNDE AMA HAREKET EDİYOR ===
        if in_zone and vehicle.speed >= 0.5:
            leader = find_nearest_leader_on_platform(vehicle, vehicle_list)
            if leader:
                leader_rear = leader.position_meters - VEHICLE_LENGTH
                gap = leader_rear - vehicle.position_meters
                if gap < SAFE_GAP:
                    # Öndeki araca çok yakın → BURADA DUR
                    # Slot pozisyonunu öndeki aracın arkasına göre hesapla
                    safe_pos = leader_rear - SAFE_GAP
                    vehicle.phase = "stopped"
                    vehicle.speed = 0.0
                    vehicle.acceleration = 0.0
                    vehicle.slot_meter_position = safe_pos
                    vehicle.position_meters = safe_pos
                    vehicle.is_queuing = False
                    vehicle.total_stops += 1

                    dwell = _compute_realistic_dwell(
                        next_stop, config, is_rush_hour, rng,
                        use_fixed_dwell, fixed_dwell_seconds,
                        demand_profile, current_hour,
                    )
                    dwell += vehicle.holding_extra
                    vehicle.holding_extra = 0.0
                    vehicle.dwell_remaining = dwell
                    vehicle.last_dwell_time = dwell
                    return
            # Frenlemeye devam
            return

        # === PERON ALANI DIŞINDA — fallback ===
        platform_vehicles = get_vehicles_on_platform(vehicle.next_stop_index, vehicle_list)
        entry_pos = compute_entry_position(next_stop, platform_vehicles)

        if vehicle.speed < 3.0 and -5 < dist_to_stop < 8:
            if fits_in_platform(entry_pos, v_len, next_stop):
                vehicle.phase = "docking"
                vehicle.is_queuing = False
                vehicle.queue_wait_time = 0.0
                vehicle.slot_meter_position = entry_pos
            else:
                vehicle.phase = "queued"
                vehicle.is_queuing = True
                vehicle.speed = 0.0
                vehicle.acceleration = 0.0

        # Durağı tamamen geçtiyse → bir sonraki durağa ilerle (sonsuz döngü önleme)
        overshoot_limit = max(5, next_stop.platform_length_meters * 0.5)
        if dist_to_stop <= -overshoot_limit and not in_zone:
            vehicle.phase = "cruising"
            vehicle.next_stop_index += 1

    # ============================================
    # QUEUED — Peron girişinde bekleme
    # ============================================
    elif vehicle.phase == "queued":
        vehicle.queue_wait_time += dt
        vehicle.speed = 0.0
        vehicle.acceleration = 0.0

        platform_vehicles = get_vehicles_on_platform(vehicle.next_stop_index, vehicle_list)
        entry_pos = compute_entry_position(next_stop, platform_vehicles)

        if fits_in_platform(entry_pos, VEHICLE_LENGTH, next_stop):
            vehicle.phase = "docking"
            vehicle.is_queuing = False
            # Slot pozisyonu mevcut pozisyondan ileride olmalı
            # Gerideyse araç zaten peronda → direkt stopped'a geç
            if entry_pos <= vehicle.position_meters:
                vehicle.phase = "stopped"
                vehicle.speed = 0.0
                vehicle.acceleration = 0.0
                vehicle.slot_meter_position = vehicle.position_meters
                vehicle.total_stops += 1
                dwell = _compute_realistic_dwell(
                    next_stop, config, is_rush_hour, rng,
                    use_fixed_dwell, fixed_dwell_seconds,
                    demand_profile, current_hour,
                )
                dwell += vehicle.holding_extra
                vehicle.holding_extra = 0.0
                vehicle.dwell_remaining = dwell
                vehicle.last_dwell_time = dwell
            else:
                vehicle.slot_meter_position = entry_pos

    # ============================================
    # DOCKING — Slot'a yavaş ilerleme (2 m/s)
    # ============================================
    elif vehicle.phase == "docking":
        dist_to_slot = vehicle.slot_meter_position - vehicle.position_meters

        if abs(dist_to_slot) < 1.0 or dist_to_slot < 0:
            # Pozisyona ulaştı → yolcu operasyonu
            vehicle.phase = "stopped"
            vehicle.speed = 0.0
            vehicle.acceleration = 0.0
            # Overshoot varsa mevcut pozisyonda kal (geriye teleport yok)
            if dist_to_slot >= -0.5:
                vehicle.position_meters = vehicle.slot_meter_position
            else:
                vehicle.slot_meter_position = vehicle.position_meters
            vehicle.total_stops += 1

            dwell = _compute_realistic_dwell(
                next_stop, config, is_rush_hour, rng,
                use_fixed_dwell, fixed_dwell_seconds,
                demand_profile, current_hour,
            )
            dwell += vehicle.holding_extra
            vehicle.holding_extra = 0.0
            vehicle.dwell_remaining = dwell
            vehicle.last_dwell_time = dwell
        else:
            # Kinematik tutarlı docking: hızı önce sınırla, sonra hareket et
            DOCKING_SPEED_CAP = 2.0  # m/s
            v_old = vehicle.speed
            # Hız cap üstündeyse önce frenle
            if v_old > DOCKING_SPEED_CAP:
                dock_accel = max(-config.comfort_braking, (DOCKING_SPEED_CAP - v_old) / dt)
            elif v_old < DOCKING_SPEED_CAP:
                dock_accel = min(config.max_acceleration, (DOCKING_SPEED_CAP - v_old) / dt)
            else:
                dock_accel = 0.0
            ds = v_old * dt + 0.5 * dock_accel * dt * dt
            vehicle.position_meters += max(0.0, ds)
            vehicle.speed = max(0.0, min(DOCKING_SPEED_CAP, v_old + dock_accel * dt))

    # ============================================
    # STOPPED — Kapılar açık, yolcu operasyonu (PARALEL)
    # ============================================
    elif vehicle.phase == "stopped":
        vehicle.position_meters = vehicle.slot_meter_position
        vehicle.speed = 0.0

        vehicle.dwell_remaining -= dt

        if vehicle.dwell_remaining <= 0:
            vehicle.dwell_remaining = 0.0
            vehicle.phase = "doorsClosed"
            vehicle.dwell_remaining = 2.0  # Kapı kapanma 2s

    # ============================================
    # DOORS CLOSED — Kapılar kapanıyor (2s)
    # ============================================
    elif vehicle.phase == "doorsClosed":
        vehicle.position_meters = vehicle.slot_meter_position
        vehicle.speed = 0.0

        vehicle.dwell_remaining -= dt

        if vehicle.dwell_remaining <= 0:
            vehicle.dwell_remaining = 0.0
            if is_blocked_by_gap(vehicle, vehicle.next_stop_index, vehicle_list):
                vehicle.phase = "blocked"
            else:
                vehicle.phase = "departing"
                vehicle.next_stop_index += 1

    # ============================================
    # BLOCKED — Önde engel var
    # ============================================
    elif vehicle.phase == "blocked":
        vehicle.position_meters = vehicle.slot_meter_position
        vehicle.speed = 0.0

        # Deadlock önleme: 5 saniye beklediyse VE önü açıksa kalk
        vehicle.queue_wait_time += dt
        if vehicle.queue_wait_time > 5.0 and not is_blocked_by_gap(vehicle, vehicle.next_stop_index, vehicle_list):
            vehicle.phase = "departing"
            vehicle.queue_wait_time = 0.0
            vehicle.next_stop_index += 1
        elif vehicle.queue_wait_time > 15.0:
            # Gerçek deadlock: 15s sonra zorla kalk (son çare)
            vehicle.phase = "departing"
            vehicle.queue_wait_time = 0.0
            vehicle.next_stop_index += 1
        elif not is_blocked_by_gap(vehicle, vehicle.next_stop_index, vehicle_list):
            vehicle.phase = "departing"
            vehicle.queue_wait_time = 0.0
            vehicle.next_stop_index += 1

    # ============================================
    # DEPARTING — Kalkış ivmelenmesi
    # ============================================
    elif vehicle.phase == "departing":
        vehicle.acceleration = config.max_acceleration  # TS ile senkron: kalkışta ivme ata
        if vehicle.speed > 3.0:
            vehicle.phase = "cruising"


# ============================================
# Dwell Time Hesaplama
# ============================================

def _compute_passenger_load(
    stop: LinearStop,
    is_rush_hour: bool,
    rng: np.random.Generator,
    demand_profile=None,
    current_hour: float = 8.0,
) -> int:
    """Duraktaki yolcu sayisini hesapla."""
    if demand_profile is not None:
        return demand_profile.get_passenger_count(
            stop.name, current_hour, rng=rng
        )

    base = 5 + int(rng.integers(0, 15))
    rush_multiplier = 2.5 if is_rush_hour else 1.0
    center_bonus = 1.3 if 10 < stop.index < 30 else 1.0
    max_buses = compute_max_buses_at_stop(stop)
    platform_bonus = 1.0 + (max_buses - 1) * 0.15

    return round(base * rush_multiplier * center_bonus * platform_bonus)


def _compute_dwell_time(passenger_count: int, config: SimConfig) -> float:
    """Dwell suresi hesapla."""
    raw = config.door_time + passenger_count * config.per_passenger_time
    return max(config.min_dwell_time, min(config.max_dwell_time, raw))


def _compute_realistic_dwell(
    stop: LinearStop,
    config: SimConfig,
    is_rush_hour: bool,
    rng: np.random.Generator,
    use_fixed_dwell: bool = False,
    fixed_dwell_seconds: float = 15.0,
    demand_profile=None,
    current_hour: float = 8.0,
) -> float:
    """
    Gerçekçi stokastik dwell süresi (15-30 saniye aralığında).
    """
    if use_fixed_dwell:
        return fixed_dwell_seconds

    passenger_count = _compute_passenger_load(
        stop, is_rush_hour, rng,
        demand_profile=demand_profile,
        current_hour=current_hour,
    )
    base_dwell = _compute_dwell_time(passenger_count, config)

    if is_rush_hour:
        base_dwell *= 1.5

    extra = 0.0
    if rng.random() < 0.08:
        extra += rng.uniform(5.0, 10.0)
    if rng.random() < 0.05:
        extra += rng.uniform(3.0, 6.0)
    crowd_prob = 0.15 if is_rush_hour else 0.03
    if rng.random() < crowd_prob:
        extra += rng.uniform(2.0, 5.0)
    if rng.random() < 0.03:
        extra += rng.uniform(2.0, 4.0)

    total = base_dwell + extra
    return max(15.0, min(30.0, total))
