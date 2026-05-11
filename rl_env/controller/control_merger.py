"""
Kontrol Birleştirici — PID Reflex + Lookahead Proaktif → Final Komut
=====================================================================

İki katmanın çıktılarını tek bir ControlCommand'a birleştirir.

Birleştirme Stratejisi:
    1. PID her tick çalışır (reflex — anlık headway düzeltme)
    2. Lookahead her N tick'te çalışır (proaktif — multi-stop plan)
    3. hold_time = max(pid_hold, lookahead_hold)
       Gerekçe: Her iki katman da "en az bu kadar tut" der.
       En kısıtlayıcı olan kazanır.
    4. speed_factor: Lookahead aktifse lookahead, değilse 1.0
    5. skip_stop: Sadece Lookahead önerir
    6. Forward safety: Öndeki araca minimum mesafe her zaman korunur

Güvenlik Katmanı:
    Forward safety tüm kontrol çıktılarının üstünde çalışır.
    Öndeki araca çok yakınsa speed_factor zorla düşürülür.
    Bu katman override edilemez.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from typing import List, Optional

try:
    from ..config import SimVehicle
    from .headway_model import HeadwayModel, HeadwayState
    from .pid_controller import PIDController, PIDOutput
    from .lookahead_optimizer import LookaheadOptimizer, LookaheadDecision
except ImportError:
    from config import SimVehicle
    from headway_model import HeadwayModel, HeadwayState
    from pid_controller import PIDController, PIDOutput
    from lookahead_optimizer import LookaheadOptimizer, LookaheadDecision


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
    source: str                 # "pid" | "lookahead" | "merged" | "safety"

    # Debug bilgileri
    pid_hold: float = 0.0
    lookahead_hold: float = 0.0
    headway_error: float = 0.0
    headway_cv: float = 0.0
    cost: float = 0.0


class ControlMerger:
    """
    PID + Lookahead birleştirici ve güvenlik katmanı.

    Parametreler:
        headway_model:  Katman 1 — headway hesaplama
        pid:            Katman 2 — PID regülatör
        lookahead:      Katman 3 — lookahead optimizer
        lookahead_interval: Lookahead kaç tick'te bir çalışır
        min_gap:        Minimum takip mesafesi (m) — güvenlik
        vehicle_length: Araç boyu (m)
    """

    def __init__(
        self,
        headway_model: HeadwayModel,
        pid: PIDController,
        lookahead: LookaheadOptimizer,
        lookahead_interval: int = 50,       # 50 × 0.1s = 5 saniyede bir
        min_gap: float = 25.0,
        vehicle_length: float = 20.0,
    ):
        self.headway_model = headway_model
        self.pid = pid
        self.lookahead = lookahead
        self.lookahead_interval = lookahead_interval
        self.min_gap = min_gap
        self.vehicle_length = vehicle_length

        # Lookahead cache
        self._tick_counter = 0
        self._cached_lookahead: dict[int, LookaheadDecision] = {}
        self._la_running = False

    def compute(
        self,
        vehicles: List[SimVehicle],
        stops,                          # List[LinearStop]
        dt: float = 0.1,
        is_rush_hour: bool = False,
        current_hour: float = 8.0,
    ) -> List[ControlCommand]:
        """
        Tüm filo için kontrol komutlarını hesapla.

        Akış:
            1. HeadwayModel → headway durumları
            2. PID → hold_time per vehicle (her tick)
            3. Lookahead → hold + speed + skip (her N tick)
            4. Merge → final komut
            5. Safety → forward gap kontrolü

        Args:
            vehicles:     Tüm araçlar
            stops:        Rota durakları
            dt:           Zaman adımı (sn)
            is_rush_hour: Pik saat mi
            current_hour: Saat (talep profili için)

        Returns:
            Her araç için ControlCommand
        """
        # ─── Katman 1: Headway Model ───
        headway_states = self.headway_model.compute(vehicles, dt)
        fleet_metrics = self.headway_model.compute_fleet_metrics(headway_states)

        # ─── Katman 2: PID (her tick) ───
        at_stop_flags = {
            v.id: v.phase in ("stopped", "doorsClosed")
            for v in vehicles
        }
        pid_outputs = self.pid.compute_all(headway_states, at_stop_flags)
        pid_map = {po.vehicle_id: po for po in pid_outputs}

        # ─── Katman 3: Lookahead (her N tick, arka planda) ───
        self._tick_counter += 1
        if self._tick_counter >= self.lookahead_interval and not self._la_running:
            self._tick_counter = 0
            self._run_lookahead_async(vehicles, stops, is_rush_hour, current_hour)

        # ─── Merge + Safety ───
        commands: List[ControlCommand] = []
        headway_map = {hs.vehicle_id: hs for hs in headway_states}

        for veh in vehicles:
            pid_out = pid_map.get(veh.id)
            la_out = self._cached_lookahead.get(veh.id)
            hs = headway_map.get(veh.id)

            cmd = self._merge_single(veh, pid_out, la_out, hs, fleet_metrics)

            # ─── Forward Safety Override ───
            cmd = self._apply_safety(cmd, veh, vehicles)

            commands.append(cmd)

        return commands

    def _merge_single(
        self,
        vehicle: SimVehicle,
        pid_out: Optional[PIDOutput],
        la_out: Optional[LookaheadDecision],
        headway_state: Optional[HeadwayState],
        fleet_metrics: dict,
    ) -> ControlCommand:
        """Tek araç için PID + Lookahead birleştirme."""

        pid_hold = pid_out.hold_time if pid_out else 0.0
        la_hold = la_out.hold_time if la_out else 0.0
        la_speed = la_out.speed_factor if la_out else 1.0
        la_skip = la_out.skip_stop if la_out else False
        la_cost = la_out.cost if la_out else 0.0

        # Hold time: en kısıtlayıcı kazanır
        final_hold = max(pid_hold, la_hold)

        # Speed factor: Lookahead varsa onu kullan
        final_speed = la_speed if la_out and la_speed < 1.0 else 1.0

        # Skip: sadece Lookahead önerir
        final_skip = la_skip

        # Source belirleme
        if la_out and (la_hold > pid_hold or la_speed < 1.0 or la_skip):
            source = "lookahead"
        elif pid_hold > 0:
            source = "pid"
        else:
            source = "merged"

        return ControlCommand(
            vehicle_id=vehicle.id,
            hold_time=final_hold,
            speed_factor=final_speed,
            skip_stop=final_skip,
            source=source,
            pid_hold=pid_hold,
            lookahead_hold=la_hold,
            headway_error=headway_state.headway_error if headway_state else 0.0,
            headway_cv=fleet_metrics.get("cv", 0.0),
            cost=la_cost,
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
        gap < min_gap ise speed_factor agresif düşürülür.
        Bu katman override edilemez.
        """
        # Durakta olan araçlara güvenlik uygulanmaz (FSM yönetiyor)
        if vehicle.phase in ("stopped", "doorsClosed", "blocked", "queued", "docking"):
            return cmd

        # Öndeki aracı bul
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
            return cmd  # güvenli mesafede, müdahale yok

        # Gap ratio: < 1 tehlikeli, > 1 güvenli
        gap_ratio = leader_dist / self.min_gap

        if gap_ratio < 0.3:
            # Kritik — neredeyse çarpışma
            cmd.speed_factor = min(cmd.speed_factor, 0.1)
            cmd.source = "safety"
        elif gap_ratio < 0.6:
            # Tehlikeli — agresif yavaşla
            cmd.speed_factor = min(cmd.speed_factor, 0.3)
            cmd.source = "safety"
        elif gap_ratio < 1.0:
            # Dikkatli — orantılı yavaşla
            safe_factor = 0.3 + 0.7 * gap_ratio
            cmd.speed_factor = min(cmd.speed_factor, safe_factor)
            if cmd.source != "lookahead":
                cmd.source = "safety"

        return cmd

    def _run_lookahead_async(
        self,
        vehicles: List[SimVehicle],
        stops,
        is_rush_hour: bool,
        current_hour: float,
    ) -> None:
        """Lookahead'i arka plan thread'inde çalıştır."""
        self._la_running = True

        # Araç durumlarının snapshot'ı (thread safety)
        vehicle_copies = [v.copy() for v in vehicles]
        target_hw = self.headway_model.target_headway

        def _worker():
            try:
                la_decisions = self.lookahead.optimize(
                    vehicle_copies, stops,
                    target_headway=target_hw,
                    is_rush_hour=is_rush_hour,
                    current_hour=current_hour,
                )
                self._cached_lookahead = {d.vehicle_id: d for d in la_decisions}
            except Exception:
                pass
            finally:
                self._la_running = False

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def get_state_summary(self) -> dict:
        """Kontrolcü durumunun özeti (dashboard için)."""
        return {
            "tick_counter": self._tick_counter,
            "lookahead_interval": self.lookahead_interval,
            "cached_decisions": len(self._cached_lookahead),
            "pid_gains": self.pid.get_gains(),
            "target_headway": self.headway_model.target_headway,
            "target_headway_min": self.headway_model.target_headway_minutes,
        }

    def reset(self) -> None:
        """Tüm katmanların durumunu sıfırla."""
        self.headway_model.reset()
        self.pid.reset()
        self._tick_counter = 0
        self._cached_lookahead.clear()
