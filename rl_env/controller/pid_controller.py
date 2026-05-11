"""
Katman 2 — PID Headway Regülatörü
====================================

Discrete-time PID kontrolcü. Headway hatasını düzeltmek için
her araç başına holding süresi (saniye) üretir.

Giriş:
    e_i(t) = h_target − h_i(t)       [saniye]
    Negatif error → araç öndekilere çok yakın → tutulmalı
    Pozitif error → araç öndekilere çok uzak → serbest bırak

Çıktı:
    u_i(t) = hold_time                [saniye, ≥ 0]

Discrete-Time PID (Backward Euler):
    P(k)  = Kp · e(k)
    I(k)  = I(k-1) + Ki · e(k) · dt
    D(k)  = Kd · [e(k) − e(k-1)] / dt

    u(k)  = P(k) + I(k) + D(k)

Anti-windup: Back-calculation + integral clamping
    Integral satürasyona ulaştığında geriye hesaplama ile
    integral bileşeni sınırlanır. Bu, uzun süreli hata
    birikiminin kontrolcüyü dengesizleştirmesini engeller.

Saturation:
    u(k) = clamp(u(k), 0, u_max)
    hold_time negatif olamaz (araç zaman yolculuğu yapamaz).
    u_max varsayılan 60 sn — bir durakta 1 dk'dan fazla tutmak
    trafik akışını ciddi şekilde bozar.

Kazanç Seçimi Gerekçesi:
    Kp, Ki, Kd değerleri Ziegler-Nichols veya pole placement ile
    türetilir. tuning.py modülü bu süreci otomatize eder.
    Varsayılan değerler metrobüs koridoru için heuristic başlangıç.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

try:
    from .headway_model import HeadwayState
except ImportError:
    from headway_model import HeadwayState


@dataclass
class PIDState:
    """Tek araç için PID iç durumu."""
    vehicle_id: int
    integral: float = 0.0       # birikmiş integral terimi
    prev_error: float = 0.0     # önceki hata (derivative için)
    prev_output: float = 0.0    # önceki çıktı (debug)


@dataclass
class PIDOutput:
    """PID kontrolcü çıktısı — tek araç."""
    vehicle_id: int
    hold_time: float            # durakta tutma süresi (sn), ≥ 0
    p_term: float               # proportional bileşen
    i_term: float               # integral bileşen
    d_term: float               # derivative bileşen
    raw_output: float           # satürasyon öncesi ham çıktı
    error: float                # headway hatası (sn)
    saturated: bool             # satürasyona ulaşıldı mı


class PIDController:
    """
    Discrete-time PID headway regülatörü.

    Her araç için bağımsız PID durumu tutulur (decentralized PID).
    Merkezi headway model'den gelen error ve derivative kullanılır.

    Parametreler:
        kp:     Proportional kazanç — ana düzeltme kuvveti
        ki:     Integral kazanç — uzun vadeli drift telafisi
        kd:     Derivative kazanç — ani değişim sönümlemesi
        dt:     Zaman adımı (sn)
        u_max:  Maximum hold süresi (sn)
        anti_windup_gain: Back-calculation anti-windup kazancı (1/Tt)
    """

    def __init__(
        self,
        kp: float = 0.4,
        ki: float = 0.02,
        kd: float = 0.15,
        dt: float = 0.1,
        u_max: float = 60.0,
        anti_windup_gain: float = 0.1,
    ):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.dt = dt
        self.u_max = u_max
        self.anti_windup_gain = anti_windup_gain

        # Araç başına PID durumu
        self._states: dict[int, PIDState] = {}

    def _get_state(self, vehicle_id: int) -> PIDState:
        """Araç için PID durumunu al veya oluştur."""
        if vehicle_id not in self._states:
            self._states[vehicle_id] = PIDState(vehicle_id=vehicle_id)
        return self._states[vehicle_id]

    def compute_single(
        self,
        headway_state: HeadwayState,
        at_stop: bool = False,
    ) -> PIDOutput:
        """
        Tek araç için PID hold_time hesapla.

        Args:
            headway_state: Headway model'den gelen durum
            at_stop: Araç şu anda durakta mı

        Returns:
            PIDOutput — hold_time ve debug bilgileri

        Not:
            PID her tick çalışır ama hold_time yalnızca araç duraktayken
            uygulanır. Araç seyirdeyken PID çıktısı biriktirilerek
            (integral) bir sonraki durak için hazır tutulur.
        """
        state = self._get_state(headway_state.vehicle_id)
        error = headway_state.headway_error

        # ── Proportional ──
        # Negatif error (çok yakın) → pozitif P → hold uygula
        # İşaret çevirme: PID çıktısı pozitif = "tut"
        p_term = self.kp * (-error)

        # ── Integral (Backward Euler + anti-windup) ──
        state.integral += self.ki * (-error) * self.dt

        # Anti-windup: integral clamping
        integral_limit = self.u_max * 0.8  # integralin max %80'i doldurabileceği
        state.integral = max(-integral_limit, min(integral_limit, state.integral))

        i_term = state.integral

        # ── Derivative (filtered) ──
        # HeadwayModel'den gelen analitik türevi kullan
        # İşaret: headway azalıyorsa (derivative < 0) → hold gerekir
        d_term = self.kd * (-headway_state.headway_derivative)

        # Derivative kick engellemesi: büyük sıçramalarda kısıtla
        d_term = max(-self.u_max * 0.5, min(self.u_max * 0.5, d_term))

        # ── Toplam ──
        raw_output = p_term + i_term + d_term

        # ── Saturation ──
        # Hold time negatif olamaz ve u_max'ı geçemez
        hold_time = max(0.0, min(self.u_max, raw_output))
        saturated = (raw_output != hold_time)

        # ── Anti-windup back-calculation ──
        # Satürasyona ulaşıldıysa, integral bileşeni geri hesaplamayla düzelt
        if saturated:
            saturation_error = hold_time - raw_output
            state.integral += self.anti_windup_gain * saturation_error * self.dt

        # ── State güncelle ──
        state.prev_error = error
        state.prev_output = hold_time

        return PIDOutput(
            vehicle_id=headway_state.vehicle_id,
            hold_time=hold_time,
            p_term=p_term,
            i_term=i_term,
            d_term=d_term,
            raw_output=raw_output,
            error=error,
            saturated=saturated,
        )

    def compute_all(
        self,
        headway_states: List[HeadwayState],
        at_stop_flags: dict[int, bool] | None = None,
    ) -> List[PIDOutput]:
        """
        Tüm araçlar için PID çıktılarını hesapla.

        Args:
            headway_states: HeadwayModel'den gelen durumlar
            at_stop_flags: {vehicle_id: bool} — durakta mı

        Returns:
            Her araç için PIDOutput listesi
        """
        if at_stop_flags is None:
            at_stop_flags = {}

        return [
            self.compute_single(
                hs,
                at_stop=at_stop_flags.get(hs.vehicle_id, False),
            )
            for hs in headway_states
        ]

    def set_gains(self, kp: float, ki: float, kd: float) -> None:
        """PID kazançlarını güncelle (tuning sonrası)."""
        self.kp = kp
        self.ki = ki
        self.kd = kd

    def reset(self) -> None:
        """Tüm araçların PID durumunu sıfırla."""
        self._states.clear()

    def reset_vehicle(self, vehicle_id: int) -> None:
        """Tek aracın PID durumunu sıfırla."""
        if vehicle_id in self._states:
            del self._states[vehicle_id]

    def get_gains(self) -> dict:
        """Mevcut kazançları döndür."""
        return {"kp": self.kp, "ki": self.ki, "kd": self.kd}

    def __repr__(self) -> str:
        return (
            f"PIDController(Kp={self.kp}, Ki={self.ki}, Kd={self.kd}, "
            f"dt={self.dt}, u_max={self.u_max})"
        )
