"""
Durak-Slot Merkezli Akıllı Kontrol Motoru — 4 Aşamalı Sistem

Aşama 1: StationArrivalScheduler — Durak varış zamanlaması (slot çizelgesi)
Aşama 2: PIDController           — Slot-timing error tabanlı PID düzeltme
Aşama 3: SpeedProfiler           — Enerji-optimal hız profili
Aşama 4: CascadeCoordinator      — Çok-duraklı cascade propagasyon

Destek:
  HeadwayModel — Headway dinamiği (metrik + dashboard)

Birleştirme: ControlMerger — 4 aşama + güvenlik → final komut
"""

from .headway_model import HeadwayModel, HeadwayState
from .pid_controller import PIDController
from .station_arrival_scheduler import StationArrivalScheduler, ArrivalPlan, StationSchedule
from .speed_profile import SpeedProfiler, SpeedCommand
from .cascade_coordinator import CascadeCoordinator, CoordinatedPlan
from .control_merger import ControlMerger, ControlCommand

__all__ = [
    "HeadwayModel",
    "HeadwayState",
    "PIDController",
    "StationArrivalScheduler",
    "ArrivalPlan",
    "StationSchedule",
    "SpeedProfiler",
    "SpeedCommand",
    "CascadeCoordinator",
    "CoordinatedPlan",
    "ControlMerger",
    "ControlCommand",
]
