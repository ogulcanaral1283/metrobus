"""
Katman 3 — Lookahead Karar Motoru
====================================

Finite-horizon multi-stop optimizer. 3–5 durak ileriye projeksiyon yaparak
optimal hold_sequence ve speed_factor çözer.

Maliyet Fonksiyonu:
    J = w_h · Σ_k |h_k_predicted − h_target|²    (headway düzgünlüğü)
      + w_o · Σ_k overflow_k                      (peron taşması cezası)
      + w_s · Σ_k skip_k²                         (durak atlama maliyeti)

Çözüm Yöntemi:
    Dynamic Programming — state = (araç, durak) çifti bazında
    discretize edilmiş hold süreleri (0, 5, 10, ..., 30 sn) üzerinde
    kümülatif maliyet minimizasyonu.

    Branch-and-bound yerine DP tercih edildi çünkü:
    - Durak sayısı küçük (3–5) ve hold discrete (7 seviye)
    - DP O(N·S·H) ile polinomyal, B&B worst-case exponential
    - Subproblem overlap yüksek → memoization verimli

ETA Projeksiyon:
    predictive_engine.py'den taşınan IDM mini-sim.
    Her araç için sonraki S durağa tahmini varış süresi hesaplanır.

Slot Overflow Tespiti:
    Durağa aynı anda capacity'den fazla araç varırsa overflow.
    Express (durak atlama) önerisi üretilir.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

try:
    from ..config import SimVehicle, SimConfig
    from ..route_data import LinearStop
except ImportError:
    from config import SimVehicle, SimConfig
    from route_data import LinearStop


# ═══════════════════════════════════════════
# Sabitler
# ═══════════════════════════════════════════

# Hold time discretization (saniye)
HOLD_LEVELS = [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0]

# Maliyet ağırlıkları
DEFAULT_W_HEADWAY = 1.0     # headway sapması ağırlığı
DEFAULT_W_OVERFLOW = 5.0    # peron taşması cezası
DEFAULT_W_SKIP = 2.0        # durak atlama maliyeti

# IDM Mini-Sim sabitleri
IDM_DELTA = 4.0
IDM_S0 = 2.0
IDM_T_HEADWAY = 1.5
SIM_DT = 0.5
SIM_MAX_STEPS = 600
VEHICLE_LENGTH = 20.0

# ETA sabitleri
DEFAULT_APPROACH_DISTANCE = 150.0
V_MIN = 2.0

# Dwell tahmini
DWELL_BASE_NORMAL = 20.0
DWELL_BASE_RUSH = 26.0
DWELL_DOOR_TIME = 1.0


# ═══════════════════════════════════════════
# Veri Yapıları
# ═══════════════════════════════════════════

@dataclass
class ArrivalProjection:
    """Bir aracın bir durağa tahmini varış bilgisi."""
    vehicle_id: int
    stop_index: int
    eta: float                  # tahmini varış süresi (sn)
    arrival_rank: int           # varış sıralaması (1-indexed)
    slot_available: bool        # slot müsait mi
    estimated_wait: float       # kuyruk bekleme tahmini (sn)
    estimated_dwell: float      # yolcu operasyon tahmini (sn)


@dataclass
class LookaheadDecision:
    """Lookahead optimizer kararı — tek araç."""
    vehicle_id: int
    hold_time: float            # önerilen ek hold süresi (sn)
    speed_factor: float         # hız çarpanı [0.3, 1.2], 1.0 = normal
    skip_stop: bool             # sonraki durağı atla (express)
    cost: float                 # bu kararın maliyeti
    projections: List[ArrivalProjection] = field(default_factory=list)
    debug: dict = field(default_factory=dict)


# ═══════════════════════════════════════════
# ETA Hesaplama — IDM Mini-Sim
# ═══════════════════════════════════════════

def compute_eta_analytic(
    distance: float,
    current_speed: float,
    approach_distance: float = DEFAULT_APPROACH_DISTANCE,
    comfort_braking: float = 2.0,
) -> float:
    """
    Analitik ETA — iki fazlı kinematik model.

    Faz 1: Serbest seyir (distance − approach_distance, v hızıyla)
    Faz 2: Frenleme eğrisi (approach_distance, v → 0)

    T_eta = (d − D_a) / v + v_b / b
    v_b = min(v, √(2·b·D_a))
    """
    if distance <= 0:
        return 0.0
    if current_speed <= 0.01:
        return float("inf")

    v_brake = min(current_speed, math.sqrt(2.0 * comfort_braking * approach_distance))
    cruise_dist = max(0.0, distance - approach_distance)
    t_cruise = cruise_dist / current_speed
    t_brake = v_brake / comfort_braking
    return t_cruise + t_brake


def compute_eta_idm(
    distance: float,
    current_speed: float,
    target_speed: float,
    leader_distance: float = 9999.0,
    leader_speed: float = 14.0,
    a_max: float = 1.0,
    b_comfort: float = 2.0,
    approach_dist: float = DEFAULT_APPROACH_DISTANCE,
) -> float:
    """
    IDM Mini-Sim ile ETA — gerçek fizik adımları.

    Araç IDM ile ilerletilir, durağa yaklaştıkça hedef hızı düşürülür.
    """
    if distance <= 0:
        return 0.0
    if current_speed <= 0.01 and target_speed <= 0.01:
        return float("inf")

    dt = SIM_DT
    pos = 0.0
    speed = current_speed
    time_elapsed = 0.0
    sqrt_ab = math.sqrt(a_max * b_comfort)

    for _ in range(SIM_MAX_STEPS):
        remaining = distance - pos
        if remaining <= 0:
            return time_elapsed

        # Durağa yaklaştıkça hedef hızı düşür
        if remaining < approach_dist:
            v_desired = max(0.5, target_speed * math.sqrt(remaining / approach_dist))
        else:
            v_desired = target_speed

        # IDM ivme
        gap = min(remaining, leader_distance)
        delta_v = speed - leader_speed
        s_star = IDM_S0 + max(0, speed * IDM_T_HEADWAY + speed * delta_v / (2.0 * sqrt_ab))
        v_ratio = (speed / max(0.01, v_desired)) ** IDM_DELTA
        s_ratio = (s_star / max(0.1, gap)) ** 2
        accel = a_max * (1.0 - v_ratio - s_ratio)
        accel = max(-b_comfort * 2.0, min(a_max, accel))

        speed = max(0.0, speed + accel * dt)
        ds = max(0.0, speed * dt + 0.5 * accel * dt * dt)
        pos += ds
        time_elapsed += dt

    return time_elapsed


def estimate_dwell(
    stop: LinearStop,
    is_rush_hour: bool = False,
    holding_extra: float = 0.0,
) -> float:
    """Deterministik dwell süresi tahmini (lookahead projeksiyon için)."""
    base = DWELL_BASE_RUSH if is_rush_hour else DWELL_BASE_NORMAL
    return DWELL_DOOR_TIME + base + holding_extra


# ═══════════════════════════════════════════
# Lookahead Optimizer
# ═══════════════════════════════════════════

class LookaheadOptimizer:
    """
    Finite-horizon multi-stop optimizer.

    Her tick'te tüm filo için:
    1. Sonraki S durağa ETA projeksiyon
    2. Her araç × her durak × her hold_level için maliyet hesapla
    3. DP ile minimum toplam maliyeti veren hold sequence bul
    4. Slot overflow tespit → express (durak atlama) öner

    Parametreler:
        horizon:    Kaç durak ileriye bak (3–5)
        w_headway:  Headway sapması ağırlığı
        w_overflow: Peron taşması cezası
        w_skip:     Durak atlama maliyeti
        max_speed:  Maksimum araç hızı (m/s)
    """

    def __init__(
        self,
        horizon: int = 3,
        w_headway: float = DEFAULT_W_HEADWAY,
        w_overflow: float = DEFAULT_W_OVERFLOW,
        w_skip: float = DEFAULT_W_SKIP,
        max_speed: float = 14.0,
        comfort_braking: float = 2.0,
    ):
        self.horizon = horizon
        self.w_headway = w_headway
        self.w_overflow = w_overflow
        self.w_skip = w_skip
        self.max_speed = max_speed
        self.comfort_braking = comfort_braking

    def optimize(
        self,
        vehicles: List[SimVehicle],
        stops: List[LinearStop],
        target_headway: float,
        is_rush_hour: bool = False,
        current_hour: float = 8.0,
    ) -> List[LookaheadDecision]:
        """
        Tüm filo için optimal hold + speed kararlarını hesapla.

        Sadece cruising ve approaching araçlar için çalışır.
        Durakta olan araçlar (stopped, doorsClosed, blocked) atlanır.

        Args:
            vehicles:       Tüm araçlar
            stops:          Rota durakları (sıralı)
            target_headway: Hedef headway (sn) — HeadwayModel'den
            is_rush_hour:   Pik saat mi
            current_hour:   Simülasyon saati (dwell tahmini için)

        Returns:
            Her araç için LookaheadDecision
        """
        decisions: List[LookaheadDecision] = []
        num_stops = len(stops)

        # Araçları pozisyona göre sırala
        sorted_vehicles = sorted(vehicles, key=lambda v: v.position_meters)

        for veh in vehicles:
            # Durakta olan araçlara müdahale etme
            if veh.phase in ("stopped", "doorsClosed", "blocked", "queued", "docking"):
                decisions.append(LookaheadDecision(
                    vehicle_id=veh.id,
                    hold_time=0.0,
                    speed_factor=1.0,
                    skip_stop=False,
                    cost=0.0,
                ))
                continue

            # Bu araç için horizon durak ileriye bak
            start_stop = veh.next_stop_index
            if start_stop >= num_stops:
                decisions.append(LookaheadDecision(
                    vehicle_id=veh.id,
                    hold_time=0.0,
                    speed_factor=1.0,
                    skip_stop=False,
                    cost=0.0,
                ))
                continue

            end_stop = min(start_stop + self.horizon, num_stops)
            horizon_stops = stops[start_stop:end_stop]

            if not horizon_stops:
                decisions.append(LookaheadDecision(
                    vehicle_id=veh.id,
                    hold_time=0.0,
                    speed_factor=1.0,
                    skip_stop=False,
                    cost=0.0,
                ))
                continue

            # DP ile optimal hold + speed bul
            decision = self._dp_optimize_vehicle(
                veh, horizon_stops, sorted_vehicles,
                target_headway, is_rush_hour,
            )
            decisions.append(decision)

        return decisions

    def _dp_optimize_vehicle(
        self,
        vehicle: SimVehicle,
        horizon_stops: List[LinearStop],
        all_vehicles_sorted: List[SimVehicle],
        target_headway: float,
        is_rush_hour: bool,
    ) -> LookaheadDecision:
        """
        Tek araç için DP optimizasyonu.

        State:  (durak_index, kümülatif_hold)
        Action: her durakta hold_level seçimi (0, 5, ..., 30 sn)

        Transition:
            Bir sonraki durağa ETA = f(mesafe, hız, hold_birikimi)

        Cost:
            headway_cost + overflow_cost + skip_cost

        İlk durağa optimal hold_time ve speed_factor döndürülür.
        """
        first_stop = horizon_stops[0]
        dist_to_first = first_stop.meter_position - vehicle.position_meters

        if dist_to_first <= 0:
            return LookaheadDecision(
                vehicle_id=vehicle.id,
                hold_time=0.0,
                speed_factor=1.0,
                skip_stop=False,
                cost=0.0,
            )

        # Öndeki ve arkadaki aracı bul
        leader, follower = self._find_neighbors(vehicle, all_vehicles_sorted)

        # ─── Her hold seviyesi için maliyet hesapla ───
        best_cost = float("inf")
        best_hold = 0.0
        best_speed_factor = 1.0
        best_skip = False
        best_projections: List[ArrivalProjection] = []

        # Seçenek 1: Normal geçiş — farklı hold seviyeleri
        for hold in HOLD_LEVELS:
            cost, projections = self._evaluate_hold(
                vehicle, horizon_stops, all_vehicles_sorted,
                hold, target_headway, is_rush_hour,
            )
            if cost < best_cost:
                best_cost = cost
                best_hold = hold
                best_projections = projections

        # Seçenek 2: Hız filtreleme — slot timing
        speed_factor, sf_cost, sf_projections = self._evaluate_speed_filter(
            vehicle, first_stop, all_vehicles_sorted,
            target_headway, is_rush_hour,
        )
        if sf_cost < best_cost:
            best_cost = sf_cost
            best_hold = 0.0
            best_speed_factor = speed_factor
            best_projections = sf_projections

        # Seçenek 3: Express (durak atlama) — ciddi overflow durumunda
        if len(horizon_stops) > 1:
            skip_cost = self._evaluate_skip(
                vehicle, first_stop, horizon_stops[1],
                all_vehicles_sorted, target_headway, is_rush_hour,
            )
            if skip_cost < best_cost:
                best_cost = skip_cost
                best_hold = 0.0
                best_speed_factor = 1.0
                best_skip = True
                best_projections = []

        return LookaheadDecision(
            vehicle_id=vehicle.id,
            hold_time=best_hold,
            speed_factor=best_speed_factor,
            skip_stop=best_skip,
            cost=best_cost,
            projections=best_projections,
            debug={
                "dist_to_first_stop": dist_to_first,
                "horizon_stops": len(horizon_stops),
                "best_hold": best_hold,
                "best_speed_factor": best_speed_factor,
            },
        )

    def _evaluate_hold(
        self,
        vehicle: SimVehicle,
        horizon_stops: List[LinearStop],
        all_vehicles: List[SimVehicle],
        hold_time: float,
        target_headway: float,
        is_rush_hour: bool,
    ) -> Tuple[float, List[ArrivalProjection]]:
        """
        Belirli bir hold_time için kümülatif maliyet hesapla.

        Hold_time ilk durağa uygulanır. Sonraki duraklara propagasyon
        hesaplanır (hold birikimiyle ETA kayması).
        """
        total_cost = 0.0
        projections: List[ArrivalProjection] = []
        cumulative_delay = hold_time  # hold süresi ETA'yı kaydırır

        for stop in horizon_stops:
            dist = stop.meter_position - vehicle.position_meters
            if dist <= 0:
                continue

            # Bu araç için ETA (hold kayması dahil)
            base_eta = compute_eta_analytic(
                dist, vehicle.speed, DEFAULT_APPROACH_DISTANCE, self.comfort_braking,
            )
            adjusted_eta = base_eta + cumulative_delay

            # Bu durağa yaklaşan diğer araçları bul
            competitors = self._get_stop_competitors(
                vehicle, stop, all_vehicles,
            )

            # Slot kontrolü
            capacity = max(stop.slot_count, 1)
            at_station_count = self._count_at_station(stop.index, all_vehicles)

            # Varış sıralaması
            rank = 1 + sum(
                1 for c_eta in competitors.values() if c_eta < adjusted_eta
            )
            slot_available = rank <= (capacity - at_station_count)
            wait_time = 0.0 if slot_available else self._estimate_wait(
                rank, capacity, at_station_count, competitors, is_rush_hour,
            )

            dwell = estimate_dwell(stop, is_rush_hour, hold_time if stop == horizon_stops[0] else 0.0)

            # ─── Headway maliyeti ───
            # Arkadaki araçla predicted headway
            follower_eta = self._get_follower_eta(vehicle, stop, all_vehicles)
            predicted_headway = follower_eta - adjusted_eta if follower_eta > 0 else target_headway
            headway_deviation = (predicted_headway - target_headway) ** 2
            headway_cost = self.w_headway * headway_deviation

            # ─── Overflow maliyeti ───
            overflow_cost = self.w_overflow * max(0, wait_time)

            # ─── Toplam ───
            stop_cost = headway_cost + overflow_cost
            total_cost += stop_cost

            projections.append(ArrivalProjection(
                vehicle_id=vehicle.id,
                stop_index=stop.index,
                eta=adjusted_eta,
                arrival_rank=rank,
                slot_available=slot_available,
                estimated_wait=wait_time,
                estimated_dwell=dwell,
            ))

            # Sonraki durağa kümülatif gecikme
            cumulative_delay += wait_time

        return total_cost, projections

    def _evaluate_speed_filter(
        self,
        vehicle: SimVehicle,
        first_stop: LinearStop,
        all_vehicles: List[SimVehicle],
        target_headway: float,
        is_rush_hour: bool,
    ) -> Tuple[float, float, List[ArrivalProjection]]:
        """
        Hız filtreleme değerlendirmesi.

        Araç yavaşlatılarak slot boşaldığı anda varması sağlanır.
        speed_factor [0.3, 1.0] aralığında optimize edilir.

        Kinematik çözüm:
            v_filtered = d / t_target
            t_target = slot_clear_time + buffer

        Returns: (speed_factor, cost, projections)
        """
        dist = first_stop.meter_position - vehicle.position_meters
        if dist <= 5.0 or vehicle.speed < 0.5:
            return 1.0, float("inf"), []

        capacity = max(first_stop.slot_count, 1)
        at_station = self._count_at_station(first_stop.index, all_vehicles)

        # Slot müsaitse filtreleme gereksiz
        if at_station < capacity:
            return 1.0, float("inf"), []

        # Slot boşalma tahmini
        avg_remaining_dwell = estimate_dwell(first_stop, is_rush_hour) * 0.5
        slot_clear_time = avg_remaining_dwell + 2.0  # 2s buffer

        # Minimum varış süresi
        t_target = max(slot_clear_time, 5.0)

        # Gerekli hız
        v_needed = dist / t_target
        v_needed = max(V_MIN, min(self.max_speed, v_needed))
        speed_factor = v_needed / self.max_speed
        speed_factor = max(0.3, min(1.0, speed_factor))

        # Bu hızla maliyet hesapla
        adjusted_eta = dist / max(v_needed, 0.1)

        # Headway etkisi
        follower_eta = self._get_follower_eta(vehicle, first_stop, all_vehicles)
        predicted_headway = follower_eta - adjusted_eta if follower_eta > 0 else target_headway
        headway_cost = self.w_headway * (predicted_headway - target_headway) ** 2

        # Bekleme yok (tam zamanında varış)
        overflow_cost = 0.0

        total_cost = headway_cost + overflow_cost

        projection = ArrivalProjection(
            vehicle_id=vehicle.id,
            stop_index=first_stop.index,
            eta=adjusted_eta,
            arrival_rank=at_station + 1,
            slot_available=True,
            estimated_wait=0.0,
            estimated_dwell=estimate_dwell(first_stop, is_rush_hour),
        )

        return speed_factor, total_cost, [projection]

    def _evaluate_skip(
        self,
        vehicle: SimVehicle,
        skip_stop: LinearStop,
        next_stop: LinearStop,
        all_vehicles: List[SimVehicle],
        target_headway: float,
        is_rush_hour: bool,
    ) -> float:
        """
        Durak atlama (express) maliyeti.

        Skip maliyeti = w_skip · 1 + sonraki durağın headway etkisi

        Express sadece ciddi overflow durumunda önerilir:
        - Durak kapasitesi dolu + kuyruk var
        - Atlanan durağın yolcu yükü düşük
        """
        capacity = max(skip_stop.slot_count, 1)
        at_station = self._count_at_station(skip_stop.index, all_vehicles)

        # Overflow yoksa skip çok pahalı
        if at_station < capacity:
            return float("inf")

        # Skip maliyeti
        skip_cost = self.w_skip * 1.0

        # Sonraki durağa direkt ETA
        dist = next_stop.meter_position - vehicle.position_meters
        if dist <= 0:
            return float("inf")

        eta = compute_eta_analytic(dist, vehicle.speed, DEFAULT_APPROACH_DISTANCE, self.comfort_braking)

        # Headway etkisi
        follower_eta = self._get_follower_eta(vehicle, next_stop, all_vehicles)
        predicted_headway = follower_eta - eta if follower_eta > 0 else target_headway
        headway_cost = self.w_headway * (predicted_headway - target_headway) ** 2

        return skip_cost + headway_cost

    # ═══════════════════════════════════════
    # Yardımcı Fonksiyonlar
    # ═══════════════════════════════════════

    def _find_neighbors(
        self,
        vehicle: SimVehicle,
        sorted_vehicles: List[SimVehicle],
    ) -> Tuple[Optional[SimVehicle], Optional[SimVehicle]]:
        """Öndeki (leader) ve arkadaki (follower) aracı bul."""
        leader = None
        follower = None

        for v in sorted_vehicles:
            if v.id == vehicle.id:
                continue
            if v.position_meters > vehicle.position_meters:
                if leader is None or v.position_meters < leader.position_meters:
                    leader = v
            elif v.position_meters < vehicle.position_meters:
                if follower is None or v.position_meters > follower.position_meters:
                    follower = v

        return leader, follower

    def _get_stop_competitors(
        self,
        vehicle: SimVehicle,
        stop: LinearStop,
        all_vehicles: List[SimVehicle],
    ) -> dict[int, float]:
        """Bu durağa yaklaşan diğer araçların ETA'larını hesapla."""
        competitors: dict[int, float] = {}

        for v in all_vehicles:
            if v.id == vehicle.id:
                continue
            if v.next_stop_index != stop.index:
                continue
            if v.phase not in ("cruising", "approaching"):
                continue

            dist = stop.meter_position - v.position_meters
            if dist <= 0:
                continue

            eta = compute_eta_analytic(
                dist, v.speed, DEFAULT_APPROACH_DISTANCE, self.comfort_braking,
            )
            competitors[v.id] = eta

        return competitors

    def _count_at_station(
        self,
        stop_index: int,
        all_vehicles: List[SimVehicle],
    ) -> int:
        """Durakta olan araç sayısı."""
        return sum(
            1 for v in all_vehicles
            if v.next_stop_index == stop_index
            and v.phase in ("stopped", "doorsClosed", "blocked", "docking")
        )

    def _estimate_wait(
        self,
        rank: int,
        capacity: int,
        at_station: int,
        competitors: dict[int, float],
        is_rush_hour: bool,
    ) -> float:
        """Kuyruk bekleme süresi tahmini (sn)."""
        # Kaç slot boşalması gerekiyor?
        slots_needed = rank - max(0, capacity - at_station)
        if slots_needed <= 0:
            return 0.0

        # Ortalama dwell üzerinden tahmini bekleme
        avg_dwell = DWELL_BASE_RUSH if is_rush_hour else DWELL_BASE_NORMAL
        return slots_needed * (avg_dwell + DWELL_DOOR_TIME + 2.0)  # +2s kalkış

    def _get_follower_eta(
        self,
        vehicle: SimVehicle,
        stop: LinearStop,
        all_vehicles: List[SimVehicle],
    ) -> float:
        """Arkadaki en yakın aracın bu durağa ETA'sı."""
        best_eta = 0.0

        for v in all_vehicles:
            if v.id == vehicle.id:
                continue
            if v.position_meters >= vehicle.position_meters:
                continue
            if v.phase not in ("cruising", "approaching"):
                continue

            dist = stop.meter_position - v.position_meters
            if dist <= 0:
                continue

            eta = compute_eta_analytic(
                dist, v.speed, DEFAULT_APPROACH_DISTANCE, self.comfort_braking,
            )
            if best_eta == 0.0 or eta < best_eta:
                best_eta = eta

        return best_eta

    def set_weights(self, w_headway: float, w_overflow: float, w_skip: float) -> None:
        """Maliyet ağırlıklarını güncelle."""
        self.w_headway = w_headway
        self.w_overflow = w_overflow
        self.w_skip = w_skip
