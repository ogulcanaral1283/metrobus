"""
Kontrol Birleştirici — 4 Aşamalı Durak-Slot Merkezli Sistem
=============================================================

Eski sistem: PID (headway) + Lookahead → merge
Yeni sistem: 4 aşama durak-slot optimizasyonu

Akış (her 5s — stratejik):
    Aşama 1: StationArrivalScheduler → her araca ideal varış zamanı
    Aşama 4: CascadeCoordinator → cascade etkileri çöz, net speed_factor
    Aşama 3: SpeedProfiler → enerji-optimal hız profili

Akış (her 0.1s — taktik):
    Aşama 2: PID (slot-timing) → plandan sapma düzeltme

Güvenlik Katmanı:
    Forward safety tüm kontrol çıktılarının üstünde çalışır.
    Bu katman override edilemez.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Dict

try:
    from ..config import SimVehicle
    from .headway_model import HeadwayModel, HeadwayState
    from .pid_controller import PIDController, PIDOutput
    from .station_arrival_scheduler import (
        StationArrivalScheduler, StationSchedule, ArrivalPlan, compute_eta,
    )
    from .speed_profile import SpeedProfiler, SpeedCommand
    from .cascade_coordinator import CascadeCoordinator, CoordinatedPlan
except ImportError:
    from config import SimVehicle
    from headway_model import HeadwayModel, HeadwayState
    from pid_controller import PIDController, PIDOutput
    from station_arrival_scheduler import (
        StationArrivalScheduler, StationSchedule, ArrivalPlan, compute_eta,
    )
    from speed_profile import SpeedProfiler, SpeedCommand
    from cascade_coordinator import CascadeCoordinator, CoordinatedPlan


@dataclass
class ControlCommand:
    """
    Tek araç için final kontrol komutu.
    Bu yapı simülasyon motoruna verilir ve araç davranışını belirler.
    """
    vehicle_id: int
    hold_time: float            # durakta ek tutma süresi (sn), ≥ 0
    speed_factor: float         # hız çarpanı [0.3, 1.3], 1.0 = normal
    skip_stop: bool             # True = sonraki durağı atla
    source: str                 # "scheduler" | "pid" | "cascade" | "safety" | "none"

    # Debug bilgileri
    pid_hold: float = 0.0
    lookahead_hold: float = 0.0
    headway_error: float = 0.0
    headway_cv: float = 0.0
    cost: float = 0.0

    # Yeni: slot-timing bilgileri
    ideal_arrival: float = 0.0
    current_eta: float = 0.0
    overflow_risk: float = 0.0
    energy_saving: float = 0.0


class ControlMerger:
    """
    4 Aşamalı durak-slot merkezli kontrol birleştirici.

    Parametreler:
        headway_model:    Headway hesaplama (metrik için korunuyor)
        pid:              PID regülatör (slot-timing modunda)
        scheduler:        Aşama 1 — durak varış zamanlaması
        profiler:         Aşama 3 — enerji-optimal hız profili
        coordinator:      Aşama 4 — cascade koordinasyon
        schedule_interval: Scheduler kaç tick'te bir çalışır
        min_gap:          Minimum takip mesafesi (m) — güvenlik
        vehicle_length:   Araç boyu (m)
    """

    def __init__(
        self,
        headway_model: HeadwayModel,
        pid: PIDController,
        scheduler: Optional[StationArrivalScheduler] = None,
        profiler: Optional[SpeedProfiler] = None,
        coordinator: Optional[CascadeCoordinator] = None,
        lookahead_interval: int = 50,
        min_gap: float = 25.0,
        vehicle_length: float = 20.0,
    ):
        self.headway_model = headway_model
        self.pid = pid

        # Yeni 4 aşama
        self.scheduler = scheduler or StationArrivalScheduler()
        self.profiler = profiler or SpeedProfiler()
        self.coordinator = coordinator or CascadeCoordinator()

        self.lookahead_interval = lookahead_interval
        self.min_gap = min_gap
        self.vehicle_length = vehicle_length

        # Scheduler cache
        self._tick_counter = self.lookahead_interval - 1  # ilk tick'te hemen calistir
        self._cached_schedule: Optional[StationSchedule] = None
        self._cached_coordinated: Dict[int, CoordinatedPlan] = {}
        self._cached_speed_cmds: Dict[int, SpeedCommand] = {}
        self._scheduler_running = False


    def compute(
        self,
        vehicles: List[SimVehicle],
        stops,
        dt: float = 0.1,
        is_rush_hour: bool = False,
        current_hour: float = 8.0,
    ) -> List[ControlCommand]:
        """
        Tüm filo için kontrol komutlarını hesapla.

        Stratejik döngü (her N tick):
            Aşama 1 → ideal varış zamanları
            Aşama 4 → cascade koordinasyon
            Aşama 3 → enerji-optimal hız profili

        Taktik döngü (her tick):
            Headway metrikleri (dashboard için)
            Aşama 2 → PID fine-tuning
            Güvenlik → forward gap

        Returns:
            Her araç için ControlCommand
        """
        # ─── Headway metrikleri (dashboard uyumluluğu) ───
        headway_states = self.headway_model.compute(vehicles, dt)
        fleet_metrics = self.headway_model.compute_fleet_metrics(headway_states)
        headway_map = {hs.vehicle_id: hs for hs in headway_states}

        # ─── Stratejik döngü (her N tick) ───
        self._tick_counter += 1
        # Scheduler hang koruması: 10s'den uzun sürerse zorla resetle
        if self._scheduler_running and hasattr(self, '_scheduler_start_time'):
            if time.monotonic() - self._scheduler_start_time > 10.0:
                self._scheduler_running = False
        if self._tick_counter >= self.lookahead_interval and not self._scheduler_running:
            self._tick_counter = 0
            # İlk çalışma senkron (cache boş), sonraki async
            if self._cached_schedule is None:
                self._run_scheduler_sync(vehicles, stops, is_rush_hour)
            else:
                self._run_scheduler_async(vehicles, stops, is_rush_hour)

        # ─── Her araç için komut üret ───
        commands: List[ControlCommand] = []

        for veh in vehicles:
            cmd = self._compute_single(
                veh, stops, headway_map, fleet_metrics, is_rush_hour,
            )

            # ─── Forward Safety Override ───
            cmd = self._apply_safety(cmd, veh, vehicles)

            commands.append(cmd)

        return commands

    def _compute_single(
        self,
        vehicle: SimVehicle,
        stops,
        headway_map: dict,
        fleet_metrics: dict,
        is_rush_hour: bool,
    ) -> ControlCommand:
        """Tek araç için 4 aşama birleştirme."""

        hs = headway_map.get(vehicle.id)

        # Durakta olan araçlara müdahale etme
        if vehicle.phase in ("stopped", "doorsClosed", "blocked", "queued", "docking"):
            return ControlCommand(
                vehicle_id=vehicle.id,
                hold_time=0.0,
                speed_factor=1.0,
                skip_stop=False,
                source="none",
                headway_error=hs.headway_error if hs else 0.0,
                headway_cv=fleet_metrics.get("cv", 0.0),
            )

        # ─── Aşama 1+4+3: Stratejik plan (cache'den) ───
        coordinated = self._cached_coordinated.get(vehicle.id)
        speed_cmd = self._cached_speed_cmds.get(vehicle.id)
        schedule = self._cached_schedule

        # Stratejik speed_factor
        strategic_speed_factor = 1.0
        ideal_arrival = 0.0
        current_eta = 0.0
        overflow_risk = 0.0
        energy_saving = 0.0
        source = "none"

        if coordinated and coordinated.speed_factor < 1.0:
            strategic_speed_factor = coordinated.speed_factor
            source = "cascade" if coordinated.conflict_resolved else "scheduler"

        if speed_cmd and speed_cmd.speed_factor < strategic_speed_factor:
            strategic_speed_factor = speed_cmd.speed_factor
            energy_saving = speed_cmd.energy_saving
            source = "scheduler"

        # Plan bilgileri (debug)
        if schedule:
            for plan in schedule.plans:
                if plan.vehicle_id == vehicle.id:
                    ideal_arrival = plan.ideal_arrival
                    current_eta = plan.current_eta
                    overflow_risk = plan.overflow_risk
                    break

        # ─── Aşama 2: PID fine-tuning (her tick) ───
        pid_adjustment = 0.0
        if ideal_arrival > 0 and current_eta > 0:
            pid_out = self.pid.compute_slot_timing(
                vehicle.id, current_eta, ideal_arrival, overflow_risk,
            )
            # PID çıktısı: timing error magnitude
            # Simetrik katsayılar — yavaşlatma ve hızlandırma eşit güçte
            if pid_out.error > 0.5:
                # Erken varacak → yavaşla
                pid_adjustment = -0.02 * min(pid_out.error, 10.0)
            elif pid_out.error < -0.5:
                # Geç varacak → hızlan (aynı katsayı)
                pid_adjustment = 0.02 * min(abs(pid_out.error), 10.0)

        # ─── Final speed_factor ───
        final_speed_factor = strategic_speed_factor + pid_adjustment
        final_speed_factor = max(0.3, min(1.2, final_speed_factor))

        return ControlCommand(
            vehicle_id=vehicle.id,
            hold_time=0.0,
            speed_factor=final_speed_factor,
            skip_stop=False,
            source=source,
            pid_hold=pid_adjustment,
            headway_error=hs.headway_error if hs else 0.0,
            headway_cv=fleet_metrics.get("cv", 0.0),
            ideal_arrival=ideal_arrival,
            current_eta=current_eta,
            overflow_risk=overflow_risk,
            energy_saving=energy_saving,
        )

    def _apply_safety(
        self,
        cmd: ControlCommand,
        vehicle: SimVehicle,
        all_vehicles: List[SimVehicle],
    ) -> ControlCommand:
        """
        Forward safety override.
        Öndeki araca minimum mesafe korunur.
        Bu katman override edilemez.
        """
        if vehicle.phase in ("stopped", "doorsClosed", "blocked", "queued", "docking"):
            return cmd

        leader = None
        leader_dist = float("inf")

        for v in all_vehicles:
            if v.id == vehicle.id:
                continue
            if v.position_meters <= vehicle.position_meters:
                continue
            dist = v.position_meters - vehicle.position_meters - self.vehicle_length
            if dist < leader_dist:
                leader_dist = dist
                leader = v

        if leader is None or leader_dist > self.min_gap * 3:
            return cmd

        gap_ratio = leader_dist / self.min_gap

        if gap_ratio < 0.3:
            cmd.speed_factor = min(cmd.speed_factor, 0.1)
            cmd.source = "safety"
        elif gap_ratio < 0.6:
            cmd.speed_factor = min(cmd.speed_factor, 0.3)
            cmd.source = "safety"
        elif gap_ratio < 1.0:
            safe_factor = 0.3 + 0.7 * gap_ratio
            cmd.speed_factor = min(cmd.speed_factor, safe_factor)
            if cmd.source not in ("scheduler", "cascade"):
                cmd.source = "safety"

        return cmd

    def _run_scheduler_core(
        self,
        vehicle_copies: List[SimVehicle],
        stops,
        is_rush_hour: bool,
    ) -> None:
        """Stratejik planlama: Aşama 1 + 4 + 3 çalıştır."""
        # Aşama 1: Station Arrival Scheduler
        schedule = self.scheduler.schedule(
            vehicle_copies, stops, is_rush_hour,
        )
        self._cached_schedule = schedule

        # Aşama 4: Cascade Koordinasyon
        coordinated = self.coordinator.coordinate(
            vehicle_copies, stops, schedule, is_rush_hour,
        )
        self._cached_coordinated = coordinated

        # Aşama 3: Enerji-optimal hız profili
        speed_cmds: Dict[int, SpeedCommand] = {}
        for veh in vehicle_copies:
            coord = coordinated.get(veh.id)
            plan = None
            for p in schedule.plans:
                if p.vehicle_id == veh.id:
                    plan = p
                    break

            if plan and plan.needs_intervention:
                speed_cmd = self.profiler.compute(
                    veh.id,
                    veh.speed,
                    plan.distance_to_stop,
                    plan.ideal_arrival,
                )
                # Cascade'den gelen speed_factor ile karşılaştır
                if coord and coord.speed_factor < speed_cmd.speed_factor:
                    speed_cmd.speed_factor = coord.speed_factor
                speed_cmds[veh.id] = speed_cmd

        self._cached_speed_cmds = speed_cmds

    def _run_scheduler_sync(
        self,
        vehicles: List[SimVehicle],
        stops,
        is_rush_hour: bool,
    ) -> None:
        """Stratejik planlamayı senkron çalıştır (ilk tick için)."""
        vehicle_copies = [v.copy() for v in vehicles]
        try:
            self._run_scheduler_core(vehicle_copies, stops, is_rush_hour)
        except Exception:
            pass

    def _run_scheduler_async(
        self,
        vehicles: List[SimVehicle],
        stops,
        is_rush_hour: bool,
    ) -> None:
        """Stratejik planlamayı arka plan thread'inde çalıştır."""
        self._scheduler_running = True
        self._scheduler_start_time = time.monotonic()
        vehicle_copies = [v.copy() for v in vehicles]

        def _worker():
            try:
                self._run_scheduler_core(vehicle_copies, stops, is_rush_hour)
            except Exception as e:
                import sys
                print(f"[Scheduler] Background error: {e}", file=sys.stderr)
            finally:
                self._scheduler_running = False

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def get_state_summary(self) -> dict:
        """Kontrolcü durumunun özeti (dashboard için)."""
        schedule = self._cached_schedule
        active_interventions = sum(
            1 for p in (schedule.plans if schedule else [])
            if p.needs_intervention
        )
        total_wait_saved = schedule.total_estimated_wait_saved if schedule else 0.0

        return {
            "tick_counter": self._tick_counter,
            "schedule_interval": self.lookahead_interval,
            "active_interventions": active_interventions,
            "total_wait_saved": round(total_wait_saved, 1),
            "total_overflow_risk": round(
                schedule.total_overflow_risk if schedule else 0.0, 2
            ),
            "pid_gains": self.pid.get_gains(),
            "target_headway": self.headway_model.target_headway,
            "target_headway_min": self.headway_model.target_headway_minutes,
        }

    def reset(self) -> None:
        """Tüm katmanların durumunu sıfırla."""
        self.headway_model.reset()
        self.pid.reset()
        self._tick_counter = 0
        self._cached_schedule = None
        self._cached_coordinated.clear()
        self._cached_speed_cmds.clear()
