"""
MetrobusEnv — Gymnasium uyumlu RL Ortami
Istanbul Metrobus hatti simulasyonu, multi-agent cooperative.

Gercekci ozellikler:
  - Paralel yolcu alim/verim (coklu slot)
  - Kuyruk overflow → double-stop
  - Snowball etkisi (IDM fizigi ile)
  - Seed-kontrollü stochasticity (np_random)

Observation space: Per-agent 24 boyutlu Box
Action space: Per-agent Discrete(4)
Reward: CV-based headway + bunching penalty + dwell/speed
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

import gymnasium as gym
import numpy as np
from gymnasium import spaces

try:
    from .config import DEFAULT_CONFIG, DT, SimConfig, SimVehicle, TrafficZone
    from .demand import DEFAULT_DEMAND, DemandProfile
    from .physics import compute_target_speed, update_vehicle_physics
    from .route_data import LinearRoute, load_route
    from .station_fsm import update_station_fsm, compute_max_buses_at_stop
    from .traffic import check_rush_hour, update_traffic_zones
    from .predictive_engine import (
        BusSnapshot, StopInfo, Decision, PredictiveDecision,
        evaluate_all_buses,
    )
except ImportError:
    from config import DEFAULT_CONFIG, DT, SimConfig, SimVehicle, TrafficZone
    from demand import DEFAULT_DEMAND, DemandProfile
    from physics import compute_target_speed, update_vehicle_physics
    from route_data import LinearRoute, load_route
    from station_fsm import update_station_fsm, compute_max_buses_at_stop
    from traffic import check_rush_hour, update_traffic_zones
    from predictive_engine import (
        BusSnapshot, StopInfo, Decision, PredictiveDecision,
        evaluate_all_buses,
    )


# Observation boyutu per-agent
OBS_DIM = 24

# Action aciklamalari — IDM parametrelerini dogrudan kontrol eder
ACTION_SLOW = 0         # Hedef hiz x 0.6 (yavaslat, bunching onleme)
ACTION_NORMAL = 1       # Hedef hiz x 1.0 (IDM varsayilan)
ACTION_FAST = 2         # Hedef hiz x 1.2 (hizlan, gap kapatma)
ACTION_HOLD = 3         # Durakta 30sn bekle (bunching eritme)
NUM_ACTIONS = 4

# Aksiyon -> hiz carpani eslesmesi
SPEED_FACTORS = {
    ACTION_SLOW: 0.6,
    ACTION_NORMAL: 1.0,
    ACTION_FAST: 1.2,
    ACTION_HOLD: 1.0,    # Hold sirasinda normal hiz, durakta bekler
}

# Hold suresi (saniye) — durakta zorla bekletme
HOLD_DURATION_SECONDS = 15.0

# Reward agirliklari — normalize edilmis, her bilesen [-1, +1] araliginda
W_HEADWAY = 1.0          # Headway duzgunlugu (ana odul, CV-based)
W_BUNCHING = 0.5         # Bunching cezasi (normalize: bunching_count / gap_count)
W_DWELL = 0.1            # Asiri dwell cezasi (normalize: count / vehicle_count)
W_SKIP = 0.0             # Durak atlama kaldirildi (aksiyon yok)
W_SPEED = 0.3            # Hiz bonusu (hedef 40 km/h)

# Bunching mesafe esikleri (metre)
BUNCHING_CRITICAL_M = 100.0
BUNCHING_WARNING_M = 200.0

# Hedef ortalama hiz (m/s)
TARGET_SPEED_MS = 40.0 / 3.6  # 40 km/h -> ~11.1 m/s

# Episode uzunlugu (saniye simulasyon zamani)
MAX_EPISODE_TIME = 7200.0  # 2 saat

# Hedef headway (saniye)
IDEAL_HEADWAY_SECONDS = 180.0

# Uzun bekleme esigi (saniye)
LONG_DWELL_THRESHOLD = 90.0


class MetrobusEnv(gym.Env):
    """
    İstanbul Metrobüs RL Environment.

    Multi-agent ortam: her araç bir ajan.
    Tüm ajanlar aynı global reward'ı paylaşır (cooperative/CTDE).

    Observation:  Dict[agent_id → Box(14,)]
    Action:       Dict[agent_id → Discrete(4)]
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        direction: str = "gidis",
        vehicle_count: int = 15,
        config: Optional[SimConfig] = None,
        max_episode_time: float = MAX_EPISODE_TIME,
        demand: Optional[DemandProfile] = None,
        use_fixed_dwell: bool = False,
        fixed_dwell_seconds: float = 15.0,
        randomize_start_hour: bool = False,
        max_stops: int = 0,
    ):
        super().__init__()

        self.config = config or SimConfig(vehicle_count=vehicle_count)
        self.config.vehicle_count = vehicle_count
        self.direction = direction
        self.max_episode_time = max_episode_time
        self.demand = demand or DEFAULT_DEMAND
        self.use_fixed_dwell = use_fixed_dwell
        self.fixed_dwell_seconds = fixed_dwell_seconds
        self.randomize_start_hour = randomize_start_hour
        self.max_stops = max_stops

        # Rota yukle
        self.route: LinearRoute = load_route(direction, max_stops=max_stops)

        # Gymnasium spaces -- vectorized multi-agent
        # Observation: (vehicle_count, OBS_DIM)
        self.observation_space = spaces.Box(
            low=0.0,
            high=2.0,
            shape=(self.config.vehicle_count, OBS_DIM),
            dtype=np.float32,
        )

        # Action: MultiDiscrete -- bir aksiyon per arac
        self.action_space = spaces.MultiDiscrete(
            [NUM_ACTIONS] * self.config.vehicle_count
        )

        # State
        self.vehicles: list[SimVehicle] = []
        self.traffic_zones: list[TrafficZone] = []
        self.sim_time: float = 0.0
        self.step_count: int = 0
        self._episode_skips: int = 0
        self._episode_bunching: int = 0
        self._start_hour: float = 6.0  # Baslangic saati
        self._predictive_decisions: dict[int, PredictiveDecision] = {}
        self._stop_infos: list[StopInfo] = []  # reset'te doldurulacak

    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[dict] = None,
    ) -> Tuple[np.ndarray, dict]:
        """Simulasyonu sifirla, araclari yerlestir, ilk gozlemi dondur."""
        super().reset(seed=seed)

        self.vehicles = []
        self.traffic_zones = []
        self.sim_time = 0.0
        self.step_count = 0
        self._episode_skips = 0
        self._episode_bunching = 0

        # Baslangic saati: rastgele veya sabit
        if self.randomize_start_hour:
            self._start_hour = 5.0 + self.np_random.random() * 17.0  # 05:00-22:00
        else:
            self._start_hour = 6.0

        # Araçları hat boyunca eşit aralıklarla yerleştir + rastgele jitter
        count = self.config.vehicle_count
        spacing = self.route.total_length / (count + 1)

        for i in range(count):
            # %15 jitter: deterministik baslangici kir
            jitter = (self.np_random.random() - 0.5) * spacing * 0.3
            pos = spacing * (i + 1) + jitter
            pos = max(1.0, min(self.route.total_length - 1.0, pos))

            # Sonraki durak indexini bul
            next_stop_idx = 0
            for si, stop in enumerate(self.route.stops):
                if stop.meter_position > pos:
                    next_stop_idx = si
                    break

            vehicle = SimVehicle(
                id=i,
                position_meters=pos,
                speed=5.0 + self.np_random.random() * 5.0,  # 5-10 m/s
                direction=self.direction,
                next_stop_index=next_stop_idx,
            )
            self.vehicles.append(vehicle)

        obs = self._get_obs()
        info = self._get_info()

        # Predictive engine için stop info'ları hazırla
        self._stop_infos = [
            StopInfo(
                index=i,
                name=s.name,
                position=s.meter_position,
                capacity=compute_max_buses_at_stop(s),
                platform_length=s.platform_length_meters,
            )
            for i, s in enumerate(self.route.stops)
        ]

        return obs, info

    def step(
        self, actions: np.ndarray
    ) -> Tuple[np.ndarray, float, bool, bool, dict]:
        """
        Bir simülasyon adımı.

        Args:
            actions: (vehicle_count,) array, her araç için aksiyon [0,3]

        Returns:
            observation, reward, terminated, truncated, info
        """
        dt = DT
        self.sim_time += dt
        self.step_count += 1

        # Saat hesabi — start_hour ile tutarli
        current_hour = self._start_hour + (self.sim_time / 3600) % 24
        is_rush = check_rush_hour(self.sim_time, start_hour=self._start_hour)

        # 1. RL aksiyonlarını uygula
        for i, vehicle in enumerate(self.vehicles):
            action = int(actions[i]) if i < len(actions) else ACTION_NORMAL
            self._apply_action(vehicle, action)

        # 1.5 Predictive Decision Engine (her step)
        self._run_predictive_engine(is_rush)

        # 2. Trafik bölgelerini güncelle (seed-kontrollü)
        self.traffic_zones = update_traffic_zones(
            self.traffic_zones, dt, self.route.total_length,
            self.config, is_rush, rng=self.np_random,
        )

        # 3. Stokastik pertürbasyonlar — doğal bunching tetikleyicileri
        # Hızı geçici olarak düşür (faz değişimi YAPMA — FSM bozulur)
        for vehicle in self.vehicles:
            if vehicle.phase == "cruising" and float(self.np_random.random()) < 0.003:
                # %0.3 olasılıkla ani yavaşlama (trafik, yolcu vb.)
                vehicle.speed *= 0.3  # Hızı %30'a düşür
                vehicle.acceleration = -2.0  # Sert fren

        # 4. Araçları pozisyona göre sırala
        sorted_vehicles = sorted(self.vehicles, key=lambda v: v.position_meters)

        # 5. Her araç için fizik + durak FSM güncelle
        for idx, vehicle in enumerate(sorted_vehicles):
            # Durak FSM (all_vehicles ile slot/kuyruk kontrolu)
            update_station_fsm(
                vehicle, dt, self.route.stops, self.config, is_rush,
                all_vehicles=sorted_vehicles,
                use_fixed_dwell=self.use_fixed_dwell,
                fixed_dwell_seconds=self.fixed_dwell_seconds,
                rng=self.np_random,
                demand_profile=self.demand,
                current_hour=current_hour,
            )

            # ═══════════════════════════════════════════════════════
            # POZISYON KİLİDİ — statik fazlardaki araçlar hareket etmez
            # ═══════════════════════════════════════════════════════
            if vehicle.phase in ("stopped", "doorsClosed", "queued", "blocked"):
                vehicle.speed = 0.0
                vehicle.acceleration = 0.0
                continue
            if vehicle.phase == "docking":
                # Docking FSM tarafından yönetilir
                continue

            # Hedef hız hesapla
            target_speed = compute_target_speed(
                vehicle,
                self.config,
                self.route.stops,
                self.traffic_zones,
                self.route.total_length,
            )

            # RL aksiyonu: hiz carpanini DOGRUDAN IDM hedef hizina uygula
            speed_factor = getattr(vehicle, '_rl_speed_factor', 1.0)
            target_speed = min(
                self.config.max_speed,
                target_speed * speed_factor,
            )

            # Öndeki araç
            leader = sorted_vehicles[idx + 1] if idx < len(sorted_vehicles) - 1 else None

            # Fizik güncelle
            update_vehicle_physics(vehicle, dt, target_speed, leader, self.config)

            # Hat sonuna ulaştıysa başa dön (circular route)
            if vehicle.position_meters >= self.route.total_length:
                vehicle.position_meters = 0.0
                vehicle.next_stop_index = 0
                vehicle.phase = "cruising"
                vehicle.is_queuing = False
                vehicle.queue_wait_time = 0.0

        # 5. Reward hesapla
        reward, reward_components = self._compute_reward()

        # 6. Bitti mi?
        terminated = False
        truncated = self.sim_time >= self.max_episode_time

        obs = self._get_obs()
        info = self._get_info()
        info["reward_components"] = reward_components

        return obs, reward, terminated, truncated, info

    def _run_predictive_engine(self, is_rush: bool) -> None:
        """
        Predictive Lookahead Decision Engine (CPU versiyonu).
        
        SimVehicle listesinden BusSnapshot çıkarır, tüm otobüsleri
        değerlendirir, SPEED_FILTER kararlarını speed_factor'e yazar.
        """
        if not self._stop_infos:
            return

        # SimVehicle → BusSnapshot dönüşümü
        bus_snapshots = []
        for v in self.vehicles:
            bus_snapshots.append(BusSnapshot(
                bus_id=v.id,
                position=v.position_meters,
                speed=v.speed,
                acceleration=v.acceleration,
                phase=v.phase,
                next_stop_index=v.next_stop_index,
                dwell_remaining=v.dwell_remaining,
                holding_extra=v.holding_extra,
            ))

        # Tüm otobüsleri değerlendir
        decisions = evaluate_all_buses(
            bus_snapshots,
            self._stop_infos,
            is_rush_hour=is_rush,
            approach_distance=self.config.approach_distance,
            comfort_braking=self.config.comfort_braking,
            max_speed=self.config.max_speed,
        )

        # Kararları kaydet
        self._predictive_decisions = decisions

        # SPEED_FILTER kararlarını RL speed_factor üzerine yaz
        for bus_id, dec in decisions.items():
            if dec.decision == Decision.SPEED_FILTER and dec.v_target > 0:
                vehicle = self.vehicles[bus_id]
                if vehicle.speed > 0.01:
                    ratio = dec.v_target / vehicle.speed
                    ratio = max(0.2, min(1.0, ratio))
                    vehicle._rl_speed_factor = ratio  # type: ignore[attr-defined]

    def _apply_action(self, vehicle: SimVehicle, action: int) -> None:
        """RL aksiyonunu araca uygula — IDM parametrelerini dogrudan kontrol eder."""
        # Hiz carpanini ayarla (IDM v0 parametresini etkiler)
        vehicle._rl_speed_factor = SPEED_FACTORS.get(action, 1.0)  # type: ignore[attr-defined]

        # Hold aksiyonu: SADECE sonraki durakta uzun bekle
        # Durakta ise dwell uzatmaz — yoksa random policy araclari sonsuza kadar durdurur
        if action == ACTION_HOLD:
            if vehicle.phase not in ("stopped", "doorsClosed", "blocked"):
                vehicle.holding_extra = max(vehicle.holding_extra, HOLD_DURATION_SECONDS)

    def _get_obs(self) -> np.ndarray:
        """
        Tüm araçlar için gözlem vektörünü oluştur.

        Per-agent 22 boyutlu:
        [0]  norm_position      - hat pozisyonu / uzunluk [0,1]
        [1]  norm_speed         - hız / maxSpeed [0,1]
        [2]  dist_to_leader     - öndeki araca mesafe / uzunluk [0,1]
        [3]  dist_to_follower   - arkadaki araca mesafe / uzunluk [0,1]
        [4]  last_dwell_time    - son dwell / maxDwell [0,1]
        [5]  time_sin           - sin(2π·saat/24)
        [6]  time_cos           - cos(2π·saat/24)
        [7]  is_rush_hour       - 0 veya 1
        [8]  phase_cruising     - one-hot
        [9]  phase_approaching  - one-hot
        [10] phase_stopped      - one-hot
        [11] phase_departing    - one-hot
        [12] next_stop_dist     - sonraki durağa mesafe / approachDistance [0,1]
        [13] norm_acceleration  - ivme / emergency_braking [-1,1]
        --- YENİ PARAMETRELER ---
        [14] leader_speed       - öndeki aracın hızı / maxSpeed [0,1]
        [15] follower_speed     - arkadaki aracın hızı / maxSpeed [0,1]
        [16] leader_stopped     - öndeki araç durakta mı [0,1]
        [17] follower_stopped   - arkadaki araç durakta mı [0,1]
        [18] next_stop_queue    - sonraki duraktaki araç sayısı / max [0,1]
        [19] prev_stop_dist     - önceki durağa mesafe (normalize) [0,1]
        [20] second_next_dist   - 2. sonraki durağa mesafe (normalize) [0,1]
        [21] episode_progress   - simülasyon zamanı / max zaman [0,1]
        [22] next_stop_slots    - durak slot kapasitesi / 6 [0,1]
        [23] slot_occupancy     - kuyruk/kapasite oranı (>1 = taşma) [0,2]
        """
        route_len = self.route.total_length
        max_spd = max(self.config.max_speed, 0.01)
        obs = np.zeros((self.config.vehicle_count, OBS_DIM), dtype=np.float32)

        # Pozisyona göre sırala (mesafe hesapları için)
        sorted_positions = sorted(
            range(len(self.vehicles)),
            key=lambda i: self.vehicles[i].position_meters,
        )

        # Pozisyon → index eşlemesi
        pos_rank = {vid: rank for rank, vid in enumerate(sorted_positions)}

        # Saat hesapla
        hour_of_day = self._start_hour + (self.sim_time / 3600) % 24
        time_sin = math.sin(2 * math.pi * hour_of_day / 24)
        time_cos = math.cos(2 * math.pi * hour_of_day / 24)
        is_rush = 1.0 if check_rush_hour(self.sim_time, start_hour=self._start_hour) else 0.0
        episode_progress = min(self.sim_time / max(self.max_episode_time, 1.0), 1.0)

        # Sonraki durak basina arac sayisini onceden hesapla
        stop_vehicle_counts: dict[int, int] = {}
        for v in self.vehicles:
            if v.phase in ("stopped", "doorsClosed", "blocked", "docking", "approaching", "queued"):
                si = v.next_stop_index
                stop_vehicle_counts[si] = stop_vehicle_counts.get(si, 0) + 1

        for i, vehicle in enumerate(self.vehicles):
            rank = pos_rank[i]

            # Öndeki araca mesafe ve bilgileri
            leader_speed = 0.0
            leader_stopped = 0.0
            if rank < len(sorted_positions) - 1:
                leader_idx = sorted_positions[rank + 1]
                leader_v = self.vehicles[leader_idx]
                dist_leader = leader_v.position_meters - vehicle.position_meters
                leader_speed = leader_v.speed / max_spd
                leader_stopped = 1.0 if leader_v.phase in ("stopped", "doorsClosed", "blocked") else 0.0
            else:
                dist_leader = route_len

            # Arkadaki araca mesafe ve bilgileri
            follower_speed = 0.0
            follower_stopped = 0.0
            if rank > 0:
                follower_idx = sorted_positions[rank - 1]
                follower_v = self.vehicles[follower_idx]
                dist_follower = vehicle.position_meters - follower_v.position_meters
                follower_speed = follower_v.speed / max_spd
                follower_stopped = 1.0 if follower_v.phase in ("stopped", "doorsClosed", "blocked") else 0.0
            else:
                dist_follower = route_len

            # Sonraki durağa mesafe
            nsi = vehicle.next_stop_index
            if nsi < len(self.route.stops):
                next_stop_dist = (
                    self.route.stops[nsi].meter_position - vehicle.position_meters
                )
            else:
                next_stop_dist = 0.0

            # Önceki durağa mesafe
            if nsi > 0:
                prev_stop_dist = (
                    vehicle.position_meters - self.route.stops[nsi - 1].meter_position
                )
            else:
                prev_stop_dist = vehicle.position_meters

            # 2. sonraki durağa mesafe
            if nsi + 1 < len(self.route.stops):
                second_next_dist = (
                    self.route.stops[nsi + 1].meter_position - vehicle.position_meters
                )
            else:
                second_next_dist = route_len - vehicle.position_meters

            # Sonraki duraktaki kuyruk ve slot kapasitesi
            next_stop_queue = stop_vehicle_counts.get(nsi, 0)
            max_queue = max(3, len(self.vehicles) // len(self.route.stops)) if self.route.stops else 3

            # Slot kapasitesi
            if nsi < len(self.route.stops):
                slot_capacity = compute_max_buses_at_stop(self.route.stops[nsi])
            else:
                slot_capacity = 1
            slot_occupancy = next_stop_queue / max(slot_capacity, 1)  # >1 = taşma!

            # Phase one-hot (8 faz → 4 gruba daralt: OBS uyumluluk)
            phase_vec = [0.0, 0.0, 0.0, 0.0]
            phase_map = {
                "cruising": 0,
                "approaching": 1, "queued": 1, "docking": 1,    # approaching group
                "stopped": 2, "doorsClosed": 2, "blocked": 2,   # stopped group
                "departing": 3,
            }
            phase_vec[phase_map.get(vehicle.phase, 0)] = 1.0

            obs[i] = [
                vehicle.position_meters / route_len,                                    # [0]
                vehicle.speed / max_spd,                                                # [1]
                min(dist_leader / route_len, 1.0),                                      # [2]
                min(dist_follower / route_len, 1.0),                                    # [3]
                vehicle.last_dwell_time / max(self.config.max_dwell_time, 1.0),        # [4]
                time_sin,                                                                # [5]
                time_cos,                                                                # [6]
                is_rush,                                                                 # [7]
                phase_vec[0],                                                            # [8]
                phase_vec[1],                                                            # [9]
                phase_vec[2],                                                            # [10]
                phase_vec[3],                                                            # [11]
                min(max(next_stop_dist, 0) / max(self.config.approach_distance, 1), 1),  # [12]
                vehicle.acceleration / max(self.config.emergency_braking, 0.01),         # [13]
                # --- YENİ ---
                leader_speed,                                                            # [14]
                follower_speed,                                                          # [15]
                leader_stopped,                                                          # [16]
                follower_stopped,                                                        # [17]
                min(next_stop_queue / max_queue, 1.0),                                   # [18]
                min(max(prev_stop_dist, 0) / route_len, 1.0),                           # [19]
                min(max(second_next_dist, 0) / route_len, 1.0),                         # [20]
                episode_progress,                                                        # [21]
                min(slot_capacity / 6.0, 1.0),                                           # [22]
                min(slot_occupancy, 2.0) / 2.0,                                          # [23]
            ]

        return obs

    def get_global_obs(self) -> np.ndarray:
        """
        Tum araclarin gozlemlerini birlestir (Critic icin).
        CTDE: Centralized Training, Decentralized Execution.

        Returns: (vehicle_count * OBS_DIM,) flat array
        """
        obs = self._get_obs()
        return obs.flatten()

    def _compute_reward(self) -> Tuple[float, dict]:
        """
        Cooperative reward — NORMALIZED.
        Her bilesen [-1, +1] araliginda, toplam per-step: yaklasik [-2, +2].
        Returns: (total_reward, components_dict)

        Düzeltmeler:
          - Durmus araclar icin mesafe bazli headway (IDEAL_HEADWAY yerine)
          - Hiz reward: Gaussian formul (durmus != ideal hiz)
        """
        num_vehicles = len(self.vehicles)
        if num_vehicles < 2:
            return 0.0, {}

        # --- Pozisyonlara gore sirala ---
        sorted_vehicles = sorted(
            self.vehicles, key=lambda v: v.position_meters
        )

        gaps = []
        headways = []
        bunching_count = 0

        for i in range(len(sorted_vehicles) - 1):
            gap = (
                sorted_vehicles[i + 1].position_meters
                - sorted_vehicles[i].position_meters
            )
            gaps.append(gap)

            # Headway (zaman)
            avg_speed = (sorted_vehicles[i].speed + sorted_vehicles[i + 1].speed) / 2
            if avg_speed > 0.5:
                headways.append(gap / avg_speed)
            else:
                # Durmus araclar: mesafe bazli headway (hedef hiz uzerinden)
                # ESKI: IDEAL_HEADWAY_SECONDS → model "dur" stratejisi ogreniyordu
                headways.append(gap / max(TARGET_SPEED_MS, 1.0))

            # Bunching say
            if gap < BUNCHING_CRITICAL_M:
                bunching_count += 1
                self._episode_bunching += 1
            elif gap < BUNCHING_WARNING_M:
                bunching_count += 0.5  # Uyari: yarim ceza

        num_gaps = max(len(gaps), 1)

        # 1. Headway duzgunlugu [-1, +1]
        cv = 0.0
        r_headway = 0.0
        if len(headways) > 1:
            headway_mean = float(np.mean(headways))
            headway_std = float(np.std(headways))
            if headway_mean > 0:
                cv = headway_std / headway_mean
                r_headway = max(1.0 - cv, -1.0) * W_HEADWAY

        # 2. Bunching orani [-0.5, 0]
        bunching_ratio = bunching_count / num_gaps
        r_bunching = -bunching_ratio * W_BUNCHING

        # 3. Durak atlama [-0.1, 0]
        skip_count = sum(1 for v in self.vehicles if v.skip_next_stop)
        skip_ratio = skip_count / num_vehicles
        r_skip = -skip_ratio * W_SKIP

        # 4. Asiri dwell [-0.1, 0] — sadece gercekten durakta olanlar
        long_dwell_count = sum(
            1 for v in self.vehicles
            if v.phase in ("stopped", "doorsClosed", "blocked") and not v.is_queuing
            and v.dwell_remaining > LONG_DWELL_THRESHOLD
        )
        dwell_ratio = long_dwell_count / num_vehicles
        r_dwell = -dwell_ratio * W_DWELL

        # 5. Hiz reward — Gaussian formul
        # 0 hiz = dusuk reward, hedef hiz = max reward, cok hizli = dusuk reward
        avg_speed = float(np.mean([v.speed for v in self.vehicles]))
        speed_ratio = avg_speed / max(TARGET_SPEED_MS, 0.01)
        r_speed = W_SPEED * math.exp(-2.0 * (speed_ratio - 1.0) ** 2)

        total = r_headway + r_bunching + r_skip + r_dwell + r_speed

        components = {
            "r_headway": r_headway,
            "r_bunching": r_bunching,
            "r_skip": r_skip,
            "r_dwell": r_dwell,
            "r_speed": r_speed,
            "bunching_count": bunching_count,
            "avg_speed_ms": avg_speed,
            "headway_cv": cv,
            "min_gap": min(gaps) if gaps else 0.0,
        }

        return float(total), components

    def _get_info(self) -> dict:
        """Debug/monitoring bilgisi."""
        speeds = [v.speed for v in self.vehicles]
        positions = sorted([v.position_meters for v in self.vehicles])

        gaps = []
        for i in range(len(positions) - 1):
            gaps.append(positions[i + 1] - positions[i])

        # Headway std (loglama icin)
        headway_std = 0.0
        if gaps:
            headway_times = []
            sorted_v = sorted(self.vehicles, key=lambda v: v.position_meters)
            for i in range(len(sorted_v) - 1):
                avg_s = (sorted_v[i].speed + sorted_v[i + 1].speed) / 2
                if avg_s > 0.5:
                    headway_times.append(gaps[i] / avg_s)
            if headway_times:
                headway_std = float(np.std(headway_times))

        return {
            "sim_time": self.sim_time,
            "step_count": self.step_count,
            "avg_speed_ms": float(np.mean(speeds)) if speeds else 0.0,
            "avg_speed_kmh": float(np.mean(speeds)) * 3.6 if speeds else 0.0,
            "min_gap_m": float(min(gaps)) if gaps else 0.0,
            "max_gap_m": float(max(gaps)) if gaps else 0.0,
            "avg_gap_m": float(np.mean(gaps)) if gaps else 0.0,
            "headway_std": headway_std,
            "num_stopped": sum(1 for v in self.vehicles if v.phase in ("stopped", "doorsClosed", "blocked")),
            "episode_skips": self._episode_skips,
            "episode_bunching": self._episode_bunching,
            "is_rush_hour": check_rush_hour(self.sim_time, start_hour=self._start_hour),
            "traffic_zones": len(self.traffic_zones),
            "predictive_engine": {
                "speed_filter_count": sum(
                    1 for d in self._predictive_decisions.values()
                    if d.decision == Decision.SPEED_FILTER
                ),
                "bunching_accept_count": sum(
                    1 for d in self._predictive_decisions.values()
                    if d.decision == Decision.BUNCHING_ACCEPT
                ),
            },
        }
