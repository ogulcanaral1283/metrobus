"""
Simülasyon Motoru — CPU Tabanlı Analitik Kontrol Simülasyonu
==============================================================

Tüm parçaları (fizik, FSM, talep, kontrol motoru) orkestre eder.

Her tick (dt = 0.1 sn):
    1. Kontrolcü → hold_time, speed_factor, skip per vehicle
    2. Fizik → IDM ivme + pozisyon güncelleme (speed_factor uygulanmış)
    3. FSM → durak state transitions (hold_time uygulanmış)
    4. Metrikler → headway CV, bunching, throughput kaydı

Simülasyon:
    - CPU single-thread (Python for-loop)
    - 15 araç × 31 durak × 3600s = 36,000 step → ~5-10 sn
    - Amacı: kontrol motorunun doğrulanması, dashboard gösterimi
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

try:
    from ..config import SimConfig, SimVehicle, TrafficZone, DEFAULT_CONFIG, VEHICLE_LENGTH, DT
    from ..route_data import LinearRoute, LinearStop, load_route
    from ..physics import compute_target_speed, update_vehicle_physics
    from ..station_fsm import update_station_fsm
    from ..demand import DemandProfile, DEFAULT_DEMAND
    from ..traffic import update_traffic_zones
    from ..controller import ControlMerger, ControlCommand
    from ..controller.headway_model import HeadwayModel
    from ..controller.pid_controller import PIDController
    from ..controller.lookahead_optimizer import LookaheadOptimizer
except ImportError:
    from config import SimConfig, SimVehicle, TrafficZone, DEFAULT_CONFIG, VEHICLE_LENGTH, DT
    from route_data import LinearRoute, LinearStop, load_route
    from physics import compute_target_speed, update_vehicle_physics
    from station_fsm import update_station_fsm
    from demand import DemandProfile, DEFAULT_DEMAND
    from traffic import update_traffic_zones
    from controller import ControlMerger, ControlCommand
    from controller.headway_model import HeadwayModel
    from controller.pid_controller import PIDController
    from controller.lookahead_optimizer import LookaheadOptimizer


# ═══════════════════════════════════════════
# Veri Yapıları
# ═══════════════════════════════════════════

@dataclass
class StepResult:
    """Tek step sonucu."""
    step: int
    sim_time: float             # simülasyon zamanı (sn)
    headway_cv: float           # headway varyasyon katsayısı
    bunching_pairs: int         # yığılma çifti sayısı
    mean_headway: float         # ortalama headway (sn)
    avg_speed_kmh: float        # ortalama hız (km/h)
    num_stopped: int            # durakta araç sayısı
    num_queued: int             # kuyrukta bekleyen araç sayısı
    active_holds: int           # aktif hold komutu sayısı
    active_filters: int         # aktif hız filtreleme sayısı
    active_skips: int           # aktif durak atlama sayısı


@dataclass
class SimulationResult:
    """Toplam simülasyon sonucu."""
    duration_seconds: float     # simüle edilen süre (sn)
    wall_time_seconds: float    # gerçek çalışma süresi (sn)
    num_vehicles: int
    num_stops: int
    route_length: float

    # Toplam metrikler
    avg_headway_cv: float       # ortalama CV
    avg_bunching_pairs: float   # ortalama yığılma çifti
    avg_speed_kmh: float        # ortalama hız
    total_holds: int            # toplam hold uygulaması
    total_skips: int            # toplam durak atlama

    # Zaman serisi
    step_results: List[StepResult] = field(default_factory=list)

    # Kontrolcü bilgisi
    pid_gains: dict = field(default_factory=dict)
    target_headway: float = 0.0


# ═══════════════════════════════════════════
# Simülasyon Motoru
# ═══════════════════════════════════════════

class SimulationEngine:
    """
    CPU tabanlı simülasyon orkestratörü.

    Kullanım:
        engine = SimulationEngine(vehicle_count=15)
        result = engine.run(duration_seconds=3600)
        print(f"CV: {result.avg_headway_cv:.3f}")
    """

    def __init__(
        self,
        vehicle_count: int = 15,
        direction: str = "gidis",
        max_stops: int = 0,
        config: SimConfig | None = None,
        start_hour: float = 7.0,
        enable_controller: bool = True,
        seed: int = 42,
        # PID kazançları (None = auto-tune)
        pid_kp: float | None = None,
        pid_ki: float | None = None,
        pid_kd: float | None = None,
        # Lookahead parametreleri
        lookahead_horizon: int = 3,
        lookahead_interval: int = 50,
    ):
        self.config = config or DEFAULT_CONFIG
        self.config.vehicle_count = vehicle_count
        self.direction = direction
        self.start_hour = start_hour
        self.enable_controller = enable_controller
        self.rng = np.random.default_rng(seed)

        # Rota yükle
        self.route = load_route(direction, max_stops)
        self.stops = self.route.stops
        self.route_length = self.route.total_length
        self.num_stops = len(self.stops)

        # Araçları oluştur — eşit aralıklı dağılım
        self.vehicles = self._create_vehicles(vehicle_count)

        # Trafik bölgeleri
        self.traffic_zones: List[TrafficZone] = []

        # Talep profili
        self.demand = DEFAULT_DEMAND

        # Simülasyon zamanı
        self.sim_time = 0.0
        self.dt = DT
        self.step_count = 0

        # ─── Kontrolcü oluştur ───
        if enable_controller:
            cruise_speed = self.config.max_speed * 0.7
            self.headway_model = HeadwayModel(
                route_length=self.route_length,
                num_vehicles=vehicle_count,
                cruise_speed=cruise_speed,
                perturbation_alpha=0.3,
                vehicle_length=VEHICLE_LENGTH,
            )

            # PID kazançları
            if pid_kp is not None and pid_ki is not None and pid_kd is not None:
                kp, ki, kd = pid_kp, pid_ki, pid_kd
            else:
                # Auto-tune
                from ..controller.tuning import auto_tune
                tuning = auto_tune(0.3, self.headway_model.target_headway, self.dt)
                kp, ki, kd = tuning.kp, tuning.ki, tuning.kd

            self.pid = PIDController(
                kp=kp, ki=ki, kd=kd,
                dt=self.dt, u_max=60.0,
            )

            self.lookahead = LookaheadOptimizer(
                horizon=lookahead_horizon,
                max_speed=self.config.max_speed,
                comfort_braking=self.config.comfort_braking,
            )

            self.controller = ControlMerger(
                headway_model=self.headway_model,
                pid=self.pid,
                lookahead=self.lookahead,
                lookahead_interval=lookahead_interval,
                min_gap=25.0,
                vehicle_length=VEHICLE_LENGTH,
            )
        else:
            self.controller = None

        # Headway gözlem modeli — kontrolcü olmasa da metrik hesaplamak için
        cruise_speed = self.config.max_speed * 0.7
        self._observer_headway = HeadwayModel(
            route_length=self.route_length,
            num_vehicles=vehicle_count,
            cruise_speed=cruise_speed,
            perturbation_alpha=0.3,
            vehicle_length=VEHICLE_LENGTH,
        )

    def _create_vehicles(self, count: int) -> List[SimVehicle]:
        """Araçları hat boyunca eşit aralıklı dağıt."""
        gap = self.route_length / count
        vehicles = []
        for i in range(count):
            pos = i * gap
            vehicles.append(SimVehicle(
                id=i,
                position_meters=pos,
                speed=self.config.max_speed * 0.5,  # yarı hızla başla
                direction=self.direction,
            ))
        return vehicles

    def step(self) -> StepResult:
        """
        Tek simülasyon adımı.

        Returns:
            StepResult — bu adımın metrikleri
        """
        dt = self.dt
        current_hour = self.start_hour + self.sim_time / 3600.0
        is_rush = 7.0 <= current_hour <= 9.5 or 17.0 <= current_hour <= 19.5

        # ─── 1. Kontrolcü ───
        commands: dict[int, ControlCommand] = {}
        active_holds = 0
        active_filters = 0
        active_skips = 0

        if self.controller is not None:
            cmd_list = self.controller.compute(
                self.vehicles, self.stops,
                dt=dt, is_rush_hour=is_rush, current_hour=current_hour,
            )
            for cmd in cmd_list:
                commands[cmd.vehicle_id] = cmd
                if cmd.hold_time > 0:
                    active_holds += 1
                if cmd.speed_factor < 0.95:
                    active_filters += 1
                if cmd.skip_stop:
                    active_skips += 1

        # ─── 2. Trafik güncellemesi ───
        self.traffic_zones = update_traffic_zones(
            self.traffic_zones, dt, self.route_length,
            self.config, is_rush, self.rng,
        )

        # ─── 3. Her araç için fizik + FSM ───
        # Pozisyona göre sırala (IDM leader hesabı için)
        sorted_vehicles = sorted(self.vehicles, key=lambda v: v.position_meters)

        for veh in self.vehicles:
            # Kontrolcü komutlarını uygula
            cmd = commands.get(veh.id)
            if cmd:
                # Hold: FSM'deki holding_extra'ya yaz
                if cmd.hold_time > 0 and veh.phase in ("stopped", "doorsClosed"):
                    veh.holding_extra = max(veh.holding_extra, cmd.hold_time)

                # Skip
                if cmd.skip_stop:
                    veh.skip_next_stop = True

            # Hedef hız hesapla
            target_speed = compute_target_speed(
                veh, self.config, self.stops,
                self.traffic_zones, self.route_length,
            )

            # Speed factor uygula
            if cmd and cmd.speed_factor < 1.0:
                target_speed *= cmd.speed_factor

            # Leader bul
            leader = self._find_leader(veh, sorted_vehicles)

            # Fizik güncelle
            update_vehicle_physics(veh, dt, target_speed, leader, self.config)

            # FSM güncelle
            update_station_fsm(
                veh, dt, self.stops, self.config,
                is_rush_hour=is_rush,
                all_vehicles=self.vehicles,
                rng=self.rng,
                demand_profile=self.demand,
                current_hour=current_hour,
            )

            # Wrap-around: hat sonuna ulaştıysa başa dön
            if veh.position_meters >= self.route_length:
                veh.position_meters -= self.route_length
                veh.next_stop_index = 0

        # ─── 4. Metrikler ───
        self.sim_time += dt
        self.step_count += 1

        # Hız istatistikleri
        cruising = [v for v in self.vehicles if v.phase in ("cruising", "approaching", "departing")]
        avg_speed = (
            sum(v.speed for v in cruising) / max(len(cruising), 1)
        ) * 3.6  # m/s → km/h

        stopped = sum(1 for v in self.vehicles if v.phase in ("stopped", "doorsClosed", "blocked"))
        queued = sum(1 for v in self.vehicles if v.phase == "queued")

        # Headway metrikleri (her zaman hesapla)
        hs = self._observer_headway.compute(self.vehicles, dt)
        metrics = self._observer_headway.compute_fleet_metrics(hs)
        cv = metrics["cv"]
        bunching = metrics["bunching_pairs"]
        mean_h = metrics["mean_headway"]

        return StepResult(
            step=self.step_count,
            sim_time=self.sim_time,
            headway_cv=cv,
            bunching_pairs=bunching,
            mean_headway=mean_h,
            avg_speed_kmh=avg_speed,
            num_stopped=stopped,
            num_queued=queued,
            active_holds=active_holds,
            active_filters=active_filters,
            active_skips=active_skips,
        )

    def run(
        self,
        duration_seconds: float = 3600.0,
        report_interval: float = 60.0,
        verbose: bool = True,
    ) -> SimulationResult:
        """
        Belirtilen süre boyunca simülasyon çalıştır.

        Args:
            duration_seconds: Simüle edilecek süre (sn)
            report_interval:  Konsola raporlama aralığı (sn)
            verbose:          Konsol çıktısı

        Returns:
            SimulationResult — toplam metrikler ve zaman serisi
        """
        total_steps = int(duration_seconds / self.dt)
        report_every = int(report_interval / self.dt)

        if verbose:
            target_h = self.controller.headway_model.target_headway if self.controller else 0
            print(f"[BUS] Metrobus Simulasyonu Basliyor")
            print(f"   {len(self.vehicles)} arac x {self.num_stops} durak x {self.route_length:.0f}m")
            print(f"   Hedef headway: {target_h:.0f}s ({target_h/60:.1f}dk)")
            print(f"   Kontrolcu: {'AKTIF' if self.enable_controller else 'DEVRE DISI'}")
            if self.controller:
                gains = self.controller.pid.get_gains()
                print(f"   PID: Kp={gains['kp']:.4f}, Ki={gains['ki']:.4f}, Kd={gains['kd']:.4f}")
            print(f"   Sure: {duration_seconds:.0f}s ({duration_seconds/60:.0f}dk)")
            print("-" * 60)

        wall_start = time.time()
        step_results: List[StepResult] = []
        total_holds = 0
        total_skips = 0

        for step_i in range(total_steps):
            result = self.step()

            # Her 10 step'te bir kayıt (bellek tasarrufu)
            if step_i % 10 == 0:
                step_results.append(result)

            total_holds += result.active_holds
            total_skips += result.active_skips

            # Periyodik rapor
            if verbose and step_i > 0 and step_i % report_every == 0:
                print(
                    f"  t={result.sim_time:6.0f}s | "
                    f"CV={result.headway_cv:.3f} | "
                    f"bunch={result.bunching_pairs} | "
                    f"spd={result.avg_speed_kmh:.1f}km/h | "
                    f"hold={result.active_holds} filt={result.active_filters}"
                )

        wall_elapsed = time.time() - wall_start

        # Toplam istatistikler
        if step_results:
            avg_cv = sum(r.headway_cv for r in step_results) / len(step_results)
            avg_bunch = sum(r.bunching_pairs for r in step_results) / len(step_results)
            avg_spd = sum(r.avg_speed_kmh for r in step_results) / len(step_results)
        else:
            avg_cv = avg_bunch = avg_spd = 0.0

        target_h = self.controller.headway_model.target_headway if self.controller else 0.0
        pid_gains = self.controller.pid.get_gains() if self.controller else {}

        if verbose:
            print("-" * 60)
            print(f"[OK] Simulasyon Tamamlandi ({wall_elapsed:.1f}s)")
            print(f"   Ort. Headway CV:  {avg_cv:.3f}")
            print(f"   Ort. Bunching:    {avg_bunch:.1f} cift")
            print(f"   Ort. Hiz:         {avg_spd:.1f} km/h")
            print(f"   Toplam Hold:      {total_holds}")
            print(f"   Toplam Skip:      {total_skips}")

        return SimulationResult(
            duration_seconds=duration_seconds,
            wall_time_seconds=wall_elapsed,
            num_vehicles=len(self.vehicles),
            num_stops=self.num_stops,
            route_length=self.route_length,
            avg_headway_cv=avg_cv,
            avg_bunching_pairs=avg_bunch,
            avg_speed_kmh=avg_spd,
            total_holds=total_holds,
            total_skips=total_skips,
            step_results=step_results,
            pid_gains=pid_gains,
            target_headway=target_h,
        )

    def _find_leader(
        self,
        vehicle: SimVehicle,
        sorted_vehicles: List[SimVehicle],
    ) -> Optional[SimVehicle]:
        """Öndeki en yakın aracı bul."""
        best = None
        best_dist = float("inf")

        for v in sorted_vehicles:
            if v.id == vehicle.id:
                continue
            dist = v.position_meters - vehicle.position_meters
            if dist < 0:
                # Wrap-around
                dist += self.route_length
            if dist < best_dist and dist > 0:
                best_dist = dist
                best = v

        return best

    def get_vehicle_states(self) -> List[dict]:
        """Dashboard için araç durumlarını döndür."""
        return [
            {
                "id": v.id,
                "position": v.position_meters,
                "speed": v.speed,
                "speed_kmh": v.speed * 3.6,
                "phase": v.phase,
                "next_stop": v.next_stop_index,
                "dwell_remaining": v.dwell_remaining,
                "holding_extra": v.holding_extra,
                "total_stops": v.total_stops,
            }
            for v in self.vehicles
        ]

    def reset(self, seed: int | None = None) -> None:
        """Simülasyonu sıfırla."""
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        self.vehicles = self._create_vehicles(len(self.vehicles))
        self.sim_time = 0.0
        self.step_count = 0
        self.traffic_zones = []
        if self.controller:
            self.controller.reset()
