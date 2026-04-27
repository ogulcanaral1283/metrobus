"""
Simülasyon Konfigürasyon Sabitleri & Dataclass'lar
TypeScript sim-types.ts'den Python'a taşındı.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

# Sabit zaman adımı (saniye) — RL eğitiminde kararlılık için
DT: float = 0.1

# Araç boyu (metre) — Mercedes-Benz Citaro metrobüs (TS vehicleType.lengthMeters ile senkron)
VEHICLE_LENGTH: float = 20.0

# Araç fazları
VehiclePhase = Literal[
    "cruising", "approaching", "queued", "docking",
    "stopped", "doorsClosed", "blocked", "departing",
]

# Yön
Direction = Literal["gidis", "donus"]


@dataclass
class SimConfig:
    """Simülasyon konfigürasyonu — TypeScript SimConfig interface karşılığı."""

    # === Fizik ===
    max_acceleration: float = 1.0       # m/s²
    comfort_braking: float = 2.0        # m/s²
    emergency_braking: float = 4.5      # m/s²
    max_speed: float = 14.0             # m/s (~50 km/h)

    # === IDM ===
    idm_min_gap: float = 2.0            # metre
    idm_time_headway: float = 1.5       # saniye
    idm_delta: int = 4                  # IDM delta üssü

    # === Durak ===
    door_time: float = 5.0              # saniye
    per_passenger_time: float = 1.5     # saniye/yolcu
    min_dwell_time: float = 15.0        # saniye
    max_dwell_time: float = 30.0        # saniye
    approach_distance: float = 150.0    # metre

    # === Trafik ===
    traffic_spawn_rate: float = 0.005   # per tick olasılık (yoğun)
    traffic_duration: float = 120.0     # saniye

    # === Hız limiti ===
    default_speed_limit: float = 12.5   # m/s (~45 km/h)

    # === Genel ===
    vehicle_count: int = 15
    time_scale: float = 1.0             # RL'de 1.0 (gerçek zamanlı)


@dataclass
class SimVehicle:
    """Simüle edilen araç."""

    id: int
    position_meters: float          # hat üzerindeki metre pozisyon
    speed: float                    # m/s
    acceleration: float = 0.0       # m/s²
    phase: VehiclePhase = "cruising"
    direction: Direction = "gidis"
    dwell_remaining: float = 0.0    # saniye
    next_stop_index: int = 0
    total_stops: int = 0
    total_distance: float = 0.0
    last_dwell_time: float = 0.0    # son durakta kalınan süre (obs için)
    skip_next_stop: bool = False    # RL aksiyonu: sonraki durağı atla
    holding_extra: float = 0.0      # RL aksiyonu: ek bekleme süresi
    queue_wait_time: float = 0.0    # kuyrukta fiziksel bekleme süresi (sn)
    is_queuing: bool = False         # kuyrukta mı (durak dolu)
    slot_meter_position: float = 0.0 # perondaki atanmış pozisyon

    def copy(self) -> SimVehicle:
        """Shallow copy."""
        return SimVehicle(
            id=self.id,
            position_meters=self.position_meters,
            speed=self.speed,
            acceleration=self.acceleration,
            phase=self.phase,
            direction=self.direction,
            dwell_remaining=self.dwell_remaining,
            next_stop_index=self.next_stop_index,
            total_stops=self.total_stops,
            total_distance=self.total_distance,
            last_dwell_time=self.last_dwell_time,
            skip_next_stop=self.skip_next_stop,
            holding_extra=self.holding_extra,
            queue_wait_time=self.queue_wait_time,
            is_queuing=self.is_queuing,
            slot_meter_position=self.slot_meter_position,
        )


@dataclass
class TrafficZone:
    """Trafik tıkanıklık bölgesi."""

    start_meter: float
    end_meter: float
    max_speed_ms: float
    remaining_seconds: float
    severity: Literal["light", "moderate", "heavy"] = "light"


# Varsayılan config
DEFAULT_CONFIG = SimConfig()
