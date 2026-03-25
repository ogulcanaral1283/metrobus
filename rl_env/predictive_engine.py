"""
Predictive Lookahead Decision Engine
=====================================

Otobüs durağa yaklaşırken iki alternatif geleceği simüle eder:
  Senaryo A: Müdahale yok → bunching + kuyruk bekleme
  Senaryo B: Hız filtreleme → yavaşlayarak tam zamanında varış

Hangisi zaman açısından daha avantajlıysa o seçilir.

Phase 2 Güncellemeleri:
  - IDM mini-sim ile gerçek fizik tabanlı ETA
  - Sabit DECISION_DISTANCE kaldırıldı — her frame tüm otobüsler değerlendirilir
  - Ağırlıklı çoklu metrik skor karşılaştırma
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


# ============================================
# Sabitler
# ============================================

# Durağa yaklaşma frenleme mesafesi (metre) — config'den de alınabilir
DEFAULT_APPROACH_DISTANCE = 150.0

# Minimum filtrelen miş hız (m/s) — çok yavaş gitmek de trafik sorunlarına yol açar
V_MIN_FILTERED = 2.0

# Güvenlik tamponu: slot boşalma zamanına eklenen tampon (sn)
SLOT_CLEAR_BUFFER = 2.0

# Dwell süresi tahmin sabitleri
DWELL_BASE_NORMAL = 20.0     # Normal saatlerde ortalama dwell (sn)
DWELL_BASE_RUSH = 26.0       # Rush hour'da ortalama dwell (sn)
DWELL_DOOR_TIME = 1.0        # Kapı açılma süresi (sn)

# Ağırlıklı skor katsayıları
WEIGHT_TIME = 1.0             # Toplam süre ağırlığı (α)
WEIGHT_PASSENGER = 0.5        # Yolcu bekleme etkisi (β)
WEIGHT_HEADWAY = 0.3          # Headway bozulması (γ)
WEIGHT_ENERGY = 0.1           # Enerji maliyeti (δ)

# Otobüs uzunluğu (metre)
BUS_LENGTH = 15.0

# Slot arası boşluk (metre)
SLOT_GAP = 0.5

# IDM Mini-Sim sabitleri
IDM_DELTA = 4.0               # IDM üs parametresi
IDM_S0 = 2.0                  # Minimum mesafe (m)
IDM_T_HEADWAY = 1.5           # Güvenli zaman aralığı (s)
SIM_DT = 0.5                  # Mini-sim zaman adımı (s) — hızlı sim için kaba
SIM_MAX_STEPS = 600           # Max sim adımı = 300s


# ============================================
# Veri Yapıları
# ============================================

class Decision(str, Enum):
    """Predictive engine karar türleri."""
    NO_RISK = "NO_RISK"                    # Bunching riski yok, normal seyir
    SPEED_FILTER = "SPEED_FILTER"          # Hız filtreleme uygula
    BUNCHING_ACCEPT = "BUNCHING_ACCEPT"    # Bunching kabul et (daha hızlı)


@dataclass
class BusSnapshot:
    """Bir otobüsün anlık durumu (lookahead için)."""
    bus_id: int
    position: float         # metre pozisyonu
    speed: float            # m/s
    acceleration: float     # m/s²
    phase: str              # "cruising", "approaching", "stopped", ...
    next_stop_index: int    # hedef durak indexi
    dwell_remaining: float  # kalan dwell süresi (sn)
    holding_extra: float    # RL holding süresi (sn)


@dataclass
class StopInfo:
    """Durak bilgisi (lookahead için)."""
    index: int
    name: str
    position: float              # metre pozisyonu
    capacity: int                # max eşzamanlı otobüs (slot sayısı)
    platform_length: float       # platform uzunluğu (metre)


@dataclass
class ScenarioResult:
    """Bir senaryonun simülasyon sonucu."""
    total_time: float       # karar anından operasyon bitişine toplam süre
    arrival_time: float     # durağa varış süresi
    wait_time: float        # kuyruk bekleme süresi
    dwell_time: float       # yolcu operasyonu süresi
    feasible: bool          # fiziksel olarak gerçekleştirilebilir mi
    v_filtered: float       # filtrelenmiş hız (Senaryo B için)

    # Ek metrikler
    passenger_impact: float = 0.0   # yolcu bekleme etkisi
    headway_impact: float = 0.0     # headway bozulması
    energy_cost: float = 0.0        # enerji maliyeti (normalize)


@dataclass
class PredictiveDecision:
    """Predictive engine kararı."""
    decision: Decision
    v_target: float                 # hedef hız (m/s)
    score_a: float                  # Senaryo A skoru
    score_b: float                  # Senaryo B skoru
    scenario_a: Optional[ScenarioResult] = None
    scenario_b: Optional[ScenarioResult] = None
    time_saved: float = 0.0         # kazanılan süre (sn)
    debug: dict = field(default_factory=dict)


# ============================================
# ETA Hesaplama — IDM Kinematiği Dahil
# ============================================

def compute_eta(
    distance: float,
    current_speed: float,
    approach_distance: float = DEFAULT_APPROACH_DISTANCE,
    comfort_braking: float = 2.0,
) -> float:
    """
    Durağa tahmini varış süresi (sn) — analitik model (fallback).

    İki fazlı model:
      Faz 1: Serbest seyir (distance - approach_distance mesafe, current_speed hızla)
      Faz 2: Frenleme eğrisi (approach_distance mesafe, v→0)
    """
    if distance <= 0:
        return 0.0
    if current_speed <= 0.01:
        return float('inf')

    v_brake_entry = min(current_speed, math.sqrt(2.0 * comfort_braking * approach_distance))
    cruise_dist = max(0.0, distance - approach_distance)
    t_cruise = cruise_dist / current_speed
    t_brake = v_brake_entry / comfort_braking
    return t_cruise + t_brake


def compute_eta_idm_sim(
    distance: float,
    current_speed: float,
    target_speed: float,
    leader_distance: float = 9999.0,
    leader_speed: float = 14.0,
    a_max: float = 1.0,
    b_comfort: float = 2.0,
    stop_approach_dist: float = DEFAULT_APPROACH_DISTANCE,
) -> float:
    """
    IDM Mini-Sim ile ETA hesaplama — gerçek fizik adımları.

    Otobüsü IDM ile ilerletir, durağa yaklaştıkça hedef hızı düşürür,
    ve durağa varış zamanını hesaplar.

    Args:
        distance:           Durağa kalan mesafe (m)
        current_speed:      Mevcut hız (m/s)
        target_speed:       Hedef seyir hızı (m/s)
        leader_distance:    Öndeki araça mesafe (m)
        leader_speed:       Öndeki aracın hızı (m/s)
        a_max:              Max ivme (m/s²)
        b_comfort:          Konfor fren ivmesi (m/s²)
        stop_approach_dist: Durağa yaklaşma mesafesi (m)

    Returns:
        Tahmini varış süresi (sn)
    """
    if distance <= 0:
        return 0.0
    if current_speed <= 0.01 and target_speed <= 0.01:
        return float('inf')

    dt = SIM_DT
    pos = 0.0
    speed = current_speed
    time_elapsed = 0.0
    sqrt_ab = math.sqrt(a_max * b_comfort)

    for _ in range(SIM_MAX_STEPS):
        remaining = distance - pos
        if remaining <= 0:
            return time_elapsed

        # Hedef hız: durağa yaklaştıkça düşür
        if remaining < stop_approach_dist:
            # Yumuşak frenleme: karekök profili
            v_desired = max(0.5, target_speed * math.sqrt(remaining / stop_approach_dist))
        else:
            v_desired = target_speed

        # IDM ivme hesabı
        gap = min(remaining, leader_distance)
        delta_v = speed - leader_speed

        s_star = IDM_S0 + max(0, speed * IDM_T_HEADWAY + speed * delta_v / (2.0 * sqrt_ab))
        v_ratio = (speed / max(0.01, v_desired)) ** IDM_DELTA
        s_ratio = (s_star / max(0.1, gap)) ** 2

        accel = a_max * (1.0 - v_ratio - s_ratio)
        accel = max(-b_comfort * 2.0, min(a_max, accel))  # emergency fren limit

        # Pozisyon ve hız güncelle
        speed = max(0.0, speed + accel * dt)
        ds = max(0.0, speed * dt + 0.5 * accel * dt * dt)
        pos += ds
        time_elapsed += dt

    # Max step'e ulaşıldı — tahmini varış
    return time_elapsed


def compute_all_etas(
    buses: List[BusSnapshot],
    stop: StopInfo,
    approach_distance: float = DEFAULT_APPROACH_DISTANCE,
    comfort_braking: float = 2.0,
    max_speed: float = 14.0,
    use_idm_sim: bool = True,
) -> dict[int, float]:
    """
    Tüm otobüslerin durağa ETA'sını hesapla.
    use_idm_sim=True ise IDM mini-sim kullanır (daha doğru),
    False ise analitik formül kullanır (daha hızlı).

    Returns:
        {bus_id: eta_seconds} dict
    """
    # Öndeki araca mesafe hesabı için pozisyona göre sırala
    sorted_buses = sorted(buses, key=lambda b: b.position)

    etas = {}
    for idx, bus in enumerate(sorted_buses):
        dist = stop.position - bus.position
        if dist <= 0:
            etas[bus.bus_id] = 0.0
            continue

        if use_idm_sim:
            # Öndeki aracı bul
            leader_dist = 9999.0
            leader_spd = max_speed
            if idx < len(sorted_buses) - 1:
                next_bus = sorted_buses[idx + 1]
                leader_dist = next_bus.position - bus.position - BUS_LENGTH
                leader_spd = next_bus.speed

            etas[bus.bus_id] = compute_eta_idm_sim(
                dist, bus.speed, max_speed,
                leader_distance=max(0.1, leader_dist),
                leader_speed=leader_spd,
                b_comfort=comfort_braking,
                stop_approach_dist=approach_distance,
            )
        else:
            etas[bus.bus_id] = compute_eta(
                dist, bus.speed, approach_distance, comfort_braking
            )
    return etas


# ============================================
# Dwell Süresi Tahmini
# ============================================

def estimate_dwell(
    bus: BusSnapshot,
    stop: StopInfo,
    is_rush_hour: bool = False,
) -> float:
    """
    Deterministik dwell süresi tahmini (lookahead için).

    Returns:
        Tahmini dwell süresi (sn)
    """
    base = DWELL_BASE_RUSH if is_rush_hour else DWELL_BASE_NORMAL
    return DWELL_DOOR_TIME + base + bus.holding_extra


# ============================================
# Bunching Riski Tespiti
# ============================================

def detect_bunching_risk(
    bus_k: BusSnapshot,
    all_buses: List[BusSnapshot],
    stop: StopInfo,
    approach_distance: float = DEFAULT_APPROACH_DISTANCE,
    comfort_braking: float = 2.0,
) -> Tuple[bool, int, dict[int, float]]:
    """
    Otobüs k için bunching riski tespiti.

    Args:
        bus_k:      Değerlendirilen otobüs
        all_buses:  Tüm otobüsler
        stop:       Hedef durak
    
    Returns:
        (risk_var, rank_k, etas)
        - risk_var: True ise bunching riski var
        - rank_k:   Bus k'nın varış sıralamasındaki yeri (1-indexed)
        - etas:     Tüm ETA'lar
    """
    # Sadece bu durağa yönelen ve henüz geçmemiş otobüsleri filtrele
    relevant_buses = [
        b for b in all_buses
        if b.next_stop_index == stop.index
        and b.position < stop.position
        and b.phase in ("cruising", "approaching", "queued", "docking")
    ]

    # Durağa zaten vardığını kabul et: stopped/doorsClosed/blocked fazındaki araçlar
    at_station = [
        b for b in all_buses
        if b.next_stop_index == stop.index
        and b.phase in ("stopped", "doorsClosed", "blocked")
    ]

    etas = compute_all_etas(relevant_buses, stop, approach_distance, comfort_braking)

    # Sıralama: ETA'ya göre küçükten büyüğe
    sorted_arrivals = sorted(etas.items(), key=lambda x: x[1])

    # Bus k'nın sırası
    rank_k = -1
    for rank, (bid, _) in enumerate(sorted_arrivals, start=1):
        if bid == bus_k.bus_id:
            rank_k = rank
            break

    if rank_k == -1:
        # Bus k bu durağa yönelmiyor
        return False, 0, etas

    # Durakta zaten olan araç sayısını da hesaba kat
    occupied_slots = len(at_station)
    effective_capacity = max(0, stop.capacity - occupied_slots)

    # Bunching riski: rank > kalan kapasite
    has_risk = rank_k > effective_capacity

    return has_risk, rank_k, etas


# ============================================
# Senaryo A: Müdahalesiz (Bunching Kabul)
# ============================================

def simulate_scenario_a(
    bus_k: BusSnapshot,
    all_buses: List[BusSnapshot],
    stop: StopInfo,
    etas: dict[int, float],
    rank_k: int,
    is_rush_hour: bool = False,
    approach_distance: float = DEFAULT_APPROACH_DISTANCE,
    comfort_braking: float = 2.0,
) -> ScenarioResult:
    """
    Senaryo A: Hiçbir müdahale olmadan ne olur?

    Otobüs mevcut hızıyla devam → durağa varır → slot doluysa bekler → 
    operasyon yapar → kalkar.

    T_A = ETA_k + W_k + τ_k
    """
    d_k = stop.position - bus_k.position
    if d_k <= 0:
        return ScenarioResult(
            total_time=0.0, arrival_time=0.0, wait_time=0.0,
            dwell_time=0.0, feasible=True, v_filtered=bus_k.speed,
        )

    # Bus k'nın varış zamanı
    eta_k = etas.get(bus_k.bus_id, compute_eta(d_k, bus_k.speed, approach_distance, comfort_braking))

    # Önden varış sırasına göre ilk C otobüsü bul
    # (bus_k hariç, durağa daha önce varacaklar)
    arrivals_before_k = [
        (bid, eta) for bid, eta in etas.items()
        if eta < eta_k and bid != bus_k.bus_id
    ]
    arrivals_before_k.sort(key=lambda x: x[1])

    # Duraktaki mevcut otobüslerin operasyon bitiş zamanları
    at_station = [
        b for b in all_buses
        if b.next_stop_index == stop.index
        and b.phase in ("stopped", "doorsClosed", "blocked")
    ]

    # Tüm slot boşalma zamanları
    clear_times: List[float] = []

    # Durağa gelmiş araçların kalan dwell süreleri
    for bus_at in at_station:
        clear_times.append(bus_at.dwell_remaining)

    # Henüz varmamış ama bus_k'dan önce varacak olanlar
    for bid, eta in arrivals_before_k:
        bus_j = next((b for b in all_buses if b.bus_id == bid), None)
        if bus_j:
            dwell_j = estimate_dwell(bus_j, stop, is_rush_hour)
            clear_times.append(eta + dwell_j)

    clear_times.sort()

    # Bus k için slot ne zaman boşalır?
    # rank_k > capacity demek ki, (rank_k - capacity) numaralı slotun
    # boşalmasını beklemesi gerekiyor
    wait_index = rank_k - stop.capacity - 1

    if wait_index < 0 or wait_index >= len(clear_times):
        # Bekleme gerekmez veya hesaplanamaz
        wait_time = 0.0
    else:
        slot_clear_time = clear_times[wait_index] + SLOT_CLEAR_BUFFER
        wait_time = max(0.0, slot_clear_time - eta_k)

    # Dwell süresi
    dwell_k = estimate_dwell(bus_k, stop, is_rush_hour)

    # Toplam süre: varış + bekleme + operasyon
    total_time = eta_k + wait_time + dwell_k

    # Ek metrikler
    passenger_impact = _compute_passenger_impact_a(bus_k, wait_time)
    headway_impact = _compute_headway_impact_a(bus_k, all_buses, eta_k, wait_time)
    energy_cost = _compute_energy_cost_a(bus_k)

    return ScenarioResult(
        total_time=total_time,
        arrival_time=eta_k,
        wait_time=wait_time,
        dwell_time=dwell_k,
        feasible=True,
        v_filtered=bus_k.speed,
        passenger_impact=passenger_impact,
        headway_impact=headway_impact,
        energy_cost=energy_cost,
    )


# ============================================
# Senaryo B: Hız Filtreleme
# ============================================

def simulate_scenario_b(
    bus_k: BusSnapshot,
    all_buses: List[BusSnapshot],
    stop: StopInfo,
    etas: dict[int, float],
    rank_k: int,
    is_rush_hour: bool = False,
    approach_distance: float = DEFAULT_APPROACH_DISTANCE,
    comfort_braking: float = 2.0,
    max_speed: float = 14.0,
) -> ScenarioResult:
    """
    Senaryo B: Hız filtreleme ile tam zamanında varış.

    Otobüs yavaşlatılarak, tam slot boşaldığı anda durağa varması 
    sağlanır → kuyruk bekleme yok → direkt operasyon.

    v_filtered çözümü: İkinci dereceden kinematik denklem
    """
    d_k = stop.position - bus_k.position
    if d_k <= 0:
        return ScenarioResult(
            total_time=0.0, arrival_time=0.0, wait_time=0.0,
            dwell_time=0.0, feasible=True, v_filtered=bus_k.speed,
        )

    # Hedef varış zamanı — ilgili slotun boşalma zamanı
    # (Senaryo A ile aynı slot hesabı)
    arrivals_before_k = [
        (bid, eta) for bid, eta in etas.items()
        if eta < etas.get(bus_k.bus_id, float('inf')) and bid != bus_k.bus_id
    ]
    arrivals_before_k.sort(key=lambda x: x[1])

    at_station = [
        b for b in all_buses
        if b.next_stop_index == stop.index
        and b.phase in ("stopped", "doorsClosed", "blocked")
    ]

    clear_times: List[float] = []

    for bus_at in at_station:
        clear_times.append(bus_at.dwell_remaining)

    for bid, eta in arrivals_before_k:
        bus_j = next((b for b in all_buses if b.bus_id == bid), None)
        if bus_j:
            dwell_j = estimate_dwell(bus_j, stop, is_rush_hour)
            clear_times.append(eta + dwell_j)

    clear_times.sort()

    wait_index = rank_k - stop.capacity - 1
    if wait_index < 0 or wait_index >= len(clear_times):
        # Bekleme gerekmez → Senaryo B anlamsız
        return ScenarioResult(
            total_time=float('inf'), arrival_time=0.0, wait_time=0.0,
            dwell_time=0.0, feasible=False, v_filtered=bus_k.speed,
        )

    t_target = clear_times[wait_index] + SLOT_CLEAR_BUFFER

    # t_target çok küçükse (zaten geç kalınmış) → B geçersiz
    if t_target <= 0:
        return ScenarioResult(
            total_time=float('inf'), arrival_time=0.0, wait_time=0.0,
            dwell_time=0.0, feasible=False, v_filtered=bus_k.speed,
        )

    # --- Kinematik v_filtered çözümü ---
    #
    # İki fazlı model:
    #   Seyir: (d_k - D_approach) metre, v_f hızla
    #   Frenleme: D_approach mesafe, v_f → 0
    #
    # t_target = (d_k - D_approach) / v_f + v_f / b_comfort
    #
    # İkinci derece denklem:
    #   v_f² / b - v_f · t_target + (d_k - D_approach) = 0
    #
    # Çözüm (küçük kök — en düşük hız):
    #   v_f = (b·t - sqrt((b·t)² - 4·b·(d-D))) / 2

    d_cruise = max(0.0, d_k - approach_distance)

    if d_cruise <= 0:
        # Zaten frenleme bölgesinde — basit hız hesabı
        v_filtered = d_k / t_target if t_target > 0 else bus_k.speed
    else:
        bt = comfort_braking * t_target
        discriminant = bt * bt - 4.0 * comfort_braking * d_cruise

        if discriminant < 0:
            # Fiziksel olarak imkansız — B geçersiz
            return ScenarioResult(
                total_time=float('inf'), arrival_time=0.0, wait_time=0.0,
                dwell_time=0.0, feasible=False, v_filtered=bus_k.speed,
            )

        v_filtered = (bt - math.sqrt(discriminant)) / 2.0

    # Güvenlik sınırlamaları
    v_filtered = max(V_MIN_FILTERED, min(max_speed, v_filtered))

    # Gerçek varış süresi (filtrelenmiş hızla)
    actual_arrival = compute_eta(d_k, v_filtered, approach_distance, comfort_braking)

    # Dwell süresi
    dwell_k = estimate_dwell(bus_k, stop, is_rush_hour)

    # Toplam süre: varış + operasyon (bekleme yok!)
    total_time = actual_arrival + dwell_k

    # Ek metrikler
    passenger_impact = _compute_passenger_impact_b(bus_k, d_k, v_filtered)
    headway_impact = _compute_headway_impact_b(bus_k, all_buses, v_filtered)
    energy_cost = _compute_energy_cost_b(bus_k, v_filtered)

    return ScenarioResult(
        total_time=total_time,
        arrival_time=actual_arrival,
        wait_time=0.0,  # bekleme yok!
        dwell_time=dwell_k,
        feasible=True,
        v_filtered=v_filtered,
        passenger_impact=passenger_impact,
        headway_impact=headway_impact,
        energy_cost=energy_cost,
    )


# ============================================
# Ağırlıklı Skor Hesaplama
# ============================================

def compute_weighted_score(result: ScenarioResult) -> float:
    """
    Score = α·T + β·P + γ·H + δ·E

    Düşük skor = daha iyi senaryo.
    """
    if not result.feasible:
        return float('inf')

    return (
        WEIGHT_TIME * result.total_time
        + WEIGHT_PASSENGER * result.passenger_impact
        + WEIGHT_HEADWAY * result.headway_impact
        + WEIGHT_ENERGY * result.energy_cost
    )


# ============================================
# Ek Metrik Hesaplamaları
# ============================================

def _compute_passenger_impact_a(bus_k: BusSnapshot, wait_time: float) -> float:
    """
    Senaryo A — yolcu bekleme etkisi.
    Otobüs kuyrukta beklerken sonraki durağın yolcuları da bekler.
    Basit tahmin: wait_time * ortalama yolcu varış oranı.
    """
    # λ ≈ 0.5 kişi/dakika ortalama
    passenger_arrival_rate = 0.5 / 60.0  # kişi/saniye
    return wait_time * passenger_arrival_rate


def _compute_passenger_impact_b(
    bus_k: BusSnapshot, distance: float, v_filtered: float,
) -> float:
    """
    Senaryo B — yolcu bekleme etkisi.
    Otobüs yavaş gidiyor, sonraki durağa geç varıyor.
    """
    if bus_k.speed < 0.01 or v_filtered < 0.01:
        return 0.0

    # Gecikme = yavaş süre - normal süre
    normal_time = distance / bus_k.speed
    slow_time = distance / v_filtered
    delay = max(0.0, slow_time - normal_time)

    passenger_arrival_rate = 0.5 / 60.0
    return delay * passenger_arrival_rate


def _compute_headway_impact_a(
    bus_k: BusSnapshot,
    all_buses: List[BusSnapshot],
    arrival_time: float,
    wait_time: float,
) -> float:
    """
    Senaryo A — headway bozulması.
    Bunching sonrası arkadaki araçla headway düşer.
    """
    # Arkadaki aracı bul
    follower = None
    for bus in all_buses:
        if bus.position < bus_k.position and bus.bus_id != bus_k.bus_id:
            if follower is None or bus.position > follower.position:
                follower = bus

    if follower is None:
        return 0.0

    # İdeal headway (120sn varsayılan)
    ideal_headway = 120.0

    # Otobüs durağa varıp beklerken, arkadaki araç yaklaşır
    gap = bus_k.position - follower.position
    if follower.speed > 0.01:
        headway = gap / follower.speed
    else:
        headway = ideal_headway  # durmuş araç, headway sabit

    # Bekleme süresi boyunca headway daralır
    effective_headway = max(0.0, headway - wait_time)
    return max(0.0, ideal_headway - effective_headway)


def _compute_headway_impact_b(
    bus_k: BusSnapshot,
    all_buses: List[BusSnapshot],
    v_filtered: float,
) -> float:
    """
    Senaryo B — headway bozulması.
    Hız filtreleme ile arkadaki aracın headway'i korunur.
    """
    follower = None
    for bus in all_buses:
        if bus.position < bus_k.position and bus.bus_id != bus_k.bus_id:
            if follower is None or bus.position > follower.position:
                follower = bus

    if follower is None:
        return 0.0

    ideal_headway = 120.0
    gap = bus_k.position - follower.position

    if v_filtered > 0.01:
        projected_headway = gap / v_filtered
    else:
        projected_headway = ideal_headway

    return abs(ideal_headway - projected_headway)


def _compute_energy_cost_a(bus_k: BusSnapshot) -> float:
    """
    Senaryo A — enerji maliyeti (normalize).
    Tam hız → tam dur → tekrar ivmelen.
    E_A = ½mv² + ½mv_depart² (v_depart ≈ 5 m/s varsayım)
    """
    v_depart = 5.0
    # m=1 olarak normalize (karşılaştırmalı)
    energy = 0.5 * bus_k.speed ** 2 + 0.5 * v_depart ** 2
    v_max = 14.0
    return energy / (v_max ** 2)  # [0, 1] normalize


def _compute_energy_cost_b(bus_k: BusSnapshot, v_filtered: float) -> float:
    """
    Senaryo B — enerji maliyeti (normalize).
    Yavaş seyir → daha az fren enerjisi.
    E_B = ½m(v-v_f)² + ½mv_depart²
    """
    v_depart = 5.0
    energy = 0.5 * (bus_k.speed - v_filtered) ** 2 + 0.5 * v_depart ** 2
    v_max = 14.0
    return energy / (v_max ** 2)


# ============================================
# Ana Karar Fonksiyonu
# ============================================

def evaluate_decision(
    bus_k: BusSnapshot,
    all_buses: List[BusSnapshot],
    stop: StopInfo,
    is_rush_hour: bool = False,
    approach_distance: float = DEFAULT_APPROACH_DISTANCE,
    comfort_braking: float = 2.0,
    max_speed: float = 14.0,
) -> PredictiveDecision:
    """
    Otobüs k için bunching vs hız filtreleme kararını ver.

    Returns:
        PredictiveDecision — karar, hedef hız, skorlar, detaylar
    """
    d_k = stop.position - bus_k.position

    # Mesafe kontrolü: durağa gitmeyen veya geçmiş araçları atla
    if d_k <= 0:
        return PredictiveDecision(
            decision=Decision.NO_RISK,
            v_target=bus_k.speed,
            score_a=0.0, score_b=0.0,
        )

    # 2. Bunching riski tespiti
    has_risk, rank_k, etas = detect_bunching_risk(
        bus_k, all_buses, stop, approach_distance, comfort_braking
    )

    if not has_risk:
        return PredictiveDecision(
            decision=Decision.NO_RISK,
            v_target=bus_k.speed,
            score_a=0.0, score_b=0.0,
            debug={"rank": rank_k, "capacity": stop.capacity},
        )

    # 3. Senaryo A simüle et
    result_a = simulate_scenario_a(
        bus_k, all_buses, stop, etas, rank_k,
        is_rush_hour, approach_distance, comfort_braking,
    )

    # 4. Senaryo B simüle et
    result_b = simulate_scenario_b(
        bus_k, all_buses, stop, etas, rank_k,
        is_rush_hour, approach_distance, comfort_braking, max_speed,
    )

    # 5. Skorları hesapla
    score_a = compute_weighted_score(result_a)
    score_b = compute_weighted_score(result_b)

    # 6. Karar
    time_saved = result_a.total_time - result_b.total_time

    if result_b.feasible and score_b < score_a:
        decision = Decision.SPEED_FILTER
        v_target = result_b.v_filtered
    else:
        decision = Decision.BUNCHING_ACCEPT
        v_target = bus_k.speed

    return PredictiveDecision(
        decision=decision,
        v_target=v_target,
        score_a=score_a,
        score_b=score_b,
        scenario_a=result_a,
        scenario_b=result_b,
        time_saved=time_saved,
        debug={
            "rank_k": rank_k,
            "capacity": stop.capacity,
            "d_k": d_k,
            "eta_k": etas.get(bus_k.bus_id, 0.0),
            "bus_speed": bus_k.speed,
            "v_filtered": result_b.v_filtered if result_b.feasible else None,
            "speed_reduction_pct": (
                (1.0 - result_b.v_filtered / bus_k.speed) * 100.0
                if result_b.feasible and bus_k.speed > 0.01
                else 0.0
            ),
        },
    )


# ============================================
# Slot Pozisyon Hesaplama
# ============================================

def compute_target_slot_position(
    stop: StopInfo,
    occupied_slots: List[int],
) -> Tuple[int, float]:
    """
    Boş slotlardan en öndekini seç ve pozisyonunu hesapla.

    Slot 1 (ön) = stop.position
    Slot j       = stop.position - (j-1) * (BUS_LENGTH + SLOT_GAP)

    Returns:
        (slot_number, meter_position)
    """
    for slot_j in range(1, stop.capacity + 1):
        if slot_j not in occupied_slots:
            position = stop.position - (slot_j - 1) * (BUS_LENGTH + SLOT_GAP)
            return slot_j, position

    # Tüm slotlar dolu — peron dışında kal
    outside_pos = stop.position - stop.capacity * (BUS_LENGTH + SLOT_GAP) - 5.0
    return -1, outside_pos


# ============================================
# Toplu Değerlendirme (Tüm Otobüsler)
# ============================================

def evaluate_all_buses(
    all_buses: List[BusSnapshot],
    stops: List[StopInfo],
    is_rush_hour: bool = False,
    approach_distance: float = DEFAULT_APPROACH_DISTANCE,
    comfort_braking: float = 2.0,
    max_speed: float = 14.0,
) -> dict[int, PredictiveDecision]:
    """
    Tüm otobüsleri değerlendir.

    Returns:
        {bus_id: PredictiveDecision} dict
    """
    decisions: dict[int, PredictiveDecision] = {}

    for bus_k in all_buses:
        # Sadece cruising ve approaching fazları — diğerleri zaten durakta
        if bus_k.phase not in ("cruising", "approaching"):
            decisions[bus_k.bus_id] = PredictiveDecision(
                decision=Decision.NO_RISK,
                v_target=bus_k.speed,
                score_a=0.0, score_b=0.0,
            )
            continue

        # Hedef durağı bul
        target_stop = None
        for s in stops:
            if s.index == bus_k.next_stop_index:
                target_stop = s
                break

        if target_stop is None:
            decisions[bus_k.bus_id] = PredictiveDecision(
                decision=Decision.NO_RISK,
                v_target=bus_k.speed,
                score_a=0.0, score_b=0.0,
            )
            continue

        decisions[bus_k.bus_id] = evaluate_decision(
            bus_k, all_buses, target_stop,
            is_rush_hour, approach_distance, comfort_braking, max_speed,
        )

    return decisions
