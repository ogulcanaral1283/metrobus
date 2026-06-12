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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

try:
    from ..config import SimVehicle
    from .headway_model import HeadwayModel, HeadwayState
    from .pid_controller import PIDController
    from .stop_interface import StopInterface
    from .smart_stop import SmartStop, SpeedRecommendation, DwellRecommendation, build_smart_stops, MIN_SPEED_FACTOR
except ImportError:
    from config import SimVehicle
    from headway_model import HeadwayModel, HeadwayState
    from pid_controller import PIDController
    from stop_interface import StopInterface
    from smart_stop import SmartStop, SpeedRecommendation, DwellRecommendation, build_smart_stops, MIN_SPEED_FACTOR


# ═══════════════════════════════════════════════════════════════════
# Hız Bandı (Sürücü Tavsiyesi) Sabitleri
# ═══════════════════════════════════════════════════════════════════
# Sürücüye nokta hız ("61 km/h") değil, tutulabilir bir BAND ("60-70")
# verilir. Band içindeyken yeni komut üretilmez → saniyelik "hızlan-yavaşla"
# titremesi (chatter) kaynağında biter. Yeni band ancak gereken hız mevcut
# banttan çıkınca verilir (histerezis). Genişlik sabit, gerçek bir sürücü
# ekranı gibi 5 km/h'e yuvarlanır.

BAND_WIDTH_KMH: float = 10.0   # band genişliği (sabit) — insani granülarite
BAND_SNAP_KMH: float = 5.0     # band kenarları bu ızgaraya yuvarlanır
_KMH_PER_MS: float = 3.6

# ── Bant kararlılığı (anti-chatter) ──────────────────────────────
# Gerçek bir sürücü saniyede bir yeni emir almaz. Üç katman:
#   1) EMA: gereken hız tick gürültüsünden arındırılır (alçak geçiren filtre)
#   2) Min-hold: bir band en az bu süre korunur, küçük sapmalar yok sayılır
#   3) Escape: gereken hız banttan BÜYÜK saparsa hold beklenmeden yenilenir
BAND_EMA_TAU_S: float = 2.5    # gereken hızın yumuşatma zaman sabiti (s)
BAND_MIN_HOLD_S: float = 8.0   # bir band en az bu kadar tutulur (s)
BAND_ESCAPE_KMH: float = 8.0   # bu kadar büyük sapmada hold'u atla (acil değişim)


def _snap_kmh(v_kmh: float) -> float:
    """Hızı en yakın BAND_SNAP_KMH katına yuvarla (60-70 gibi yuvarlak band)."""
    return round(v_kmh / BAND_SNAP_KMH) * BAND_SNAP_KMH


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
    dwell_cap: float = -1.0 # stopped araç için dwell sınırı (sn); <0 = expedite yok

    # Debug / dashboard bilgileri
    reason: str = ""
    headway_error: float = 0.0
    headway_cv: float = 0.0
    eta_to_stop: float = 0.0
    ideal_arrival: float = 0.0
    queue_time_avoided: float = 0.0
    net_benefit: float = 0.0
    overflow_risk: float = 0.0

    # Sürücüye verilen hız bandı (km/h) — 0.0 = aktif band yok
    band_low: float = 0.0
    band_high: float = 0.0


