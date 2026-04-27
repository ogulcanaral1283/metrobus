"""
GpuMetrobusEnv — Vectorized (Batched) GPU-native PyTorch Metrobus Simulasyon Ortami

B paralel ortam × N araç = (B, N) tensörler → GPU'yu doyurur.
Tüm state CUDA tensörlerinde, Python for-loop YOK.
"""

from __future__ import annotations

import math
from typing import Any, Optional, Tuple

import numpy as np
import torch

try:
    from .config import DEFAULT_CONFIG, DT, SimConfig
    from .route_data import LinearRoute, LinearStop, load_route
    from .station_fsm import compute_max_buses_at_stop
    from .predictive_engine import (
        BusSnapshot, StopInfo, Decision, PredictiveDecision,
        evaluate_all_buses,
    )
except ImportError:
    from config import DEFAULT_CONFIG, DT, SimConfig
    from route_data import LinearRoute, LinearStop, load_route
    from station_fsm import compute_max_buses_at_stop
    from predictive_engine import (
        BusSnapshot, StopInfo, Decision, PredictiveDecision,
        evaluate_all_buses,
    )

# =============================================
# Sabitler
# =============================================
OBS_DIM = 24
NUM_ACTIONS = 4
ACTION_SLOW = 0
ACTION_NORMAL = 1
ACTION_FAST = 2
ACTION_HOLD = 3

SPEED_FACTOR_MAP = torch.tensor([0.6, 1.0, 1.2, 1.0])

HOLD_DURATION_SECONDS = 15.0
VEHICLE_LENGTH = 20.0  # TS VEHICLE_TYPES ile senkron (Mercedes-Benz Citaro)

# Reward parametreleri
W_HEADWAY = 2.0              # Ana sinyal — headway düzeni
W_BUNCHING = 0.3             # Yapışma cezası (düşürüldü — çok baskındı)
W_DWELL = 0.1
W_SPEED = 0.3
BUNCHING_CRITICAL_M = 50.0   # 50m altı = kritik  (eskiden 100m)
BUNCHING_WARNING_M = 100.0   # 100m altı = uyarı  (eskiden 200m — 200 araçta her çift uyarıydı)
TARGET_SPEED_MS = 40.0 / 3.6
MAX_EPISODE_TIME = 7200.0
LONG_DWELL_THRESHOLD = 90.0

# FSM faz kodlari (8 faz — TypeScript ile uyumlu)
CRUISING = 0
APPROACHING = 1
QUEUED = 2
DOCKING = 3
STOPPED = 4
DOORS_CLOSED = 5
BLOCKED = 6
DEPARTING = 7

# Güvenli kalkış mesafesi (metre)
SAFE_GAP = 0.5


