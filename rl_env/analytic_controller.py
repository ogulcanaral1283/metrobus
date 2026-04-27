"""
Analitik Filo Kontrol Sistemi — Merkezi Headway Regülatörü

RL yerine deterministik matematik ile filo yönetimi.
GPU tensör operasyonlarıyla çalışır → GpuMetrobusEnv ile uyumlu.

3 katmanlı karar mekanizması:
  1. Headway PID: Araçlar arası eşit mesafe koruması
  2. Slot Lookahead: Durağa varışı slot müsaitliğiyle senkronize etme
  3. Forward Safety: Öndeki araca çarpmayı engelleme

Kullanım:
  controller = AnalyticFleetController(env)
  actions, speed_overrides = controller.compute(env)
  obs, reward, ... = env.step(actions)
"""

from __future__ import annotations

import torch
import math


class AnalyticFleetController:
    """
    Merkezi analitik filo kontrol sistemi.
    Tüm araçları görür, her birine hız komutu hesaplar.

    GPU tensör operasyonlarıyla çalışır (Python loop yok).
    """

    def __init__(
        self,
        route_length: float,
        num_buses: int,
        stop_positions: torch.Tensor,   # (S,)
        stop_capacities: torch.Tensor,  # (S,)
        vehicle_length: float = 20.0,
        max_speed: float = 14.0,        # m/s (~50 km/h)
        # PID parametreleri
        kp: float = 0.08,              # Proportional — ana düzeltme
        ki: float = 0.001,             # Integral — uzun vadeli drift
        kd: float = 0.02,             # Derivative — ani değişim sönümlemesi
        # Lookahead parametreleri
        lookahead_horizon: float = 120.0,  # saniye — kaç sn ileriye bak
        slot_buffer_time: float = 5.0,     # slot açıldıktan kaç sn sonra var
        # Güvenlik
        min_gap: float = 25.0,             # minimum takip mesafesi (m)
        device: str = "cuda",
    ):
        self.route_length = route_length
        self.num_buses = num_buses
        self.vehicle_length = vehicle_length
        self.max_speed = max_speed
        self.min_gap = min_gap
        self.device = device

        # PID katsayıları
        self.kp = kp
        self.ki = ki
        self.kd = kd

        # Lookahead
        self.lookahead_horizon = lookahead_horizon
        self.slot_buffer_time = slot_buffer_time

        # Hedef headway (eşit dağılım)
        self.target_gap = route_length / num_buses

        # Durak bilgileri
        self.stop_positions = stop_positions    # (S,)
        self.stop_capacities = stop_capacities  # (S,)

        # PID integral ve önceki hata (B, N)
        self._integral_error = None
        self._prev_error = None

    def reset(self, B: int, N: int):
        """Yeni episode başlangıcında PID state sıfırla."""
        dev = self.device
        self._integral_error = torch.zeros(B, N, device=dev)
        self._prev_error = torch.zeros(B, N, device=dev)

    def compute(
        self,
        positions: torch.Tensor,        # (B, N) metre
        speeds: torch.Tensor,            # (B, N) m/s
        phases: torch.Tensor,            # (B, N) long (FSM state)
        next_stop_idx: torch.Tensor,     # (B, N) long
        dwell_remaining: torch.Tensor,   # (B, N) saniye
        is_queuing: torch.Tensor,        # (B, N) bool
        dt: float = 0.1,
    ) -> torch.Tensor:
        """
        Tüm araçlar için optimal speed_factor hesapla.

        Returns:
            speed_factor: (B, N) float — her araç için hız çarpanı [0.2, 1.3]
        """
        B, N = positions.shape
        dev = positions.device

        if self._integral_error is None:
            self.reset(B, N)

        # ══════════════════════════════════════════
        # KATMAN 1: Headway PID Kontrolü
        # ══════════════════════════════════════════
        speed_pid = self._headway_pid(positions, speeds, dt)

        # ══════════════════════════════════════════
        # KATMAN 2: Slot Lookahead Optimizasyonu
        # ══════════════════════════════════════════
        speed_slot = self._slot_lookahead(
            positions, speeds, phases, next_stop_idx,
            dwell_remaining, is_queuing,
        )

        # ══════════════════════════════════════════
        # KATMAN 3: Forward Safety (çarpışma engelleme)
        # ══════════════════════════════════════════
        speed_safe = self._forward_safety(positions, speeds)

        # ══════════════════════════════════════════
        # BİRLEŞTİRME: En düşük hız komutu kazanır (güvenlik öncelikli)
        # ══════════════════════════════════════════
        # Her katman bir hedef hız üretir, en kısıtlayıcısını al
        target_speed = torch.min(speed_pid, speed_slot)
        target_speed = torch.min(target_speed, speed_safe)
        target_speed = torch.clamp(target_speed, min=0.5, max=self.max_speed)

        # Speed factor hesapla (mevcut hız limiti baz alınarak)
        base_speed = self.max_speed
        speed_factor = target_speed / base_speed
        speed_factor = torch.clamp(speed_factor, min=0.05, max=1.3)

        # Durakta olan araçlara dokunma (FSM yönetiyor)
        # Phase: 0=CRUISING, 1=APPROACHING, 4=STOPPED, 5=DOORS_CLOSED, 6=BLOCKED, 7=DEPARTING
        at_stop = (phases >= 3) & (phases <= 6)  # QUEUED, DOCKING, STOPPED, DOORS_CLOSED, BLOCKED
        speed_factor = torch.where(at_stop, torch.ones_like(speed_factor), speed_factor)

        return speed_factor

    def _headway_pid(
        self,
        positions: torch.Tensor,  # (B, N)
        speeds: torch.Tensor,     # (B, N)
        dt: float,
    ) -> torch.Tensor:
        """
        PID headway kontrolü — her aracın öndeki araçla mesafesini
        target_gap'e yaklaştırır.

        Returns: target_speed (B, N)
        """
        B, N = positions.shape
        dev = positions.device

        # ─── Pozisyona göre sırala ───
        sorted_idx = torch.argsort(positions, dim=1)
        sorted_pos = torch.gather(positions, 1, sorted_idx)
        sorted_spd = torch.gather(speeds, 1, sorted_idx)

        # ─── Forward gap hesapla (circular route) ───
        forward_gap = torch.zeros(B, N, device=dev)
        forward_gap[:, :-1] = sorted_pos[:, 1:] - sorted_pos[:, :-1] - self.vehicle_length
        # Son araç → ilk araç (circular)
        forward_gap[:, -1] = (self.route_length - sorted_pos[:, -1]) + sorted_pos[:, 0] - self.vehicle_length
        forward_gap = torch.clamp(forward_gap, min=1.0)

        # ─── PID error ───
        # Pozitif error = çok uzak → hızlan
        # Negatif error = çok yakın → yavaşla
        error = forward_gap - self.target_gap  # (B, N)

        # Integral (anti-windup)
        sorted_integral = torch.gather(self._integral_error, 1, sorted_idx)
        sorted_integral = sorted_integral + error * dt
        sorted_integral = torch.clamp(sorted_integral, -500.0, 500.0)  # anti-windup

        # Derivative
        sorted_prev = torch.gather(self._prev_error, 1, sorted_idx)
        derivative = (error - sorted_prev) / max(dt, 1e-6)

        # PID çıktısı (hız düzeltmesi, m/s)
        correction = (
            self.kp * error +
            self.ki * sorted_integral +
            self.kd * derivative
        )

        # Hedef hız = mevcut baz hız + düzeltme
        base_speed = self.max_speed * 0.8  # %80 taban hız
        target_speed = base_speed + correction
        target_speed = torch.clamp(target_speed, min=1.0, max=self.max_speed * 1.3)

        # ─── State güncelle (unsort) ───
        unsort_idx = torch.argsort(sorted_idx, dim=1)
        self._integral_error = torch.gather(sorted_integral, 1, unsort_idx)
        self._prev_error = torch.gather(error, 1, unsort_idx)

        # Unsort target speed
        target_speed = torch.gather(target_speed, 1, unsort_idx)

        return target_speed

    def _slot_lookahead(
        self,
        positions: torch.Tensor,       # (B, N)
        speeds: torch.Tensor,          # (B, N)
        phases: torch.Tensor,          # (B, N) long
        next_stop_idx: torch.Tensor,   # (B, N) long
        dwell_remaining: torch.Tensor, # (B, N)
        is_queuing: torch.Tensor,      # (B, N) bool
    ) -> torch.Tensor:
        """
        Slot Lookahead: Durağa varışı peron müsaitliğiyle senkronize et.

        Durakta kaç araç var? Çıkışları ne zaman?
        → Slot açılmasını bekleyecek şekilde hız ayarla.
        → Kuyruk bekleme süresi = 0 hedefi.

        Returns: target_speed (B, N) — slot bazlı hız limiti
        """
        B, N = positions.shape
        dev = positions.device
        S = self.stop_positions.shape[0]

        # Varsayılan: max hız (slot kısıtlaması yoksa)
        target_speed = torch.full((B, N), self.max_speed, device=dev)

        # Sadece CRUISING veya APPROACHING araçlara uygula
        cruising = (phases == 0) | (phases == 1)  # CRUISING veya APPROACHING

        # ─── Durağa mesafe ───
        safe_nsi = torch.clamp(next_stop_idx, 0, S - 1)
        stop_pos = self.stop_positions[safe_nsi]  # (B, N)
        dist_to_stop = stop_pos - positions  # (B, N)
        dist_to_stop = torch.clamp(dist_to_stop, min=1.0)

        # Sadece 300m içindeki araçlar için lookahead yap
        in_range = cruising & (dist_to_stop < 300.0) & (dist_to_stop > 5.0)

        # ─── Her durak için kaç araç var? ───
        # Count vehicles at each stop (STOPPED, DOORS_CLOSED, BLOCKED, DOCKING phases)
        at_station = (phases >= 3) & (phases <= 6)
        # Her (env, stop) için araç sayısı
        # Simplified: aynı next_stop_idx'e sahip ve durakta olan araç sayısı
        # Bu tensör operasyonuyla hesaplamak pahalı, yaklaşık yöntem kullan:

        # Her araç için: "benim hedef durağımda kaç araç duruyor?"
        stop_occupancy = torch.zeros(B, S, device=dev)
        for s in range(S):
            mask = at_station & (safe_nsi == s)
            stop_occupancy[:, s] = mask.float().sum(dim=1)

        # Bu aracın hedef durağındaki doluluk
        occ = torch.gather(stop_occupancy, 1, safe_nsi)  # (B, N)
        cap = self.stop_capacities[safe_nsi].float()      # (B, N)

        # Durak dolu mu?
        is_full = occ >= cap

        # ─── Slot açılma zamanı tahmini ───
        # Duraktaki araçların ortalama kalan dwell süresi
        # Basitleştirilmiş: ortalama dwell ~20 saniye
        avg_dwell_remaining = 20.0  # saniye (heuristik)

        # Dolu durak için: slot açılana kadar bekleme süresi
        # slot_free_time ≈ avg_dwell_remaining (ilk araç çıkışı)
        slot_free_time = torch.where(
            is_full,
            torch.tensor(avg_dwell_remaining, device=dev),
            torch.tensor(0.0, device=dev),
        )

        # ─── Optimal hız hesapla ───
        # v_optimal = mesafe / (slot_açılma + tampon)
        # Bu hızla gidersen, tam slot açıldığında varırsın → bekleme yok
        time_needed = slot_free_time + self.slot_buffer_time  # saniye
        time_needed = torch.clamp(time_needed, min=5.0)

        v_slot_optimal = dist_to_stop / time_needed
        v_slot_optimal = torch.clamp(v_slot_optimal, min=2.0, max=self.max_speed)

        # Sadece dolu duraklar ve range içindeki araçlar için uygula
        should_slow = in_range & is_full
        target_speed = torch.where(should_slow, v_slot_optimal, target_speed)

        return target_speed

    def _forward_safety(
        self,
        positions: torch.Tensor,  # (B, N)
        speeds: torch.Tensor,     # (B, N)
    ) -> torch.Tensor:
        """
        Forward Safety: Öndeki araca minimum mesafe koru.

        IDM zaten bunu yapıyor ama ek güvenlik katmanı olarak
        speed_factor'ü sınırla.

        Returns: max_safe_speed (B, N)
        """
        B, N = positions.shape
        dev = positions.device

        # Pozisyona göre sırala
        sorted_idx = torch.argsort(positions, dim=1)
        sorted_pos = torch.gather(positions, 1, sorted_idx)

        # Forward gap
        gap = torch.full((B, N), 500.0, device=dev)
        gap[:, :-1] = sorted_pos[:, 1:] - sorted_pos[:, :-1] - self.vehicle_length
        gap = torch.clamp(gap, min=0.1)

        # Güvenli hız: gap < min_gap ise agresif yavaşla
        # gap >> min_gap ise max hız
        gap_ratio = gap / self.min_gap  # <1 = tehlikeli, >1 = güvenli
        safe_speed = self.max_speed * torch.clamp(gap_ratio, min=0.05, max=1.5)

        # Unsort
        unsort_idx = torch.argsort(sorted_idx, dim=1)
        safe_speed = torch.gather(safe_speed, 1, unsort_idx)

        return safe_speed


def create_controller_from_env(env) -> AnalyticFleetController:
    """GpuMetrobusEnv'den analitik controller oluştur."""
    return AnalyticFleetController(
        route_length=env.route_length,
        num_buses=env.N,
        stop_positions=env.stop_positions,
        stop_capacities=env.stop_max_buses,  # GpuMetrobusEnv'deki isim
        vehicle_length=20.0,
        max_speed=env._max_speed,
        device=str(env.device),
    )
