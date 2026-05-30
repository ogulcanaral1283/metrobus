"""
Durak Varış Yardımcı Modülü
============================

SmartStop tarafından kullanılan ETA hesaplama ve dwell tahmini.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from ..route_data import LinearStop
    except ImportError:
        from route_data import LinearStop


# ═══════════════════════════════════════════
# Sabitler
# ═══════════════════════════════════════════

# Slot boşalma sonrası güvenlik tamponu (s)
SLOT_BUFFER_SECONDS = 2.0

# Kapı kapanma + kalkış süresi (s): doorsClosed (2s) + departing ivme (~2s)
DEPARTURE_OVERHEAD = 4.0

# Minimum seyir hızı (m/s) — durmuş araç için ETA tahmini
MIN_CRUISE_SPEED = 3.0

# Dwell süresi tahmin sabitleri
_DWELL_BASE_NORMAL = 20.0
_DWELL_BASE_RUSH   = 26.0
_DWELL_DOOR_TIME   = 1.0


# ═══════════════════════════════════════════
# Fonksiyonlar
# ═══════════════════════════════════════════

def compute_eta(
    distance: float,
    current_speed: float,
    approach_distance: float = 150.0,
    comfort_braking: float = 2.0,
) -> float:
    """
    Kinematik ETA — iki fazlı model.

    Faz 1: Serbest seyir (mevcut hız)
    Faz 2: Frenleme eğrisi (approach mesafesinde yavaşla)
    """
    if distance <= 0:
        return 0.0
    if current_speed < 0.5:
        return distance / MIN_CRUISE_SPEED

    if distance <= approach_distance:
        v_entry = min(current_speed, math.sqrt(2.0 * comfort_braking * distance))
        avg_speed = max(v_entry / 2.0, 0.5)
        return distance / avg_speed

    cruise_dist = distance - approach_distance
    t_cruise = cruise_dist / current_speed
    v_entry = min(current_speed, math.sqrt(2.0 * comfort_braking * approach_distance))
    t_brake = approach_distance / max(v_entry / 2.0, 0.5)
    return t_cruise + t_brake


def estimate_dwell(stop: "LinearStop", is_rush_hour: bool = False) -> float:
    """Deterministik dwell süresi tahmini."""
    base = _DWELL_BASE_RUSH if is_rush_hour else _DWELL_BASE_NORMAL
    return _DWELL_DOOR_TIME + base