class ControlMerger:
    """
    SmartStop tabanlı kontrol birleştirici.

    Her tick tüm SmartStop'ları günceller.
    Her SmartStop yalnızca kendi bölgesine bakar → toplam yük O(N_durak × 1-2).

    Parametreler:
        headway_model:   Headway hesaplama (yalnızca metrik / dashboard)
        pid:             Yalnızca dashboard'da kazanç gösterimi için
        min_gap:         Minimum takip mesafesi (m) — güvenlik katmanı
        vehicle_length:  Araç boyu (m)
        comfort_braking: SmartStop ETA/fren modeli — fizik motoruyla aynı olmalı
        max_speed:       SmartStop hız çarpanı referansı — fizik motoruyla aynı
        approach_distance: Durak yaklaşma mesafesi (m) — fizik motoruyla aynı
    """

    def __init__(
        self,
        headway_model: HeadwayModel,
        pid: Optional[PIDController] = None,
        min_gap: float = 25.0,
        vehicle_length: float = 20.0,
        comfort_braking: float = 3.5,
        max_speed: float = 25.0,
        approach_distance: float = 150.0,
    ) -> None:
        self.headway_model     = headway_model
        self.pid               = pid
        self.min_gap           = min_gap
        self.vehicle_length    = vehicle_length
        self.comfort_braking   = comfort_braking
        self.max_speed         = max_speed
        self.approach_distance = approach_distance

        # SmartStop sistemi — ilk compute() çağrısında başlatılır
        self._interface: StopInterface = StopInterface()
        self._smart_stops: List[SmartStop] = []
        self._stops_initialized: bool = False

        # Sim zamanı
        self._sim_time: float = 0.0

        # Son SmartStop önerileri (dashboard için)
        self._last_rec_map: dict = {}
        self._last_dwell_map: Dict[int, DwellRecommendation] = {}

        # Araç başına taahhüt edilen hız bandı durumu.
        # {"low", "high": km/h band kenarları; "commit_time": band'in verildiği
        #  sim zamanı (min-hold için); "ema": yumuşatılmış gereken hız (km/h)}
        # Band içinde kaldığı + min-hold dolmadığı sürece sabit tutulur.
        self._band_state: Dict[int, dict] = {}

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
                approach_distance=self.approach_distance,
                comfort_braking=self.comfort_braking,
                max_speed=self.max_speed,
            )
            self._stops_initialized = True

        # ── Headway metrikleri (dashboard) ────────────────────────
        headway_states  = self.headway_model.compute(vehicles, dt)
        fleet_metrics   = self.headway_model.compute_fleet_metrics(headway_states)
        headway_map: Dict[int, HeadwayState] = {hs.vehicle_id: hs for hs in headway_states}

        # ── SmartStop güncellemeleri (her tick, tüm duraklar) ─────
        # Her durak yalnızca kendi bölgesine bakar → O(N_durak × 1-2)
        rec_map: Dict[int, SpeedRecommendation] = {}
        dwell_map: Dict[int, DwellRecommendation] = {}
        for smart_stop in self._smart_stops:
            recs, dwell_recs = smart_stop.update(vehicles, is_rush_hour, self._sim_time)
            for rec in recs:
                rec_map[rec.vehicle_id] = rec
            for drec in dwell_recs:
                dwell_map[drec.vehicle_id] = drec
        self._last_rec_map = rec_map
        self._last_dwell_map = dwell_map

        # ── Her araç için ControlCommand üret ────────────────────
        commands: List[ControlCommand] = []
        for veh in vehicles:
            rec = rec_map.get(veh.id)
            hs  = headway_map.get(veh.id)
            drec = dwell_map.get(veh.id)

            cmd = self._build_command(veh, rec, hs, fleet_metrics, drec, dt)
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
        drec: Optional[DwellRecommendation] = None,
        dt: float = 0.1,
    ) -> ControlCommand:
        """SpeedRecommendation → ControlCommand."""
        headway_error = hs.headway_error if hs else 0.0
        headway_cv    = fleet_metrics.get("cv", 0.0)

        # Durakta olan araçlara hız müdahalesi yapma
        if vehicle.phase in ("stopped", "doorsClosed", "blocked", "queued", "docking"):
            self._band_state.pop(vehicle.id, None)  # aktif band tavsiyesi yok
            # Taşma varsa stopped araç için dwell expedite (hız müdahalesi değil)
            if vehicle.phase == "stopped" and drec is not None:
                return ControlCommand(
                    vehicle_id=vehicle.id,
                    hold_time=0.0,
                    speed_factor=1.0,
                    skip_stop=False,
                    source="smart_stop",
                    reason="expedite_dwell",
                    dwell_cap=drec.dwell_cap,
                    headway_error=headway_error,
                    headway_cv=headway_cv,
                )
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
            # Müdahale bitti. Araç DAHA ÖNCE yavaşlatıldıysa (aktif band var),
            # bandı bir anda silmek yerine TAM HIZA doğru TIRMANDIR → sürücüye
            # "artık hızlan" sinyali verilir (65-75 → 80-90 tut). Band tavana
            # ulaşınca tavsiye tamamlanır ve bırakılır. Hiç yönetilmemiş araçta
            # band gösterilmez (serbest seyir, tavsiye gereksiz).
            if vehicle.id in self._band_state:
                band_factor, band_low, band_high = self._apply_band(vehicle.id, 1.0, dt)
                full_kmh = self.max_speed * _KMH_PER_MS
                released = band_high >= full_kmh - BAND_SNAP_KMH
                if released or vehicle.phase != "cruising":
                    # Tam hıza ulaşıldı (veya seyirde değil) → tavsiyeyi kaldır
                    self._band_state.pop(vehicle.id, None)
                    band_low = band_high = 0.0
                return ControlCommand(
                    vehicle_id=vehicle.id,
                    hold_time=0.0,
                    speed_factor=band_factor if band_high > 0.0 else 1.0,
                    skip_stop=False,
                    source="smart_stop" if band_high > 0.0 else "none",
                    reason="resume" if band_high > 0.0 else "released",
                    headway_error=headway_error,
                    headway_cv=headway_cv,
                    eta_to_stop=rec.eta_to_stop if rec else 0.0,
                    ideal_arrival=rec.ideal_arrival if rec else 0.0,
                    band_low=band_low,
                    band_high=band_high,
                )
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

        # SmartStop müdahalesi → nokta hız yerine TUTULABİLİR BAND uygula.
        # Gereken hız yumuşatılır (EMA), band min-hold süresince korunur ve
        # ancak büyük sapmada erken yenilenir → sürücüye saniyelik emir gitmez.
        band_factor, band_low, band_high = self._apply_band(vehicle.id, rec.speed_factor, dt)
        # Band tavsiyesi yalnız SERBEST SEYİRDE gösterilir. "approaching"de FSM
        # durağa frenliyor; "60-70 tut" demek yanıltıcı olur (araç uymaz).
        if vehicle.phase != "cruising":
            band_low = band_high = 0.0
        return ControlCommand(
            vehicle_id=vehicle.id,
            hold_time=0.0,
            speed_factor=band_factor,
            skip_stop=False,
            source="smart_stop",
            reason=rec.reason,
            headway_error=headway_error,
            headway_cv=headway_cv,
            eta_to_stop=rec.eta_to_stop,
            ideal_arrival=rec.ideal_arrival,
            queue_time_avoided=rec.queue_time_avoided,
            net_benefit=rec.net_benefit,
            band_low=band_low,
            band_high=band_high,
        )

    # ──────────────────────────────────────────────────────────────
    # Hız Bandı (Sürücü Tavsiyesi) + Histerezis Tutma
    # ──────────────────────────────────────────────────────────────

    def _apply_band(
        self,
        vehicle_id: int,
        needed_speed_factor: float,
        dt: float,
    ) -> Tuple[float, float, float]:
        """Önerilen hızı KARARLI, tutulabilir bir banda çevir.

        Üç katman saniyelik titremeyi engeller:
            1. EMA — gereken hız (needed_factor × max_speed) tick gürültüsünden
               arındırılır. tau = BAND_EMA_TAU_S. Tek tick'lik cost-benefit
               dalgalanması band kenarını kımıldatamaz.
            2. Min-hold — band verildikten sonra BAND_MIN_HOLD_S boyunca
               korunur. Yumuşatılmış hız band dışına çıksa bile küçük sapmalar
               (escape eşiğinin altında) bu süre dolana dek yok sayılır.
            3. Escape — yumuşatılmış hız banttan BAND_ESCAPE_KMH'ten fazla
               saparsa (gerçek bir değişim, gürültü değil) hold beklenmeden
               yeni band verilir.
        Yeni band gereken hıza ORTALANIR (kenara değil) → hemen tekrar çıkmaz.

        Returns:
            (speed_factor, band_low_kmh, band_high_kmh)
        """
        needed_kmh = needed_speed_factor * self.max_speed * _KMH_PER_MS
        now = self._sim_time

        st = self._band_state.get(vehicle_id)

        # ── 1) Gereken hızı yumuşat (EMA) ────────────────────────
        if st is None:
            ema = needed_kmh
        else:
            alpha = dt / (BAND_EMA_TAU_S + dt)
            ema = st["ema"] + alpha * (needed_kmh - st["ema"])

        # ── 2/3) Band'i koru / yenile kararı ─────────────────────
        reissue = False
        if st is None:
            reissue = True
        else:
            inside = st["low"] <= ema <= st["high"]
            if not inside:
                held_long_enough = (now - st["commit_time"]) >= BAND_MIN_HOLD_S
                far_outside = (ema < st["low"] - BAND_ESCAPE_KMH) or \
                              (ema > st["high"] + BAND_ESCAPE_KMH)
                reissue = held_long_enough or far_outside

        if reissue:
            low = max(0.0, _snap_kmh(ema - BAND_WIDTH_KMH / 2.0))
            high = _snap_kmh(ema + BAND_WIDTH_KMH / 2.0)
            if high <= low:
                high = low + BAND_SNAP_KMH
            commit_time = now
        else:
            low, high, commit_time = st["low"], st["high"], st["commit_time"]

        self._band_state[vehicle_id] = {
            "low": low, "high": high,
            "commit_time": commit_time, "ema": ema,
        }

        center_ms = ((low + high) / 2.0) / _KMH_PER_MS
        factor = center_ms / self.max_speed if self.max_speed > 0 else 1.0
        factor = max(MIN_SPEED_FACTOR, min(1.0, factor))
        return factor, low, high

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

        # Güvenlik aracı band ortasının ALTINA çektiyse araç artık tavsiyeye
        # uymuyor (öndeki araç gap'i sıkıştırdı). Yanıltıcı band gösterme.
        if cmd.band_high > 0.0:
            band_center_factor = (
                ((cmd.band_low + cmd.band_high) / 2.0) / _KMH_PER_MS
            ) / self.max_speed if self.max_speed > 0 else 1.0
            if cmd.speed_factor < band_center_factor - 0.05:
                cmd.band_low = 0.0
                cmd.band_high = 0.0

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

        # Dwell expedite önerilerini stop_index -> [drec, ...] olarak grupla
        dwell_by_stop: Dict[int, list] = {}
        for drec in self._last_dwell_map.values():
            dwell_by_stop.setdefault(drec.stop_index, []).append(drec)

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

            # Durakta operasyon yapan araçlar için dwell expedite müdahaleleri
            interventions.extend(
                {
                    "vehicleId": drec.vehicle_id,
                    "speedFactor": 1.0,
                    "reason": "expedite_dwell",
                    "etaToStop": 0.0,
                    "idealArrival": round(drec.target_dwell, 1),
                    "queueTimeSaved": 0.0,
                    "netBenefit": 0.0,
                    "dwellCap": round(drec.dwell_cap, 1),
                    "targetDwell": round(drec.target_dwell, 1),
                }
                for drec in dwell_by_stop.get(idx, [])
            )

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
        self._last_dwell_map = {}
        self._band_state = {}
