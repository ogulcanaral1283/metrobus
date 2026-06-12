"""
Durak Varış Yardımcı Modülü
============================

SmartStop tarafından kullanılan ETA hesaplama ve dwell tahmini.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

import numpy as np

try:
    from ..config import DEFAULT_CONFIG
except ImportError:
    from config import DEFAULT_CONFIG

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

# ── Dwell dağılımı (sahada ölçülen gerçek davranış) ──────────────
# Gerçek metrobüs dwell'i [15,30] sn arası, ortalama ~18-20, kütlesinin
# çoğu 15-20 sn'de ve sağa çarpık (max 30 nadir). Durağa göre DEĞİL,
# ziyaret başına rastgele. Bunu kaydırılmış kesik üstel ile modelliyoruz:
#     dwell = min(MAX, MIN - θ·ln(1-u)),  u ~ U[0,1)
# θ tek "büyüklük" parametresi: küçük → tabana toplanır, büyük → tail uzar.
# config.min/max_dwell_time aralığın tek otoritesidir (15/30).
_DWELL_THETA_NORMAL = 4.0   # normal saat → ort ~18.9 sn, ~%71'i 15-20 sn
_DWELL_THETA_RUSH   = 6.0   # yoğun saat → ort ~20.5 sn, 30 sn'ye ulaşma daha sık


# ═══════════════════════════════════════════
# Fonksiyonlar
# ═══════════════════════════════════════════

def compute_eta(
    distance: float,
    current_speed: float,
    approach_distance: float = 150.0,
    comfort_braking: float = 3.5,
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


def _dwell_theta(is_rush_hour: bool) -> float:
    """Saate göre dwell dağılımının θ (büyüklük) parametresi."""
    return _DWELL_THETA_RUSH if is_rush_hour else _DWELL_THETA_NORMAL


def estimate_dwell(stop: "LinearStop", is_rush_hour: bool = False) -> float:
    """Dwell BEKLENEN değeri — kontrolcü tahmini için.

    sample_dwell ile aynı dağılımın analitik ortalamasını döndürür:
        E[min(MAX, MIN + Exp(θ))] = MIN + θ·(1 - e^(-(MAX-MIN)/θ))
    Gerçek dwell sample_dwell ile rastgele örneklenir; scheduler ileride
    varacak araçların slotunu bu beklenen değerle rezerve eder (gerçek
    hayatta bir aracın ne kadar duracağını önceden bilemeyip ortalamayla
    plan yapmak gibi). Araç bir kez durunca dwell_remaining kesin bilinir,
    bu yüzden tahmin hatası yalnızca henüz varmamış araçları etkiler.
    """
    lo = DEFAULT_CONFIG.min_dwell_time
    hi = DEFAULT_CONFIG.max_dwell_time
    theta = _dwell_theta(is_rush_hour)
    span = hi - lo
    return lo + theta * (1.0 - math.exp(-span / theta))


def sample_dwell(
    rng: Optional[np.random.Generator] = None,
    is_rush_hour: bool = False,
) -> float:
    """Gerçek dwell süresini örnekle — kaydırılmış kesik üstel dağılım.

    dwell = min(MAX, MIN - θ·ln(1-u)),  u ~ U[0,1)
    Sağa çarpık: çoğu ziyaret tabana (15-20 sn) yakın, 30 sn nadir.
    Durağa göre DEĞİL — ziyaret başına rastgele (sahada ölçülen davranış).
    """
    if rng is None:
        rng = np.random.default_rng()
    lo = DEFAULT_CONFIG.min_dwell_time
    hi = DEFAULT_CONFIG.max_dwell_time
    theta = _dwell_theta(is_rush_hour)
    u = float(rng.random())
    dwell = lo - theta * math.log(1.0 - u)
    return min(hi, dwell)
