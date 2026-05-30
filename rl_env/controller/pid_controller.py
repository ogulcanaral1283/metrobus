"""
PID Kontrolcü — Stub
====================

PID aktif olarak kullanılmıyor. SmartStop sistemi tüm hız
regülasyonunu üstleniyor.

Buradaki sınıf yalnızca dashboard'da kazanç bilgisi göstermek
(get_gains) ve episode sıfırlamak (reset) için tutulmaktadır.
ControlMerger'a geriye uyumluluk amacıyla geçilmektedir.
"""

from __future__ import annotations


class PIDController:
    """Pasif stub — yalnızca get_gains/reset/reset_vehicle aktif."""

    def __init__(
        self,
        kp: float = 0.4,
        ki: float = 0.02,
        kd: float = 0.15,
        **kwargs,
    ):
        self.kp = kp
        self.ki = ki
        self.kd = kd

    def reset(self) -> None:
        pass

    def reset_vehicle(self, vehicle_id: int) -> None:
        pass

    def get_gains(self) -> dict:
        return {"kp": self.kp, "ki": self.ki, "kd": self.kd}

    def __repr__(self) -> str:
        return f"PIDController(Kp={self.kp}, Ki={self.ki}, Kd={self.kd})"
