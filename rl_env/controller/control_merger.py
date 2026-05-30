"""
Kontrol Birleştirici — SmartStop Tabanlı Sistem
================================================

Akış (her tick — senkron, hafif):
    1. Her SmartStop kendi bölgesini günceller
       → hız önerileri üretir (O(zone_araç) ≈ O(1-2) / durak)
       → durumu StopInterface'e yayınlar
    2. Her araç için SpeedRecommendation → ControlCommand dönüşümü
    3. Forward Safety override (gap koruması, override edilemez)

Headway model yalnızca dashboard metriği olarak tutulmuştur.
Kontrol kararlarını etkilemez.

Eski StationArrivalScheduler ve async scheduler thread kaldırıldı.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

try:
    from ..config import SimVehicle
    from .headway_model import HeadwayModel, HeadwayState
    from .pid_controller import PIDController
    from .stop_interface import StopInterface
    from .smart_stop import SmartStop, SpeedRecommendation, build_smart_stops
except ImportError:
    from config import SimVehicle
    from headway_model import HeadwayModel, HeadwayState
    from pid_controller import PIDController
    from stop_interface import StopInterface
    from smart_stop import SmartStop, SpeedRecommendation, build_smart_stops


@dataclass
class ControlCommand:
    """
    Tek araç için final kontrol komutu.
    Simülasyon motoruna verilir, araç davranışını belirler.
    """
    vehicle_id: int
    hold_time: float        # durakta ek tutma süresi (sn) — şimdilik 0
    speed_factor: float     # hız çarpanı [0.3, 1.2]
    skip_stop: bool         # True = sonraki durağı atla
    source: str             # "smart_stop" | "safety" | "none"

    # Debug / dashboard bilgileri
    reason: str = ""
    headway_error: float = 0.0
    headway_cv: float = 0.0
    eta_to_stop: float = 0.0
    ideal_arrival: float = 0.0
    queue_time_avoided: float = 0.0
    net_benefit: float = 0.0
    overflow_risk: float = 0.0


class ControlMerger:
    """
    SmartStop tabanlı kontrol birleştirici.

    Her tick tüm SmartStop'ları günceller.
    Her SmartStop yalnızca kendi bölgesine bakar → toplam yük O(N_durak × 1-2).

    Parametreler:
        headway_model:   Headway hesaplama (yalnızca metrik / dashboard)
        min_gap:         Minimum takip mesafesi (m) — güvenlik katmanı
        vehicle_length:  Araç boyu (m)
    """

    def __init__(
        self,
        headway_model: HeadwayModel,
        pid: Optional[PIDController] = None,   # geriye uyumluluk için tutuldu
        lookahead_interval: int = 50,           # artık kullanılmıyor, bırakıldı
        min_gap: float = 25.0,
        vehicle_length: float = 20.0,
    ) -> None:
        self.headway_model  = headway_model
        self.pid            = pid               # yedek, kullanılmıyor
        self.min_gap        = min_gap
        self.vehicle_length = vehicle_length

        # SmartStop sistemi — ilk compute() çağrısında başlatılır
        self._interface: StopInterface = StopInterface()
        self._smart_stops: List[SmartStop] = []
        self._stops_initialized: bool = False

        # Sim zamanı
        self._sim_time: float = 0.0

        # Son SmartStop önerileri (dashboard için)
        self._last_rec_map: dict = {}

    # ──────────────────────────────────────────────────────────────
    # Ana Hesaplama
    # ──────────────────────────────────────────────────────────────

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

        Her tick çalışır. Senkron, hafif.
        """
        # ── SmartStop sistemi lazy init ───────────────────────────
        if not self._stops_initialized and stops:
            self._smart_stops = build_smart_stops(
                stops=stops,
                interface=self._interface,
                approach_distance=150.0,
                comfort_braking=2.0,
                max_speed=14.0,
            )
            self._stops_initialized = True

        # ── Headway metrikleri (dashboard) ────────────────────────
        headway_states  = self.headway_model.compute(vehicles, dt)
        fleet_metrics   = self.headway_model.compute_fleet_metrics(headway_states)
        headway_map: Dict[int, HeadwayState] = {hs.vehicle_id: hs for hs in headway_states}

        # ── SmartStop güncellemeleri (her tick, tüm duraklar) ─────
        # Her durak yalnızca kendi bölgesine bakar → O(N_durak × 1-2)
        rec_map: Dict[int, SpeedRecommendation] = {}
        for smart_stop in self._smart_stops:
            recs = smart_stop.update(vehicles, is_rush_hour, self._sim_time)
            for rec in recs:
                rec_map[rec.vehicle_id] = rec
        self._last_rec_map = rec_map

        # ── Her araç için ControlCommand üret ────────────────────
        commands: List[ControlCommand] = []
        for veh in vehicles:
            rec = rec_map.get(veh.id)
            hs  = headway_map.get(veh.id)

            cmd = self._build_command(veh, rec, hs, fleet_metrics)
            cmd = self._apply_safety(cmd, veh, vehicles)
            commands.append(cmd)

        self._sim_time += dt
        return commands

    # ──────────────────────────────────────────────────────────────
    # Komut Oluşturma
    # ──────────────────────────────────────────────────────────────

    def _build_command(
        self,
        vehicle: SimVehicle,
        rec: Optional[SpeedRecommendation],
        hs: Optional[HeadwayState],
        fleet_metrics: dict,
    ) -> ControlCommand:
        """SpeedRecommendation → ControlCommand."""
        headway_error = hs.headway_error if hs else 0.0
        headway_cv    = fleet_metrics.get("cv", 0.0)

        # Durakta olan araçlara hız müdahalesi yapma
        if vehicle.phase in ("stopped", "doorsClosed", "blocked", "queued", "docking"):
            return ControlCommand(
                vehicle_id=vehicle.id,
                hold_time=0.0,
                speed_factor=1.0,
                skip_stop=False,
                source="none",
                reason="stationary",
                headway_error=headway_error,
                headway_cv=headway_cv,
            )

        if rec is None or rec.source == "none":
            return ControlCommand(
                vehicle_id=vehicle.id,
                hold_time=0.0,
                speed_factor=1.0,
                skip_stop=False,
                source="none",
                reason=rec.reason if rec else "no_rec",
                headway_error=headway_error,
                headway_cv=headway_cv,
                eta_to_stop=rec.eta_to_stop if rec else 0.0,
                ideal_arrival=rec.ideal_arrival if rec else 0.0,
            )

        return ControlCommand(
            vehicle_id=vehicle.id,
            hold_time=0.0,
            speed_factor=rec.speed_factor,
            skip_stop=False,
            source="smart_stop",
            reason=rec.reason,
            headway_error=headway_error,
            headway_cv=headway_cv,
            eta_to_stop=rec.eta_to_stop,
            ideal_arrival=rec.ideal_arrival,
            queue_time_avoided=rec.queue_time_avoided,
            net_benefit=rec.net_benefit,
        )

    # ──────────────────────────────────────────────────────────────
    # Forward Safety Override
    # ──────────────────────────────────────────────────────────────

    def _apply_safety(
        self,
        cmd: ControlCommand,
        vehicle: SimVehicle,
        all_vehicles: List[SimVehicle],
    ) -> ControlCommand:
        """
        Forward safety override — gap koruması.
        Öndeki araca minimum mesafe korunur.
        Bu katman hiçbir zaman override edilemez.
        """
        if vehicle.phase in ("stopped", "doorsClosed", "blocked", "queued", "docking"):
            return cmd

        leader_dist = float("inf")
        for v in all_vehicles:
            if v.id == vehicle.id:
                continue
            if v.position_meters <= vehicle.position_meters:
                continue
            dist = v.position_meters - vehicle.position_meters - self.vehicle_length
            if dist < leader_dist:
                leader_dist = dist

        if leader_dist > self.min_gap * 3:
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
            if cmd.source != "smart_stop":
                cmd.source = "safety"

        return cmd

    # ──────────────────────────────────────────────────────────────
    # Dashboard / Durum Özeti
    # ──────────────────────────────────────────────────────────────

    def get_state_summary(self) -> dict:
        """Kontrolcü durumunun özeti (dashboard için)."""
        interface_states = self._interface.get_all_states()

        active_interventions = sum(
            1 for s in interface_states.values()
            if s.overflow_count > 0
        )
        total_overflow = self._interface.total_overflow_count()
        most_congested = self._interface.most_congested_stop()

        return {
            "active_interventions": active_interventions,
            "total_overflow_count": total_overflow,
            "most_congested_stop": most_congested.stop_name if most_congested else "",
            "most_congested_level": round(most_congested.congestion_level, 2) if most_congested else 0.0,
            "target_headway": self.headway_model.target_headway,
            "target_headway_min": self.headway_model.target_headway_minutes,
            "smart_stops_active": len(self._smart_stops),
            "pid_gains": self.pid.get_gains() if self.pid else {},
        }

    def get_stop_interface_states(self) -> dict:
        """Tüm durak bölge durumlarını döndür (dashboard için)."""
        # SmartStop önerilerini stop_index -> [rec, ...] olarak grupla
        recs_by_stop: Dict[int, list] = {}
        for rec in self._last_rec_map.values():
            if rec.source == "smart_stop":
                recs_by_stop.setdefault(rec.stop_index, []).append(rec)

        result = {}
        for idx, s in self._interface.get_all_states().items():
            # slot_timeline: [(slot_id, free_time, bus_id_or_None)]
            slot_timeline_json = [
                {"slotId": t[0], "freeTime": round(t[1], 1), "busId": t[2]}
                for t in s.slot_timeline
            ]

            # Bu durağa yaklaşan müdahale edilmiş araçlar
            interventions = [
                {
                    "vehicleId": rec.vehicle_id,
                    "speedFactor": round(rec.speed_factor, 2),
                    "reason": rec.reason,
                    "etaToStop": round(rec.eta_to_stop, 1),
                    "idealArrival": round(rec.ideal_arrival, 1),
                    "queueTimeSaved": round(rec.queue_time_avoided, 1),
                    "netBenefit": round(rec.net_benefit, 2),
                }
                for rec in recs_by_stop.get(idx, [])
            ]

            # Komşu baskı
            downstream_pressure = round(self._interface.get_downstream_pressure(idx), 3)
            upstream_density    = round(self._interface.get_upstream_density(idx), 3)

            result[idx] = {
                "stop_name": s.stop_name,
                "vehicles_in_zone": s.vehicles_in_zone,
                "occupied_slots": s.occupied_slots,
                "slot_capacity": s.slot_capacity,
                "congestion_level": round(s.congestion_level, 2),
                "overflow_count": s.overflow_count,
                "incoming_etas": s.incoming_etas,
                "slotTimeline": slot_timeline_json,
                "downstreamPressure": downstream_pressure,
                "upstreamDensity": upstream_density,
                "interventions": interventions,
            }
        return result

    def reset(self) -> None:
        """Tüm katmanların durumunu sıfırla (yeni episode)."""
        self.headway_model.reset()
        if self.pid:
            self.pid.reset()
        self._interface.reset()
        self._smart_stops = []
        self._stops_initialized = False
        self._sim_time = 0.0
        self._last_rec_map = {}