class GpuMetrobusEnv:
    """
    Vectorized GPU-native Metrobus RL Environment.
    B paralel ortam × N araç — tüm tensörler (B, N) boyutlu.
    """

    def __init__(
        self,
        vehicle_count: int = 15,
        device: str = "cuda",
        direction: str = "gidis",
        config: Optional[SimConfig] = None,
        max_episode_time: float = MAX_EPISODE_TIME,
        max_stops: int = 0,
        num_envs: int = 32,
        reward_config: Optional[dict] = None,
    ):
        self.device = torch.device(device if torch.cuda.is_available() else "cpu")
        self.N = vehicle_count
        self.B = num_envs
        self.direction = direction
        self.config = config or SimConfig(vehicle_count=vehicle_count)
        self.config.vehicle_count = vehicle_count
        self.max_episode_time = max_episode_time
        self.dt = DT

        # Reward parametreleri (config'den okunur, varsayilan modül sabitleri)
        rc = reward_config or {}
        self._w_headway = rc.get("headway_weight", W_HEADWAY)
        self._w_bunching = abs(rc.get("bunching_penalty", W_BUNCHING))  # negatifse pozitife cevir
        self._w_dwell = abs(rc.get("dwell_penalty", W_DWELL))
        self._w_speed = rc.get("speed_weight", W_SPEED)
        self._target_speed_ms = rc.get("target_speed_kmh", 40.0) / 3.6

        # Rota yukle
        self.route: LinearRoute = load_route(direction, max_stops=max_stops)
        self.route_length = self.route.total_length
        self.num_stops = len(self.route.stops)
        S = self.num_stops

        dev = self.device

        # Statik veriler → GPU (değişmez)
        self.stop_positions = torch.tensor(
            [s.meter_position for s in self.route.stops],
            dtype=torch.float32, device=dev,
        )  # (S,)
        self.stop_max_buses = torch.tensor(
            [compute_max_buses_at_stop(s) for s in self.route.stops],
            dtype=torch.long, device=dev,
        )  # (S,)
        self.stop_platform_lengths = torch.clamp(
            torch.tensor(
                [s.platform_length_meters for s in self.route.stops],
                dtype=torch.float32, device=dev,
            ),
            min=40.0,  # platform_length=0 olan duraklar icin varsayilan 40m
        )  # (S,)

        # Speed factor map
        self._speed_factors = SPEED_FACTOR_MAP.to(dev)

        # IDM sabitleri
        self._a_max = self.config.max_acceleration
        self._b_comfort = self.config.comfort_braking
        self._b_emergency = self.config.emergency_braking
        self._max_speed = self.config.max_speed
        self._s0 = self.config.idm_min_gap
        self._T = self.config.idm_time_headway
        self._idm_delta = self.config.idm_delta
        self._approach_dist = self.config.approach_distance
        self._default_speed_limit = self.config.default_speed_limit
        self._sqrt_ab = math.sqrt(self._a_max * self._b_comfort)

        # Pre-allocated constant tensors (CUDA alloc overhead = 0)
        self._ZERO_F = torch.tensor(0.0, device=dev)
        self._ZERO_L = torch.tensor(0, dtype=torch.long, device=dev)
        self._FALSE = torch.tensor(False, device=dev)
        self._TRUE = torch.tensor(True, device=dev)
        self._NEG2 = torch.tensor(-2.0, device=dev)
        self._CRUISING_T = torch.tensor(CRUISING, dtype=torch.long, device=dev)
        self._APPROACHING_T = torch.tensor(APPROACHING, dtype=torch.long, device=dev)
        self._QUEUED_T = torch.tensor(QUEUED, dtype=torch.long, device=dev)
        self._DOCKING_T = torch.tensor(DOCKING, dtype=torch.long, device=dev)
        self._STOPPED_T = torch.tensor(STOPPED, dtype=torch.long, device=dev)
        self._DOORS_CLOSED_T = torch.tensor(DOORS_CLOSED, dtype=torch.long, device=dev)
        self._BLOCKED_T = torch.tensor(BLOCKED, dtype=torch.long, device=dev)
        self._DEPARTING_T = torch.tensor(DEPARTING, dtype=torch.long, device=dev)
        self._FIFO_EYE = ~torch.eye(self.N, dtype=torch.bool, device=dev)  # (N, N)
        # FSM dwell constants (CUDA Graph uyumlu — runtime tensor yaratma YOK)
        self._1_3 = torch.tensor(1.3, device=dev)
        self._2_0 = torch.tensor(2.0, device=dev)
        self._1_0 = torch.tensor(1.0, device=dev)
        self._0_15 = torch.tensor(0.15, device=dev)
        self._0_03 = torch.tensor(0.03, device=dev)
        self._0_08 = torch.tensor(0.08, device=dev)
        self._0_05 = torch.tensor(0.05, device=dev)
        self._NUM_STOPS_L = torch.tensor(self.num_stops, device=dev)
        self._A_MAX_T = torch.tensor(self._a_max, device=dev)  # departing ivme
        self._30_0 = torch.tensor(30.0, device=dev)
        self._10_0 = torch.tensor(10.0, device=dev)
        self._3_0_t = torch.tensor(3.0, device=dev)
        self._20_0 = torch.tensor(20.0, device=dev)

        # Pre-allocated buffers for CUDA Graph compat (yeni tensor yaratma yok)
        self._target_speed_buf = torch.empty(0, device=dev)  # reset'te boyutlanır

        # State tensörleri (B, N) — reset'te oluşturulur
        self.positions: torch.Tensor = None  # type: ignore
        self.speeds: torch.Tensor = None  # type: ignore
        self.accelerations: torch.Tensor = None  # type: ignore
        self.phases: torch.Tensor = None  # type: ignore
        self.dwell_remaining: torch.Tensor = None  # type: ignore
        self.next_stop_idx: torch.Tensor = None  # type: ignore
        self.is_queuing: torch.Tensor = None  # type: ignore
        self.queue_wait_time: torch.Tensor = None  # type: ignore
        self.holding_extra: torch.Tensor = None  # type: ignore
        self.speed_factor: torch.Tensor = None  # type: ignore

        # Skaler state (per-env)
        self.sim_time = torch.zeros(self.B, device=dev)  # (B,)
        self.step_count: int = 0
        self._start_hour = torch.full((self.B,), 6.0, device=dev)  # (B,)
        self._in_graph_mode = False  # CUDA Graph capture/replay sırasında True

        # Predictive engine state (env[0] üzerinde çalışır)
        self._predictive_decisions: dict[int, PredictiveDecision] = {}
        self._stop_infos: list[StopInfo] = [
            StopInfo(
                index=i,
                name=s.name,
                position=s.meter_position,
                capacity=compute_max_buses_at_stop(s),
                platform_length=s.platform_length_meters,
            )
            for i, s in enumerate(self.route.stops)
        ]

        # Traffic zones (ws_bridge uyumluluğu)
        self.tz_starts = torch.zeros(0, device=dev)
        self.tz_ends = torch.zeros(0, device=dev)
        self.tz_speeds = torch.zeros(0, device=dev)
        self.tz_remaining = torch.zeros(0, device=dev)

    # ========================================
    # RESET
    # ========================================
    def reset(self, seed: Optional[int] = None) -> Tuple[torch.Tensor, dict]:
        """Tüm B ortamı sıfırla. Returns obs: (B, N, obs_dim)"""
        if seed is not None:
            torch.manual_seed(seed)

        B, N, dev = self.B, self.N, self.device

        self.sim_time = torch.zeros(B, device=dev)
        self.step_count = 0
        self._start_hour = 5.0 + torch.rand(B, device=dev) * 17.0

        # Eşit aralıklı yerleştirme + jitter — (B, N)
        spacing = self.route_length / (N + 1)
        base_pos = torch.arange(1, N + 1, dtype=torch.float32, device=dev) * spacing  # (N,)
        base_pos = base_pos.unsqueeze(0).expand(B, -1)  # (B, N)
        jitter = (torch.rand(B, N, device=dev) - 0.5) * spacing * 0.3
        self.positions = torch.clamp(base_pos + jitter, 1.0, self.route_length - 1.0)

        self.speeds = 5.0 + torch.rand(B, N, device=dev) * 5.0
        self.accelerations = torch.zeros(B, N, device=dev)
        self.phases = torch.zeros(B, N, dtype=torch.long, device=dev)  # CRUISING
        self.dwell_remaining = torch.zeros(B, N, device=dev)
        self.next_stop_idx = self._compute_next_stop_indices(self.positions)
        self.is_queuing = torch.zeros(B, N, dtype=torch.bool, device=dev)
        self.queue_wait_time = torch.zeros(B, N, device=dev)
        self.holding_extra = torch.zeros(B, N, device=dev)
        self.speed_factor = torch.ones(B, N, device=dev)

        # Pre-allocated buffers boyutla
        self._target_speed_buf = torch.full((B, N), self._default_speed_limit, device=dev)

        obs = self._vectorized_obs()
        return obs, {}

    def _compute_next_stop_indices(self, positions: torch.Tensor) -> torch.Tensor:
        """Her araç için sonraki durak indexi. positions: (B, N) → returns (B, N)"""
        # (B, N, 1) vs (S,) → (B, N, S)
        greater = self.stop_positions > positions.unsqueeze(-1)  # (B, N, S)
        has_next = greater.any(dim=-1)  # (B, N)
        indices = greater.long().argmax(dim=-1)  # (B, N) — ilk True
        return torch.where(has_next, indices, self._NUM_STOPS_L.long())

    # ========================================
    # STEP
    # ========================================
    def step(self, actions: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, dict]:
        """
        actions: (B, N) long tensor → returns obs (B,N,24), reward (B,), term (B,), trunc (B,), info
        """
        dt = self.dt
        B, N, dev = self.B, self.N, self.device

        self.sim_time += dt
        self.step_count += 1

        # Saat ve rush hour — per-env (B,)
        current_hour = self._start_hour + (self.sim_time / 3600) % 24
        is_rush = ((current_hour >= 7) & (current_hour <= 9.5)) | \
                  ((current_hour >= 17) & (current_hour <= 19.5))  # (B,) bool
        # Expand for (B, N) masking
        is_rush_bn = is_rush.unsqueeze(1)  # (B, 1)

        # ─── 1. RL aksiyonları ───
        actions = actions.clamp(0, NUM_ACTIONS - 1)
        self.speed_factor.copy_(self._speed_factors[actions])  # (B, N)

        # HOLD
        hold_mask = (actions == ACTION_HOLD) & (self.phases != STOPPED) & (self.phases != DOORS_CLOSED) & (self.phases != BLOCKED)
        self.holding_extra.copy_(torch.where(
            hold_mask,
            torch.clamp(self.holding_extra, min=HOLD_DURATION_SECONDS),
            self.holding_extra,
        ))

        # ─── 1.5 Predictive Decision Engine (her step, graph mode hariç) ───
        if not self._in_graph_mode:
            self._run_predictive_engine()

        # ─── 2. Stokastik perturbasyonlar ───
        cruising_mask = self.phases == CRUISING
        perturb_mask = cruising_mask & (torch.rand(B, N, device=dev) < 0.003)
        self.speeds.copy_(torch.where(perturb_mask, self.speeds * 0.3, self.speeds))
        self.accelerations.copy_(torch.where(perturb_mask, self._NEG2, self.accelerations))

        # ─── 3. Sıralama (per-env) ───
        sorted_idx = torch.argsort(self.positions, dim=1)  # (B, N)

        # ─── 4. Station FSM ───
        self._vectorized_fsm(dt, is_rush_bn, sorted_idx)

        # ─── 5. Pozisyon kilidi ───
        pos_lock = self._compute_position_lock()

        # ─── 6. Hedef hız ───
        target_speed = self._compute_target_speed()
        target_speed = torch.clamp(target_speed * self.speed_factor, max=self._max_speed)

        # ─── 7. IDM ───
        self._vectorized_idm(dt, target_speed, sorted_idx, pos_lock)

        # ─── 8. Hat sonu wrapping ───
        wrap_mask = self.positions >= self.route_length
        self.positions.copy_(torch.where(wrap_mask, self._ZERO_F, self.positions))
        self.next_stop_idx.copy_(torch.where(wrap_mask, self._ZERO_L, self.next_stop_idx))
        self.phases.copy_(torch.where(wrap_mask, self._CRUISING_T, self.phases))
        self.is_queuing.copy_(torch.where(wrap_mask, self._FALSE, self.is_queuing))
        self.queue_wait_time.copy_(torch.where(wrap_mask, self._ZERO_F, self.queue_wait_time))

        # ─── 9. Obs & Reward ───
        obs = self._vectorized_obs()       # (B, N, 24)
        reward = self._vectorized_reward()  # (B,)

        truncated = self.sim_time >= self.max_episode_time  # (B,) bool
        terminated = torch.zeros(B, dtype=torch.bool, device=dev)

        return obs, reward, terminated, truncated, {}

    # ========================================
    # VECTORIZED IDM — (B, N)
    # ========================================
    def _vectorized_idm(self, dt, target_speed, sorted_idx, pos_lock):
        """IDM fizik — per-env sıralı. Tüm tensörler (B, N)."""
        B, N, dev = self.B, self.N, self.device

        # Gather sorted
        sorted_pos = torch.gather(self.positions, 1, sorted_idx)
        sorted_spd = torch.gather(self.speeds, 1, sorted_idx)
        sorted_target = torch.gather(target_speed, 1, sorted_idx)

        # Gaps: leader rear bumper — (B, N)
        gaps = torch.full((B, N), 1000.0, device=dev)
        # Gap = öndeki aracın ARKA TAMPONU - bizim pozisyon
        gaps[:, :-1] = (sorted_pos[:, 1:] - VEHICLE_LENGTH) - sorted_pos[:, :-1]
        gaps = torch.clamp(gaps, min=0.1)

        # DeltaV
        delta_v = torch.zeros(B, N, device=dev)
        delta_v[:, :-1] = sorted_spd[:, :-1] - sorted_spd[:, 1:]

        # IDM
        s_star = self._s0 + torch.clamp(
            sorted_spd * self._T + sorted_spd * delta_v / (2.0 * self._sqrt_ab),
            min=0.0,
        )
        v_ratio = (sorted_spd / torch.clamp(sorted_target, min=0.01)) ** self._idm_delta
        s_ratio = (s_star / gaps) ** 2
        accel = self._a_max * (1.0 - v_ratio - s_ratio)
        accel = torch.clamp(accel, -self._b_emergency, self._a_max)

        # Son araç: serbest sürüş
        has_leader = torch.ones(B, N, dtype=torch.bool, device=dev)
        has_leader[:, -1] = False
        speed_diff = sorted_target - sorted_spd
        free_accel = torch.where(
            speed_diff > 0,
            torch.clamp(speed_diff / dt, max=self._a_max),
            torch.clamp(speed_diff / dt, min=-self._b_comfort),
        )
        free_accel = torch.clamp(free_accel, -self._b_emergency, self._a_max)
        final_accel = torch.where(has_leader, accel, free_accel)

        # Hız ve pozisyon
        new_speed = torch.clamp(sorted_spd + final_accel * dt, min=0.0)
        ds = torch.clamp(new_speed * dt + 0.5 * final_accel * dt * dt, min=0.0)

        # Pozisyon kilidi
        sorted_lock = torch.gather(pos_lock, 1, sorted_idx)
        new_speed = torch.where(sorted_lock, self._ZERO_F, new_speed)
        ds = torch.where(sorted_lock, self._ZERO_F, ds)
        final_accel = torch.where(sorted_lock, self._ZERO_F, final_accel)

        new_pos = sorted_pos + ds

        # Unsort (per-env)
        inv_idx = torch.argsort(sorted_idx, dim=1)
        self.speeds.copy_(torch.gather(new_speed, 1, inv_idx))
        self.positions.copy_(torch.gather(new_pos, 1, inv_idx))
        self.accelerations.copy_(torch.gather(final_accel, 1, inv_idx))

    # ========================================
    # VECTORIZED FSM — (B, N)
    # ========================================
    def _vectorized_fsm(self, dt, is_rush_bn, sorted_idx):
        """Station FSM — 8 fazlı paralel peron, mask bazlı, batched."""
        B, N, dev = self.B, self.N, self.device
        S = self.num_stops

        safe_nsi = torch.clamp(self.next_stop_idx, 0, S - 1)  # (B, N)
        dist_to_stop = self.stop_positions[safe_nsi] - self.positions  # (B, N)
        at_end = self.next_stop_idx >= S  # (B, N)

        # Platform zone kontrolü — TS isInsidePlatformZone ile senkron
        # Peron alanı = [stop.meterPosition - platformLengthMeters, stop.meterPosition + 15]
        platform_len = self.stop_platform_lengths[safe_nsi]  # (B, N)
        platform_start = self.stop_positions[safe_nsi] - platform_len  # (B, N)
        platform_end = self.stop_positions[safe_nsi] + 15.0  # (B, N) — TS: +15m tolerans
        vehicle_rear = self.positions - VEHICLE_LENGTH  # (B, N)
        in_zone = (self.positions <= platform_end) & (vehicle_rear >= platform_start - 2.0) & ~at_end  # (B, N)

        # ═══ CRUISING → APPROACHING ═══
        cruising = self.phases == CRUISING
        # Zone-based entry: peron alanına girildiyse
        enter_approach_zone = cruising & in_zone
        # Normal approach distance
        enter_approach_dist = cruising & ~at_end & (dist_to_stop > 0) & (dist_to_stop < self._approach_dist)
        enter_approach = enter_approach_zone | enter_approach_dist
        self.phases.copy_(torch.where(enter_approach, self._APPROACHING_T, self.phases))

        # Durak atlama: sadece peronu tamamen geçtiyse ve peron içinde değilse
        skip_stop = cruising & ~at_end & (dist_to_stop < -15.0) & ~in_zone
        self.next_stop_idx.copy_(torch.where(skip_stop, self.next_stop_idx + 1, self.next_stop_idx))

        # ═══ APPROACHING ═══
        approaching = self.phases == APPROACHING
        slow_enough = self.speeds < 2.0  # IDM keeps vehicles creeping — 2 m/s threshold

        # ═══ PARALEL PERON OPERASYONU ═══
        # Peron alanı içinde + durmuş → STOPPED (ANINDA dwell başlat)
        # TS mantığı: Araç peron alanına girip durduğu anda yolcu operasyonu başlar
        # Birden fazla araç AYNI ANDA kapı açık olabilir (paralel)
        enter_stopped_zone = approaching & in_zone & slow_enough & ~at_end
        # Fallback: zone dışında ama durağa son 15m + yavaş (overshoot koruması)
        very_near_stop = (dist_to_stop > -5) & (dist_to_stop < 15)
        enter_stopped_fallback = approaching & slow_enough & very_near_stop & ~at_end & ~in_zone
        enter_stopped_any = enter_stopped_zone | enter_stopped_fallback

        # Paralel peron: Perondaki araç sayısını kontrol et
        # Kapasite aşıldıysa → QUEUED (peron DOLU)
        on_platform = (self.phases == STOPPED) | (self.phases == DOORS_CLOSED) | (self.phases == BLOCKED) | (self.phases == DOCKING)  # (B, N)
        # Aynı durakta peronda kaç araç var? (B, N) → her araç kendi durağı için
        same_stop_matrix = safe_nsi.unsqueeze(2) == safe_nsi.unsqueeze(1)  # (B, N, N)
        on_plat_expanded = on_platform.unsqueeze(1).expand(B, N, N)  # (B, N, N)
        not_self_mask = self._FIFO_EYE.unsqueeze(0)  # (1, N, N)
        platform_count = (same_stop_matrix & on_plat_expanded & not_self_mask).sum(dim=2)  # (B, N)
        max_buses = self.stop_max_buses[safe_nsi]  # (B, N)
        platform_has_space = platform_count < max_buses  # (B, N)

        # TS fitsInPlatform: enter_stopped sadece kapasitede yer varsa
        can_enter = enter_stopped_any & platform_has_space
        must_queue = enter_stopped_any & ~platform_has_space

        # Dwell süresi — branchless (her zaman hesaplanır, mask ile uygulanır)
        base_dwell = 15.0 + torch.rand(B, N, device=dev) * 10.0
        rush_mult = torch.where(is_rush_bn.expand(B, N), self._1_3, self._1_0)
        base_dwell = base_dwell * rush_mult
        engelli = (torch.rand(B, N, device=dev) < self._0_08).float() * (5.0 + torch.rand(B, N, device=dev) * 5.0)
        bebek = (torch.rand(B, N, device=dev) < self._0_05).float() * (3.0 + torch.rand(B, N, device=dev) * 3.0)
        crowd = (torch.rand(B, N, device=dev) < torch.where(is_rush_bn.expand(B, N), self._0_15, self._0_03)).float() * (2.0 + torch.rand(B, N, device=dev) * 3.0)
        kart = (torch.rand(B, N, device=dev) < self._0_03).float() * (2.0 + torch.rand(B, N, device=dev) * 2.0)
        dwell = torch.clamp(base_dwell + engelli + bebek + crowd + kart, 15.0, 30.0)
        dwell = 1.0 + dwell + self.holding_extra  # 1s kapı açılma

        # Kapasitede yer var → STOPPED (paralel dwell)
        self.dwell_remaining.copy_(torch.where(can_enter, dwell, self.dwell_remaining))
        self.holding_extra.copy_(torch.where(can_enter, self._ZERO_F, self.holding_extra))
        self.phases.copy_(torch.where(can_enter, self._STOPPED_T, self.phases))
        self.speeds.copy_(torch.where(can_enter, self._ZERO_F, self.speeds))
        self.accelerations.copy_(torch.where(can_enter, self._ZERO_F, self.accelerations))
        self.is_queuing.copy_(torch.where(can_enter, self._FALSE, self.is_queuing))
        # TS computeEntryPosition mantığı:
        # - Peron BOŞ → ilk araç stop.meterPosition'a (peron başı) snap edilir
        # - Peron DOLU (ama kapasite var) → araç mevcut pozisyonunda kalır (IDM arkada durdurmuştur)
        platform_empty = platform_count == 0  # (B, N)
        snap_pos = torch.where(can_enter & platform_empty, self.stop_positions[safe_nsi], self.positions)
        self.positions.copy_(torch.where(can_enter, snap_pos, self.positions))

        # Kapasite DOLU → QUEUED (peron girişinde bekleme)
        self.phases.copy_(torch.where(must_queue, self._QUEUED_T, self.phases))
        self.speeds.copy_(torch.where(must_queue, self._ZERO_F, self.speeds))
        self.accelerations.copy_(torch.where(must_queue, self._ZERO_F, self.accelerations))
        self.is_queuing.copy_(torch.where(must_queue, self._TRUE, self.is_queuing))

        # ═══ QUEUED → STOPPED (yer açıldığında perona gir) ═══
        queued = self.phases == QUEUED
        self.queue_wait_time.copy_(torch.where(queued, self.queue_wait_time + dt, self.queue_wait_time))
        self.speeds.copy_(torch.where(queued, self._ZERO_F, self.speeds))
        # Peronda yer açıldı mı? (güncel platform_count yeniden hesapla)
        on_platform_now = (self.phases == STOPPED) | (self.phases == DOORS_CLOSED) | (self.phases == BLOCKED) | (self.phases == DOCKING)
        same_stop_q = safe_nsi.unsqueeze(2) == safe_nsi.unsqueeze(1)
        on_plat_q = on_platform_now.unsqueeze(1).expand(B, N, N)
        plat_count_now = (same_stop_q & on_plat_q & not_self_mask).sum(dim=2)
        queue_can_enter = queued & (plat_count_now < max_buses)
        # Kuyruktaki araç için dwell hesapla
        q_dwell = torch.clamp(15.0 + torch.rand(B, N, device=dev) * 15.0, 15.0, 30.0)
        q_dwell = 1.0 + q_dwell + self.holding_extra
        self.phases.copy_(torch.where(queue_can_enter, self._STOPPED_T, self.phases))
        self.dwell_remaining.copy_(torch.where(queue_can_enter, q_dwell, self.dwell_remaining))
        self.holding_extra.copy_(torch.where(queue_can_enter, self._ZERO_F, self.holding_extra))
        self.is_queuing.copy_(torch.where(queue_can_enter, self._FALSE, self.is_queuing))
        self.queue_wait_time.copy_(torch.where(queue_can_enter, self._ZERO_F, self.queue_wait_time))

        # Durak geçme: peron dışında + çok geçildi (TS ile senkron)
        overshoot_limit = torch.clamp(platform_len * 0.5, min=5.0)  # (B, N)
        passed_stop = approaching & (dist_to_stop <= -overshoot_limit) & ~in_zone
        self.phases.copy_(torch.where(passed_stop, self._CRUISING_T, self.phases))
        self.is_queuing.copy_(torch.where(passed_stop, self._FALSE, self.is_queuing))
        self.next_stop_idx.copy_(torch.where(passed_stop, self.next_stop_idx + 1, self.next_stop_idx))

        # ═══ STOPPED — kapılar açık, dwell countdown ═══
        stopped = self.phases == STOPPED
        self.speeds.copy_(torch.where(stopped, self._ZERO_F, self.speeds))
        self.dwell_remaining.copy_(torch.where(stopped, self.dwell_remaining - dt, self.dwell_remaining))
        dwell_done = stopped & (self.dwell_remaining <= 0)
        # Dwell bitti → doorsClosed (kapı kapanma 2s)
        self.phases.copy_(torch.where(dwell_done, self._DOORS_CLOSED_T, self.phases))
        self.dwell_remaining.copy_(torch.where(dwell_done, self._2_0, self.dwell_remaining))

        # ═══ DOORS_CLOSED — kapılar kapanıyor (2s) ═══
        doors_closed = self.phases == DOORS_CLOSED
        self.speeds.copy_(torch.where(doors_closed, self._ZERO_F, self.speeds))
        self.dwell_remaining.copy_(torch.where(doors_closed, self.dwell_remaining - dt, self.dwell_remaining))
        dc_done = doors_closed & (self.dwell_remaining <= 0)

        # Fiziksel gap kontrolü: önde engel var mı?
        # FIFO + gap: (B, N, N) matris — branchless
        static_at_stop = (self.phases == STOPPED) | (self.phases == DOORS_CLOSED) | (self.phases == BLOCKED)  # (B, N)
        same_stop = self.next_stop_idx.unsqueeze(2) == self.next_stop_idx.unsqueeze(1)  # (B, N, N)
        j_static = static_at_stop.unsqueeze(1).expand(B, N, N)  # (B, N, N)
        ahead = self.positions.unsqueeze(2) > self.positions.unsqueeze(1)  # (B, N, N)
        not_self = self._FIFO_EYE.unsqueeze(0)  # (1, N, N)
        static_blocked = (same_stop & j_static & ahead & not_self).any(dim=2)  # (B, N)

        # Departing araçların gap kontrolü
        departing_mask = self.phases == DEPARTING  # (B, N)
        j_departing = departing_mask.unsqueeze(1).expand(B, N, N)  # (B, N, N)
        leader_rear = (self.positions - VEHICLE_LENGTH).unsqueeze(1).expand(B, N, N)  # (B, 1→N, N)
        my_pos = self.positions.unsqueeze(2).expand(B, N, N)  # (B, N, 1→N)
        dep_gap = leader_rear - my_pos  # (B, N, N) — j'nin rear - i'nin pos
        # j önde + departing + gap < SAFE_GAP
        dep_gap_t = self.positions.unsqueeze(2) - VEHICLE_LENGTH  # j'nin rear (B, N, N olacak)
        # Doğru boyut: j indeksi dim=2
        j_rear = (self.positions - VEHICLE_LENGTH).unsqueeze(1).expand(B, N, N)  # (B, i, j=N)
        i_pos = self.positions.unsqueeze(2).expand(B, N, N)  # (B, i=N, j)
        # j_rear[b, i, j] = positions[b, j] - VL  → bunu i'nin perspektifinden hesaplayalım
        # Doğru yaklaşım: j'nin pozisyonu - VL = j'nin arka tamponu
        j_positions = self.positions.unsqueeze(1).expand(B, N, N)  # (B, i, j) = positions[b, j]
        j_rear_correct = j_positions - VEHICLE_LENGTH  # (B, i, j)
        i_positions = self.positions.unsqueeze(2).expand(B, N, N)  # (B, i, j) = positions[b, i]
        gap_from_j = j_rear_correct - i_positions  # (B, i, j)
        j_ahead_of_i = j_positions > i_positions  # (B, i, j)
        j_is_departing = departing_mask.unsqueeze(1).expand(B, N, N)  # (B, i, j)
        dep_close = j_ahead_of_i & j_is_departing & (gap_from_j < SAFE_GAP) & not_self  # (B, i, j)
        dep_blocked = dep_close.any(dim=2)  # (B, N)

        is_blocked = static_blocked | dep_blocked  # (B, N)

        # dc_done & blocked → BLOCKED, dc_done & ~blocked → DEPARTING
        self.phases.copy_(torch.where(dc_done & is_blocked, self._BLOCKED_T, self.phases))
        to_depart = dc_done & ~is_blocked
        self.phases.copy_(torch.where(to_depart, self._DEPARTING_T, self.phases))
        self.next_stop_idx.copy_(torch.where(to_depart, self.next_stop_idx + 1, self.next_stop_idx))
        self.dwell_remaining.copy_(torch.where(dc_done, self._ZERO_F, self.dwell_remaining))

        # ═══ BLOCKED — önü açılmasını bekle ═══
        blocked = self.phases == BLOCKED
        self.speeds.copy_(torch.where(blocked, self._ZERO_F, self.speeds))
        self.queue_wait_time.copy_(torch.where(blocked, self.queue_wait_time + dt, self.queue_wait_time))
        deadlock_break = blocked & (self.queue_wait_time > 10.0)
        unblocked = blocked & (~is_blocked | deadlock_break)
        self.phases.copy_(torch.where(unblocked, self._DEPARTING_T, self.phases))
        self.queue_wait_time.copy_(torch.where(unblocked, self._ZERO_F, self.queue_wait_time))
        self.next_stop_idx.copy_(torch.where(unblocked, self.next_stop_idx + 1, self.next_stop_idx))

        # ═══ DEPARTING → CRUISING ═══
        departing = self.phases == DEPARTING
        # TS ile senkron: kalkışta ivme ataması — araç ivmelensin
        self.accelerations.copy_(torch.where(departing, self._A_MAX_T, self.accelerations))
        self.phases.copy_(torch.where(departing & (self.speeds > 3.0), self._CRUISING_T, self.phases))

    # ========================================
    # POSITION LOCK — (B, N)
    # ========================================
    def _compute_position_lock(self) -> torch.Tensor:
        # Tüm statik fazlar: FSM pozisyonu yönetir
        stopped = self.phases == STOPPED
        doors_closed = self.phases == DOORS_CLOSED
        queued = self.phases == QUEUED 
        blocked = self.phases == BLOCKED
        docking = self.phases == DOCKING
        # Approaching + durağa çok yakın + yavaş — IDM ileri itmesin
        safe_nsi = torch.clamp(self.next_stop_idx, 0, self.num_stops - 1)
        dist_to_stop = self.stop_positions[safe_nsi] - self.positions
        approaching_near = (self.phases == APPROACHING) & (self.speeds < 2.0) & (dist_to_stop > 0) & (dist_to_stop < 15)
        return stopped | doors_closed | queued | blocked | docking | approaching_near

    # ========================================
    # COMPUTE TARGET SPEED — (B, N)
    # ========================================
    def _compute_target_speed(self) -> torch.Tensor:
        """TS physics.ts computeTargetSpeed ile senkron 4-aşamalı piecewise frenleme."""
        B, N, dev = self.B, self.N, self.device

        target = self._target_speed_buf.fill_(self._default_speed_limit)
        target = torch.clamp(target, max=self._max_speed)

        safe_nsi = torch.clamp(self.next_stop_idx, 0, self.num_stops - 1)
        at_end = self.next_stop_idx >= self.num_stops
        dist_to_stop = self.stop_positions[safe_nsi] - self.positions

        # Departing koruması: durağı yeni terk eden araçlara frenleme uygulanmaz
        is_departing = self.phases == DEPARTING
        in_approach = ~at_end & (dist_to_stop > 0) & (dist_to_stop < self._approach_dist) & ~is_departing

        # 4-aşamalı piecewise frenleme eğrisi (TS physics.ts ile birebir)
        # Aşama 1: 150m-30m — kademeli yavaşlama
        ratio_far = (dist_to_stop - 30.0) / (self._approach_dist - 30.0)
        brake_far = 3.0 + ratio_far * (self._max_speed * 0.6 - 3.0)
        # Aşama 2: 30m-10m — güçlü frenleme (3→1 m/s)
        ratio_mid = (dist_to_stop - 10.0) / 20.0
        brake_mid = 1.0 + ratio_mid * 2.0
        # Aşama 3: 10m-3m — creep (1 m/s) — scalar broadcast
        # Aşama 4: <3m — dur — scalar broadcast

        # Piecewise seçim (CUDA Graph uyumlu — yeni tensor yaratma yok)
        braking_target = torch.where(dist_to_stop > 30.0, brake_far,
                         torch.where(dist_to_stop > 10.0, brake_mid,
                         torch.where(dist_to_stop > 3.0, self._1_0, self._ZERO_F)))

        target = torch.where(in_approach, torch.minimum(target, braking_target), target)

        # Hat sonu
        dist_to_end = self.route_length - self.positions
        near_end = dist_to_end < 50.0
        end_speed = torch.sqrt(2.0 * self._b_comfort * torch.clamp(dist_to_end, min=0.1))
        target = torch.where(near_end, torch.minimum(target, end_speed), target)

        return torch.clamp(target, min=0.0)

    # ========================================
    # VECTORIZED OBSERVATION — (B, N, 24)
    # ========================================
    def _vectorized_obs(self) -> torch.Tensor:
        B, N, dev = self.B, self.N, self.device

        sorted_idx = torch.argsort(self.positions, dim=1)  # (B, N)
        sorted_pos = torch.gather(self.positions, 1, sorted_idx)
        sorted_spd = torch.gather(self.speeds, 1, sorted_idx)
        sorted_phases = torch.gather(self.phases, 1, sorted_idx)

        # Forward/backward gaps (sorted)
        sorted_fwd_gap = torch.full((B, N), self.route_length, device=dev)
        sorted_fwd_gap[:, :-1] = sorted_pos[:, 1:] - sorted_pos[:, :-1]
        sorted_bwd_gap = torch.full((B, N), self.route_length, device=dev)
        sorted_bwd_gap[:, 1:] = sorted_pos[:, 1:] - sorted_pos[:, :-1]

        sorted_leader_spd = torch.zeros(B, N, device=dev)
        sorted_leader_spd[:, :-1] = sorted_spd[:, 1:]
        sorted_follower_spd = torch.zeros(B, N, device=dev)
        sorted_follower_spd[:, 1:] = sorted_spd[:, :-1]

        sorted_leader_stopped = torch.zeros(B, N, device=dev)
        stopped_like = (sorted_phases == STOPPED) | (sorted_phases == DOORS_CLOSED) | (sorted_phases == BLOCKED)
        sorted_leader_stopped[:, :-1] = stopped_like[:, 1:].float()
        sorted_follower_stopped = torch.zeros(B, N, device=dev)
        sorted_follower_stopped[:, 1:] = stopped_like[:, :-1].float()

        # Unsort
        inv_idx = torch.argsort(sorted_idx, dim=1)
        forward_gap = torch.gather(sorted_fwd_gap, 1, inv_idx)
        backward_gap = torch.gather(sorted_bwd_gap, 1, inv_idx)
        leader_speed = torch.gather(sorted_leader_spd, 1, inv_idx)
        follower_speed = torch.gather(sorted_follower_spd, 1, inv_idx)
        leader_stopped = torch.gather(sorted_leader_stopped, 1, inv_idx)
        follower_stopped = torch.gather(sorted_follower_stopped, 1, inv_idx)

        # Durak mesafeleri
        safe_nsi = torch.clamp(self.next_stop_idx, 0, self.num_stops - 1)
        at_end = self.next_stop_idx >= self.num_stops
        next_stop_dist = self.stop_positions[safe_nsi] - self.positions
        next_stop_dist = torch.where(at_end, self._ZERO_F, next_stop_dist)

        prev_nsi = torch.clamp(self.next_stop_idx - 1, 0, self.num_stops - 1)
        prev_stop_dist = self.positions - self.stop_positions[prev_nsi]

        second_nsi = torch.clamp(self.next_stop_idx + 1, 0, self.num_stops - 1)
        second_next_dist = self.stop_positions[second_nsi] - self.positions

        # Kuyruk — branchless
        at_stop_mask = (self.phases == STOPPED) | (self.phases == DOORS_CLOSED) | (self.phases == BLOCKED) | (self.phases == DOCKING) | (self.phases == APPROACHING) | (self.phases == QUEUED)
        offsets = torch.arange(B, device=dev).unsqueeze(1) * self.num_stops
        flat_nsi = (safe_nsi + offsets).reshape(-1)
        at_stop_float = at_stop_mask.float().reshape(-1)
        sc_flat = torch.zeros(B * self.num_stops, device=dev)
        sc_flat.scatter_add_(0, flat_nsi, at_stop_float)
        stop_counts = sc_flat.reshape(B, self.num_stops)
        next_stop_queue = torch.gather(stop_counts, 1, safe_nsi)
        max_queue = max(3.0, N / max(self.num_stops, 1))
        slot_capacity = self.stop_max_buses[safe_nsi].float()
        slot_occupancy = next_stop_queue / torch.clamp(slot_capacity, min=1.0)

        # Saat — (B,)
        hour = self._start_hour + (self.sim_time / 3600) % 24  # (B,)
        time_sin = torch.sin(2 * math.pi * hour / 24).unsqueeze(1).expand(B, N)
        time_cos = torch.cos(2 * math.pi * hour / 24).unsqueeze(1).expand(B, N)
        is_rush_val = (((hour >= 7) & (hour <= 9.5)) | ((hour >= 17) & (hour <= 19.5))).float().unsqueeze(1).expand(B, N)
        episode_progress = (self.sim_time / max(self.max_episode_time, 1.0)).clamp(max=1.0).unsqueeze(1).expand(B, N)

        # Phase one-hot
        max_spd = max(self._max_speed, 0.01)

        # Stack (B, N, 24)
        obs = torch.stack([
            self.positions / self.route_length,                                   # [0]
            self.speeds / max_spd,                                                # [1]
            torch.clamp(forward_gap / self.route_length, max=1.0),                # [2]
            torch.clamp(backward_gap / self.route_length, max=1.0),               # [3]
            self.dwell_remaining / max(self.config.max_dwell_time, 1.0),          # [4]
            time_sin,                                                              # [5]
            time_cos,                                                              # [6]
            is_rush_val,                                                           # [7]
            (self.phases == CRUISING).float(),                                     # [8]
            ((self.phases == APPROACHING) | (self.phases == QUEUED) | (self.phases == DOCKING)).float(),  # [9] approaching group
            ((self.phases == STOPPED) | (self.phases == DOORS_CLOSED) | (self.phases == BLOCKED)).float(),  # [10] stopped group
            (self.phases == DEPARTING).float(),                                    # [11]
            torch.clamp(next_stop_dist.clamp(min=0) / max(self._approach_dist, 1), max=1.0),  # [12]
            self.accelerations / max(self._b_emergency, 0.01),                    # [13]
            leader_speed / max_spd,                                                # [14]
            follower_speed / max_spd,                                              # [15]
            leader_stopped,                                                        # [16]
            follower_stopped,                                                      # [17]
            torch.clamp(next_stop_queue / max_queue, max=1.0),                    # [18]
            torch.clamp(prev_stop_dist.clamp(min=0) / self.route_length, max=1.0), # [19]
            torch.clamp(second_next_dist.clamp(min=0) / self.route_length, max=1.0), # [20]
            episode_progress,                                                      # [21]
            torch.clamp(slot_capacity / 6.0, max=1.0),                            # [22]
            torch.clamp(slot_occupancy, max=2.0) / 2.0,                           # [23]
        ], dim=2)  # (B, N, 24)

        return obs

    # ========================================
    # VECTORIZED REWARD — (B,)
    # ========================================
    def _vectorized_reward(self) -> torch.Tensor:
        """Per-env reward. Returns (B,) GPU tensor."""
        B, N, dev = self.B, self.N, self.device

        if N < 2:
            return torch.zeros(B, device=dev)

        sorted_pos = torch.sort(self.positions, dim=1).values  # (B, N)
        gaps = sorted_pos[:, 1:] - sorted_pos[:, :-1]  # (B, N-1)
        num_gaps = gaps.shape[1]

        # Headway CV
        avg_speed = (self.speeds.sum(dim=1) / N).clamp(min=0.01)  # (B,)
        headways = gaps / avg_speed.unsqueeze(1)  # (B, N-1)
        headway_mean = headways.mean(dim=1)  # (B,)
        headway_std = headways.std(dim=1)  # (B,)
        cv = headway_std / headway_mean.clamp(min=0.01)  # (B,)
        r_headway = torch.clamp(1.0 - cv, min=-1.0) * self._w_headway  # (B,)

        # Bunching
        critical = (gaps < BUNCHING_CRITICAL_M).float().sum(dim=1)  # (B,)
        warning = ((gaps >= BUNCHING_CRITICAL_M) & (gaps < BUNCHING_WARNING_M)).float().sum(dim=1) * 0.5
        bunching_ratio = (critical + warning) / max(num_gaps, 1)
        r_bunching = -bunching_ratio * self._w_bunching  # (B,)

        # Dwell
        stopped_like = (self.phases == STOPPED) | (self.phases == DOORS_CLOSED) | (self.phases == BLOCKED)
        long_dwell = (stopped_like & ~self.is_queuing & (self.dwell_remaining > LONG_DWELL_THRESHOLD)).float().sum(dim=1)
        r_dwell = -(long_dwell / N) * self._w_dwell  # (B,)

        # Speed
        avg_spd = self.speeds.mean(dim=1)  # (B,)
        speed_ratio = avg_spd / max(self._target_speed_ms, 0.01)
        r_speed = self._w_speed * torch.exp(-2.0 * (speed_ratio - 1.0) ** 2)  # (B,)

        return r_headway + r_bunching + r_dwell + r_speed  # (B,)

    # ========================================
    # PREDICTIVE DECISION ENGINE
    # ========================================
    _PHASE_NAMES_PE = ["cruising", "approaching", "queued", "docking",
                       "stopped", "doorsClosed", "blocked", "departing"]

    def _run_predictive_engine(self) -> None:
        """
        Predictive Lookahead Decision Engine — env[0] üzerinde çalışır.
        
        GPU tensörlerinden CPU snapshot çıkarır, tüm otobüsleri değerlendirir,
        SPEED_FILTER kararı verilen araçların speed_factor'ünü günceller.
        
        Bu işlem CPU'da yapılır (analitik formüller, GPU overhead yok).
        Sadece env[0] üzerinde çalışır — diğer env'ler etkilenmez.
        """
        env_idx = 0
        N = self.N

        # GPU → CPU snapshot (sadece env[0])
        positions = self.positions[env_idx].cpu().numpy()
        speeds = self.speeds[env_idx].cpu().numpy()
        accels = self.accelerations[env_idx].cpu().numpy()
        phases = self.phases[env_idx].cpu().numpy()
        dwell_rem = self.dwell_remaining[env_idx].cpu().numpy()
        next_si = self.next_stop_idx[env_idx].cpu().numpy()
        holding = self.holding_extra[env_idx].cpu().numpy()

        # Rush hour tespiti
        hour = (self._start_hour[env_idx].item() + self.sim_time[env_idx].item() / 3600) % 24
        is_rush = (7 <= hour <= 9.5) or (17 <= hour <= 19.5)

        # BusSnapshot listesi oluştur
        bus_snapshots = []
        for i in range(N):
            phase_idx = int(phases[i])
            phase_name = self._PHASE_NAMES_PE[phase_idx] if phase_idx < 8 else "cruising"
            bus_snapshots.append(BusSnapshot(
                bus_id=i,
                position=float(positions[i]),
                speed=float(speeds[i]),
                acceleration=float(accels[i]),
                phase=phase_name,
                next_stop_index=int(next_si[i]),
                dwell_remaining=float(dwell_rem[i]),
                holding_extra=float(holding[i]),
            ))

        # Tüm otobüsleri değerlendir
        decisions = evaluate_all_buses(
            bus_snapshots,
            self._stop_infos,
            is_rush_hour=is_rush,
            approach_distance=self._approach_dist,
            comfort_braking=self._b_comfort,
            max_speed=self._max_speed,
        )

        # Kararları kaydet (WS bridge / logging)
        self._predictive_decisions = decisions

        # SPEED_FILTER kararlarını GPU'ya uygula (env[0] için)
        for bus_id, dec in decisions.items():
            if dec.decision == Decision.SPEED_FILTER and dec.v_target > 0:
                current_speed = float(speeds[bus_id])
                if current_speed > 0.01:
                    # speed_factor = v_target / target_speed
                    # Ama biz speed_factor'ü doğrudan hız oranı olarak kullanıyoruz
                    ratio = dec.v_target / current_speed
                    ratio = max(0.2, min(1.0, ratio))  # güvenlik sınırı
                    self.speed_factor[env_idx, bus_id] = ratio

    # ========================================
    # GET INFO (WS bridge / logging için)
    # ========================================
    def _get_info(self, env_idx: int = 0) -> dict:
        """Tek env'in info'su — WS bridge için."""
        pos = self.positions[env_idx]
        spd = self.speeds[env_idx]
        sorted_pos = torch.sort(pos).values
        gaps = sorted_pos[1:] - sorted_pos[:-1]

        # Predictive engine istatistikleri
        pe_stats = {"speed_filter_count": 0, "bunching_accept_count": 0}
        for dec in self._predictive_decisions.values():
            if dec.decision == Decision.SPEED_FILTER:
                pe_stats["speed_filter_count"] += 1
            elif dec.decision == Decision.BUNCHING_ACCEPT:
                pe_stats["bunching_accept_count"] += 1

        return {
            "sim_time": self.sim_time[env_idx].item(),
            "step_count": self.step_count,
            "avg_speed_ms": spd.mean().item(),
            "avg_speed_kmh": spd.mean().item() * 3.6,
            "min_gap_m": gaps.min().item() if gaps.numel() > 0 else 0.0,
            "max_gap_m": gaps.max().item() if gaps.numel() > 0 else 0.0,
            "avg_gap_m": gaps.mean().item() if gaps.numel() > 0 else 0.0,
            "num_stopped": ((self.phases[env_idx] == STOPPED) | (self.phases[env_idx] == DOORS_CLOSED) | (self.phases[env_idx] == BLOCKED)).sum().item(),
            "device": str(self.device),
            "predictive_engine": pe_stats,
        }

    # ========================================
    # RESET DONE ENVS
    # ========================================
    def reset_done_envs(self, done_mask: torch.Tensor) -> None:
        """Biten env'leri sıfırla. done_mask: (B,) bool."""
        if not done_mask.any():
            return
        B, N, dev = self.B, self.N, self.device

        # Sadece done olan env'leri sıfırla
        n_done = done_mask.sum().item()
        spacing = self.route_length / (N + 1)
        base = torch.arange(1, N + 1, dtype=torch.float32, device=dev) * spacing
        base = base.unsqueeze(0).expand(n_done, -1)
        jitter = (torch.rand(n_done, N, device=dev) - 0.5) * spacing * 0.3
        new_pos = torch.clamp(base + jitter, 1.0, self.route_length - 1.0)

        self.positions[done_mask] = new_pos
        self.speeds[done_mask] = 5.0 + torch.rand(n_done, N, device=dev) * 5.0
        self.accelerations[done_mask] = 0.0
        self.phases[done_mask] = CRUISING
        self.dwell_remaining[done_mask] = 0.0
        self.next_stop_idx[done_mask] = self._compute_next_stop_indices(new_pos)
        self.is_queuing[done_mask] = False
        self.queue_wait_time[done_mask] = 0.0
        self.holding_extra[done_mask] = 0.0
        self.speed_factor[done_mask] = 1.0
        self.sim_time[done_mask] = 0.0
        self._start_hour[done_mask] = 5.0 + torch.rand(n_done, device=dev) * 17.0

    def compile_step(self):
        """Eski torch.compile wrapper — artık CUDA Graph kullanıyoruz."""
        print("  GPU env: CUDA Graphs kullanılacak (compile_step atlandı)")

    # ========================================
    # CUDA GRAPH — Python dispatch bypass
    # ========================================
    def capture_graph(self):
        """
        CUDA Graph capture — step() içindeki tüm CUDA kernel'larını
        bir kere kaydet, sonra Python'a dönmeden replay et.
        ~100 kernel launch overhead → 1 graph replay.
        """
        B, N, dev = self.B, self.N, self.device
        print("  CUDA Graph: warmup başlıyor...")

        # Static input/output tensörleri (graph capture sırasında sabit adresler)
        self._graph_actions = torch.ones(B, N, dtype=torch.long, device=dev)
        self._graph_obs = torch.zeros(B, N, OBS_DIM, device=dev)
        self._graph_reward = torch.zeros(B, device=dev)
        self._graph_terminated = torch.zeros(B, dtype=torch.bool, device=dev)
        self._graph_truncated = torch.zeros(B, dtype=torch.bool, device=dev)

        # Warmup — GPU memory pool'u ısıt (3 step)
        s = torch.cuda.Stream()
        s.wait_stream(torch.cuda.current_stream())
        self._in_graph_mode = True  # Predictive engine'i devre dışı bırak
        with torch.cuda.stream(s):
            for _ in range(3):
                self._graph_actions.fill_(1)
                obs, rew, term, trunc, _ = self.step(self._graph_actions)
                self._graph_obs.copy_(obs)
                self._graph_reward.copy_(rew)
                self._graph_terminated.copy_(term)
                self._graph_truncated.copy_(trunc)
        torch.cuda.current_stream().wait_stream(s)

        # Graph capture
        print("  CUDA Graph: capture başlıyor...")
        self._cuda_graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(self._cuda_graph):
            obs, rew, term, trunc, _ = self.step(self._graph_actions)
            self._graph_obs.copy_(obs)
            self._graph_reward.copy_(rew)
            self._graph_terminated.copy_(term)
            self._graph_truncated.copy_(trunc)

        self._graph_captured = True
        print("  CUDA Graph: capture BASARILI ok")

    def graph_step(self, actions: torch.Tensor):
        """
        CUDA Graph replay — Python dispatch SIFIR.
        actions'ı static input'a kopyala, graph'ı replay et, output'u oku.
        """
        self._graph_actions.copy_(actions)
        self._cuda_graph.replay()
        return (
            self._graph_obs,
            self._graph_reward,
            self._graph_terminated,
            self._graph_truncated,
            {},
        )
