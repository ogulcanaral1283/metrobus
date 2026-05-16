"""
Aşama 3 — Enerji-Optimal Hız Profili
=======================================

ideal_varış_zamanı biliniyor (Aşama 1'den).
Bu modül, o zamana ulaşan EN DÜZ hız profilini hesaplar.

Prensip:
    Enerji tüketimi ∝ Σ|a(t)|²
    Sert fren + sert gaz = yüksek enerji
    Yumuşak geçiş + sabit hız = düşük enerji

3 Fazlı Profil:
    Faz 1: v_current → v_cruise (yumuşak geçiş)
    Faz 2: v_cruise sabit (en uzun faz — enerji tasarrufu)
    Faz 3: v_cruise → 0 (durağa frenleme — approach bölgesi)

Çözüm:
    v_cruise = (d - d_brake) / (t_ideal - t_brake)
    Tek bilinmeyen: v_cruise
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# ═══════════════════════════════════════════
# Sabitler
# ═══════════════════════════════════════════

# Hız geçiş yumuşaklığı: her tick'te max hız değişimi (m/s)
MAX_SPEED_CHANGE_PER_TICK = 0.3  # 0.1s tick → 3 m/s² max jerk

# Minimum pratik cruise hızı (m/s)
MIN_CRUISE_SPEED = 3.0

# Approach mesafesi — frenleme başlangıcı (m)
DEFAULT_APPROACH_DISTANCE = 150.0


# ═══════════════════════════════════════════
# Veri Yapıları
# ═══════════════════════════════════════════

@dataclass
class SpeedCommand:
    """Tek araç için hız profili komutu."""
    vehicle_id: int
    target_speed: float         # hedef cruise hızı (m/s)
    speed_factor: float         # mevcut max_speed'e oran [0.3, 1.2]
    phase: str                  # "cruise" | "transition" | "approach" | "none"
    energy_saving: float        # tahmini enerji tasarrufu (0-1, 1=max)
    distance_to_stop: float     # durağa kalan mesafe
    time_budget: float          # kalan zaman bütçesi (s)


# ═══════════════════════════════════════════
# Hız Profili Hesaplayıcı
# ═══════════════════════════════════════════

class SpeedProfiler:
    """
    Enerji-optimal hız profili hesaplayıcı.

    Verilen mesafe ve zaman bütçesiyle en düz
    (minimum ivme değişimi) hız profilini üretir.
    """

    def __init__(
        self,
        max_speed: float = 14.0,
        approach_distance: float = DEFAULT_APPROACH_DISTANCE,
        comfort_braking: float = 2.0,
        max_acceleration: float = 1.0,
    ):
        self.max_speed = max_speed
        self.approach_distance = approach_distance
        self.comfort_braking = comfort_braking
        self.max_acceleration = max_acceleration

    def compute(
        self,
        vehicle_id: int,
        current_speed: float,
        distance: float,
        time_budget: float,
    ) -> SpeedCommand:
        """
        Enerji-optimal hız komutu hesapla.

        Args:
            vehicle_id:   Araç ID
            current_speed: Mevcut hız (m/s)
            distance:     Durağa mesafe (m)
            time_budget:  İdeal varış zamanı (s) — Aşama 1'den

        Returns:
            SpeedCommand — hedef hız + speed_factor
        """
        # Müdahale gerekmiyor
        if distance <= 0 or time_budget <= 0:
            return SpeedCommand(
                vehicle_id=vehicle_id,
                target_speed=current_speed,
                speed_factor=1.0,
                phase="none",
                energy_saving=0.0,
                distance_to_stop=distance,
                time_budget=time_budget,
            )

        # Frenleme fazı parametreleri (Faz 3)
        approach_dist = min(self.approach_distance, distance * 0.4)
        v_brake_entry = math.sqrt(2.0 * self.comfort_braking * approach_dist)
        v_brake_entry = min(v_brake_entry, self.max_speed)
        t_brake = v_brake_entry / self.comfort_braking

        # Cruise fazı (Faz 2) — kalan mesafe ve süre
        cruise_dist = distance - approach_dist
        cruise_time = time_budget - t_brake

        if cruise_time <= 0:
            # Zaman yetmiyor, zaten frenleme bölgesinde
            return SpeedCommand(
                vehicle_id=vehicle_id,
                target_speed=current_speed,
                speed_factor=1.0,
                phase="approach",
                energy_saving=0.0,
                distance_to_stop=distance,
                time_budget=time_budget,
            )

        # Optimal cruise hızı
        v_cruise = cruise_dist / cruise_time

        # Sınırlandırma
        if v_cruise < MIN_CRUISE_SPEED:
            v_cruise = MIN_CRUISE_SPEED
        elif v_cruise > self.max_speed:
            v_cruise = self.max_speed

        # Speed factor hesapla
        speed_factor = v_cruise / self.max_speed
        speed_factor = max(0.3, min(1.2, speed_factor))

        # Faz belirleme
        if distance <= approach_dist:
            phase = "approach"
        elif abs(current_speed - v_cruise) > 1.0:
            phase = "transition"
        else:
            phase = "cruise"

        # Enerji tasarrufu tahmini
        # Normal seyir: max_speed ile git → frenle → bekle → hızlan
        # Optimal: v_cruise ile git → frenle (daha yumuşak)
        # Tasarruf ∝ (v_max - v_cruise) / v_max
        energy_saving = max(0.0, (self.max_speed - v_cruise) / self.max_speed)

        return SpeedCommand(
            vehicle_id=vehicle_id,
            target_speed=v_cruise,
            speed_factor=speed_factor,
            phase=phase,
            energy_saving=energy_saving,
            distance_to_stop=distance,
            time_budget=cruise_time + t_brake,
        )

    def smooth_speed_transition(
        self,
        current_speed: float,
        target_speed: float,
        dt: float = 0.1,
    ) -> float:
        """
        Yumuşak hız geçişi — jerk sınırı uygular.

        Ani hız değişimi yerine her tick'te max MAX_SPEED_CHANGE_PER_TICK
        kadar değişim. Yolcu konforu için kritik.

        Returns: bu tick'te uygulanacak hız (m/s)
        """
        diff = target_speed - current_speed
        max_change = MAX_SPEED_CHANGE_PER_TICK  # per tick (0.1s)

        if abs(diff) <= max_change:
            return target_speed

        if diff > 0:
            return current_speed + max_change
        else:
            return current_speed - max_change
