"""
Trafik Bölge Yönetimi
TypeScript traffic.ts'den Python'a taşındı.
Rastgele tıkanıklık oluşturma/çözme + rush hour
"""

from __future__ import annotations

from typing import Optional

import numpy as np

try:
    from .config import SimConfig, TrafficZone
except ImportError:
    from config import SimConfig, TrafficZone


def update_traffic_zones(
    zones: list[TrafficZone],
    dt: float,
    route_length: float,
    config: SimConfig,
    is_rush_hour: bool,
    rng: Optional[np.random.Generator] = None,
) -> list[TrafficZone]:
    """
    Trafik bölgelerini güncelle:
    - Mevcut bölgelerin süresini düşür
    - Süresi dolan bölgeleri kaldır
    - Rastgele yeni bölge oluştur
    """
    if rng is None:
        rng = np.random.default_rng()

    # Süreleri düşür, bitenleri kaldır
    active: list[TrafficZone] = []
    for z in zones:
        z.remaining_seconds -= dt
        if z.remaining_seconds > 0:
            active.append(z)

    # Yeni bölge oluştur (rastgele)
    spawn_rate = config.traffic_spawn_rate * 3 if is_rush_hour else config.traffic_spawn_rate
    if float(rng.random()) < spawn_rate * dt and len(active) < 5:
        severity = _pick_severity(is_rush_hour, rng)
        start = 500 + float(rng.random()) * (route_length - 1000)
        length = 200 + float(rng.random()) * 500

        active.append(TrafficZone(
            start_meter=start,
            end_meter=start + length,
            max_speed_ms=_severity_to_speed(severity),
            remaining_seconds=config.traffic_duration * (0.5 + float(rng.random())),
            severity=severity,
        ))

    return active


def check_rush_hour(sim_time_seconds: float, start_hour: float = 6.0) -> bool:
    """
    Simülasyon saatine göre rush hour kontrolü.
    Sabah: 07:00-09:30, Akşam: 17:00-19:30

    Args:
        sim_time_seconds: simülasyon zamanı (saniye)
        start_hour: simülasyonun başladığı saat (varsayılan 6.0)
    """
    hour_of_day = start_hour + (sim_time_seconds / 3600) % 24
    return (7 <= hour_of_day <= 9.5) or (17 <= hour_of_day <= 19.5)


def _pick_severity(is_rush_hour: bool, rng: np.random.Generator) -> str:
    """Trafik bölgesi şiddeti seç."""
    r = float(rng.random())
    if is_rush_hour:
        if r < 0.3:
            return "heavy"
        if r < 0.7:
            return "moderate"
        return "light"
    if r < 0.1:
        return "heavy"
    if r < 0.3:
        return "moderate"
    return "light"


def _severity_to_speed(severity: str) -> float:
    """Trafik şiddetine göre max hız (m/s)."""
    if severity == "heavy":
        return 2.0    # ~7 km/h
    if severity == "moderate":
        return 5.5    # ~20 km/h
    return 11.0       # ~40 km/h (light)
