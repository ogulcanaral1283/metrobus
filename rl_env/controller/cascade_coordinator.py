"""
Aşama 4 — Cascade Koordinasyon (Çok-Duraklı Propagasyon)
==========================================================

Bir aracı Durak N için yavaşlatmak, Durak N+1, N+2, ... varışını etkiler.
Bu modül:
  1. Hız değişikliklerini sonraki duraklara yayar (cascade propagation)
  2. Yan etkileri tespit eder (yavaşlatma başka durakta taşmaya yol açar mı?)
  3. Çelişkili talepleri çözer (Durak 5: "yavaşla" vs Durak 6: "hızlan")
  4. Net en iyi speed_factor'ı belirler

Prensip:
    Lokal optimum ≠ Global optimum.
    Bir durağı kurtarmak için başka durağı bozmamak gerek.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Dict

try:
    from ..config import SimVehicle, SimConfig
    from ..route_data import LinearStop
    from ..station_fsm import compute_rear_free_slots
    from .station_arrival_scheduler import (
        StationArrivalScheduler, StationSchedule, ArrivalPlan, compute_eta,
        estimate_dwell, DEPARTURE_OVERHEAD, SLOT_BUFFER_SECONDS,
    )
except ImportError:
    from config import SimVehicle, SimConfig
    from route_data import LinearStop
    from station_fsm import compute_rear_free_slots
    from station_arrival_scheduler import (
        StationArrivalScheduler, StationSchedule, ArrivalPlan, compute_eta,
        estimate_dwell, DEPARTURE_OVERHEAD, SLOT_BUFFER_SECONDS,
    )


# ═══════════════════════════════════════════
# Sabitler
# ═══════════════════════════════════════════

# Kaç durak ileriye cascade propagasyon yap
CASCADE_HORIZON = 5

# Cascade kontrolünde minimum mesafe (m) — çok uzak duraklar güvenilmez
CASCADE_MAX_DISTANCE = 5000.0

# Çelişki çözümünde ağırlık: yüksek riskli durak daha önemli
RISK_WEIGHT_EXPONENT = 2.0


# ═══════════════════════════════════════════
# Veri Yapıları
# ═══════════════════════════════════════════

@dataclass
class CascadeEffect:
    """Bir hız müdahalesinin sonraki duraklardaki etkisi."""
    vehicle_id: int
    source_stop: int            # müdahalenin kaynağı (durak index)
    affected_stop: int          # etkilenen durak
    eta_shift: float            # ETA kayması (s) — pozitif = gecikme
    causes_overflow: bool       # bu kayma taşmaya yol açıyor mu
    overflow_severity: float    # taşma şiddeti (0-1)


@dataclass
class CoordinatedPlan:
    """Cascade koordinasyonu sonrası tek araç için final plan."""
    vehicle_id: int
    speed_factor: float         # final speed_factor [0.3, 1.2]
    primary_stop: int           # ana hedef durak (next_stop)
    cascade_effects: List[CascadeEffect]
    conflict_resolved: bool     # çelişki çözüldü mü
    original_speed_factor: float  # Aşama 1'den gelen orijinal
    adjustment_reason: str      # "none" | "cascade_safe" | "conflict_resolved"


# ═══════════════════════════════════════════
# Cascade Coordinator
# ═══════════════════════════════════════════

class CascadeCoordinator:
    """
    Çok-duraklı cascade propagasyon ve çelişki çözümü.

    Aşama 1'in ürettiği per-stop planları alır, her aracın
    hız değişikliğini sonraki duraklara yayar, yan etkileri
    kontrol eder ve net optimal speed_factor belirler.
    """

    def __init__(
        self,
        horizon: int = CASCADE_HORIZON,
        max_speed: float = 14.0,
        approach_distance: float = 150.0,
        comfort_braking: float = 2.0,
    ):
        self.horizon = horizon
        self.max_speed = max_speed
        self.approach_distance = approach_distance
        self.comfort_braking = comfort_braking

    def coordinate(
        self,
        vehicles: List[SimVehicle],
        stops: List[LinearStop],
        schedule: StationSchedule,
        is_rush_hour: bool = False,
    ) -> Dict[int, CoordinatedPlan]:
        """
        Tüm filo için cascade koordinasyonu.

        Akış:
            1. Her araç için Aşama 1 planını al
            2. Planın sonraki duraklara etkisini hesapla
            3. Yan etki taşmaya yol açıyorsa → speed_factor'ı ayarla
            4. Çelişki varsa → ağırlıklı maliyet karşılaştırması

        Returns:
            {vehicle_id: CoordinatedPlan}
        """
        coordinated: Dict[int, CoordinatedPlan] = {}

        for veh in vehicles:
            # Durakta olan araçlara müdahale etme
            if veh.phase not in ("cruising", "approaching"):
                coordinated[veh.id] = CoordinatedPlan(
                    vehicle_id=veh.id,
                    speed_factor=1.0,
                    primary_stop=veh.next_stop_index,
                    cascade_effects=[],
                    conflict_resolved=False,
                    original_speed_factor=1.0,
                    adjustment_reason="none",
                )
                continue

            # Aşama 1'den bu aracın planını al
            primary_plan = self._get_primary_plan(veh, schedule)

            if primary_plan is None or not primary_plan.needs_intervention:
                coordinated[veh.id] = CoordinatedPlan(
                    vehicle_id=veh.id,
                    speed_factor=1.0,
                    primary_stop=veh.next_stop_index,
                    cascade_effects=[],
                    conflict_resolved=False,
                    original_speed_factor=1.0,
                    adjustment_reason="none",
                )
                continue

            # Cascade propagasyon: bu yavaşlatma sonraki durakları etkiler mi?
            effects = self._propagate_cascade(
                veh, primary_plan, stops, vehicles, schedule, is_rush_hour,
            )

            # Çelişki kontrolü ve çözümü
            final_speed_factor, reason = self._resolve_conflicts(
                veh, primary_plan, effects, stops,
            )

            coordinated[veh.id] = CoordinatedPlan(
                vehicle_id=veh.id,
                speed_factor=final_speed_factor,
                primary_stop=primary_plan.stop_index,
                cascade_effects=effects,
                conflict_resolved=(reason == "conflict_resolved"),
                original_speed_factor=primary_plan.speed_factor,
                adjustment_reason=reason,
            )

        return coordinated

    def _get_primary_plan(
        self,
        vehicle: SimVehicle,
        schedule: StationSchedule,
    ) -> Optional[ArrivalPlan]:
        """Aracın bir sonraki durağı için Aşama 1 planını al."""
        for plan in schedule.plans:
            if plan.vehicle_id == vehicle.id:
                return plan
        return None

    def _propagate_cascade(
        self,
        vehicle: SimVehicle,
        primary_plan: ArrivalPlan,
        stops: List[LinearStop],
        all_vehicles: List[SimVehicle],
        schedule: StationSchedule,
        is_rush_hour: bool,
    ) -> List[CascadeEffect]:
        """
        Hız müdahalesinin sonraki duraklara etkisini hesapla.

        speed_factor < 1.0 → araç yavaşlar → sonraki duraklara da geç varır
        Bu gecikme sonraki duraklarda taşmaya yol açabilir.
        """
        effects: List[CascadeEffect] = []
        primary_stop_idx = primary_plan.stop_index

        # Mevcut ETA ile müdahaleli ETA arasındaki fark = gecikme
        delay_from_intervention = primary_plan.ideal_arrival - primary_plan.current_eta
        if delay_from_intervention <= 0:
            return effects  # gecikme yok

        # Sonraki horizon durak için cascade kontrol
        cumulative_delay = delay_from_intervention

        for offset in range(1, self.horizon + 1):
            future_stop_idx = primary_stop_idx + offset
            if future_stop_idx >= len(stops):
                break

            future_stop = stops[future_stop_idx]
            dist_from_primary = future_stop.meter_position - stops[primary_stop_idx].meter_position
            if dist_from_primary > CASCADE_MAX_DISTANCE:
                break

            # Dwell süresi gecikmeyi kısmen absorbe eder
            # (durakta zaten duracak, o süre gecikmeyi yutar)
            dwell = estimate_dwell(future_stop, is_rush_hour)
            absorbed = min(cumulative_delay * 0.2, dwell * 0.3)
            effective_delay = cumulative_delay - absorbed

            # Bu durakta bu gecikme taşmaya yol açar mı?
            causes_overflow, severity = self._check_overflow_at_stop(
                vehicle, future_stop, all_vehicles, effective_delay, schedule,
            )

            effects.append(CascadeEffect(
                vehicle_id=vehicle.id,
                source_stop=primary_stop_idx,
                affected_stop=future_stop_idx,
                eta_shift=effective_delay,
                causes_overflow=causes_overflow,
                overflow_severity=severity,
            ))

            # Sonraki durağa gecikme taşınır (azalarak)
            cumulative_delay = effective_delay * 0.85  # %15 absorpsiyon

        return effects

    def _check_overflow_at_stop(
        self,
        vehicle: SimVehicle,
        stop: LinearStop,
        all_vehicles: List[SimVehicle],
        delay: float,
        schedule: StationSchedule,
    ) -> tuple[bool, float]:
        """
        Gecikmenin bu durakta taşmaya yol açıp açmadığını kontrol et.

        Fiziksel erişilebilir kapasiteyi kullanır — sadece arkadan
        girilebilen slotlar sayılır.

        Returns: (causes_overflow, severity 0-1)
        """
        # Fiziksel erişilebilir kapasite (arkadan girilebilir slotlar)
        rear_free = compute_rear_free_slots(stop, all_vehicles)
        on_platform = sum(
            1 for v in all_vehicles
            if v.next_stop_index == stop.index
            and v.phase in ("stopped", "doorsClosed", "blocked", "docking")
        )
        effective_capacity = max(on_platform + rear_free, 1)

        # Bu durağa yaklaşan toplam araç sayısı
        approaching_count = 0
        for v in all_vehicles:
            if v.next_stop_index == stop.index and v.phase in ("cruising", "approaching"):
                approaching_count += 1

        total_demand = approaching_count + on_platform
        overflow_ratio = total_demand / effective_capacity

        if overflow_ratio <= 1.0:
            return False, 0.0

        # Gecikme taşmayı kötüleştiriyor mu?
        # Gecikme = aynı zaman dilimine daha fazla araç sıkışması
        severity = min(1.0, (overflow_ratio - 1.0) / 2.0)
        return True, severity

    def _resolve_conflicts(
        self,
        vehicle: SimVehicle,
        primary_plan: ArrivalPlan,
        effects: List[CascadeEffect],
        stops: List[LinearStop],
    ) -> tuple[float, str]:
        """
        Çelişki çözümü.

        Primary durak: "yavaşla" (speed_factor < 1.0)
        Cascade durak: "bu yavaşlama taşma yaratıyor" (speed_factor > orijinal)

        Çözüm: Hangi durağın taşması daha maliyetli?
        → Maliyet = overflow_risk × slot_kıtlığı
        """
        # Cascade'de ciddi taşma var mı?
        severe_effects = [e for e in effects if e.causes_overflow and e.overflow_severity > 0.3]

        if not severe_effects:
            # Cascade güvenli — orijinal planı uygula
            return primary_plan.speed_factor, "cascade_safe"

        # Çelişki var: primary durak yavaşlatma istiyor ama cascade taşma yaratıyor
        # Ağırlıklı maliyet karşılaştırması

        # Primary durağın maliyeti
        primary_stop = stops[primary_plan.stop_index] if primary_plan.stop_index < len(stops) else None
        primary_cost = primary_plan.overflow_risk * (
            1.0 / max(primary_stop.slot_count, 1) if primary_stop else 1.0
        )

        # Cascade durağın maliyeti (en kötü olanı)
        max_cascade_cost = 0.0
        for effect in severe_effects:
            if effect.affected_stop < len(stops):
                cascade_stop = stops[effect.affected_stop]
                cascade_cost = effect.overflow_severity * (
                    1.0 / max(cascade_stop.slot_count, 1)
                )
                max_cascade_cost = max(max_cascade_cost, cascade_cost)

        if primary_cost >= max_cascade_cost:
            # Primary durak daha kritik → yavaşlatmaya devam
            return primary_plan.speed_factor, "cascade_safe"
        else:
            # Cascade durak daha kritik → yavaşlatmayı hafiflet
            # Orijinal speed_factor ile 1.0 arasında compromise
            compromise = (primary_plan.speed_factor + 1.0) / 2.0
            return compromise, "conflict_resolved"
