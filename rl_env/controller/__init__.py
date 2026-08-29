"""
SmartStop Tabanlı Akıllı Kontrol Motoru
========================================

Mimari:
  StopInterface    — Duraklar arası iletişim katmanı (paylaşımlı durum)
  SmartStop        — Tek durak bölgesi yöneticisi (O(1-2) araç/tick)
  ControlMerger    — SmartStop orchestrator + forward safety

Destek:
  HeadwayModel     — Headway dinamiği (yalnızca metrik / dashboard)
"""

from .headway_model import HeadwayModel, HeadwayState
from .stop_interface import StopInterface, StopZoneState
from .smart_stop import SmartStop, SpeedRecommendation, build_smart_stops
from .control_merger import ControlMerger, ControlCommand

__all__ = [
    # Headway (metrik)
    "HeadwayModel",
    "HeadwayState",
    # SmartStop sistemi
    "StopInterface",
    "StopZoneState",
    "SmartStop",
    "SpeedRecommendation",
    "build_smart_stops",
    # Kontrol
    "ControlMerger",
    "ControlCommand",
]
