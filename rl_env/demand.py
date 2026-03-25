"""
Yolcu Talep Profilleri
Rehber Asama 2.6: Her durak icin saatlik yogunluk carpanlari.
Gercekci Istanbul metrobus yolculuk oruntuleri.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np


@dataclass
class DemandProfile:
    """Durak bazli yolcu talep profili."""

    # Durak adi -> saat bazli yogunluk carpanlari (0.0-1.0)
    profiles: Dict[str, Dict[int, float]]
    # Durak kategorileri
    categories: Dict[str, str]  # durak_adi -> "merkez"|"ucak"|"konut"|"is"

    @classmethod
    def create_default(cls) -> DemandProfile:
        """Istanbul metrobus hattina ozgu varsayilan talep profilleri."""

        # --- Durak kategorileri ---
        # Merkez: Her zaman yogun (Mecidiyekoy, Zincirlikuyu, Merter)
        # Is: Sabah gelir, aksam gider (Levent, Gayrettepe, 4.Levent)
        # Konut: Sabah gider, aksam gelir (Avcilar, Beylikduzu, Halkali)
        # Ucak: Uclardaki duraklar, dusuuk yogunluk

        merkez_duraklar = [
            "Mecidiyekoy", "Zincirlikuyu", "Merter", "Cevizlibag",
            "Topkapi", "Edirnekapı", "Ayvansaray",
        ]
        is_duraklar = [
            "4.Levent", "Levent", "Gayrettepe", "Sisli",
            "Okmeydani", "Kagithane",
        ]
        konut_duraklar = [
            "Avcilar", "Beylikduzu", "Halkali", "Bahcelievler",
            "Sefakoy", "Kucukcekmece", "Avcılar Konaklari",
        ]

        categories = {}
        for d in merkez_duraklar:
            categories[d] = "merkez"
        for d in is_duraklar:
            categories[d] = "is"
        for d in konut_duraklar:
            categories[d] = "konut"

        # --- Saatlik profiller ---
        hourly_patterns = {
            # Merkez: sabah ve aksam pik, gunduz de yogun
            "merkez": {
                5: 0.1, 6: 0.3, 7: 0.7, 8: 1.0, 9: 0.8,
                10: 0.5, 11: 0.4, 12: 0.5, 13: 0.5, 14: 0.4,
                15: 0.5, 16: 0.6, 17: 0.9, 18: 1.0, 19: 0.8,
                20: 0.5, 21: 0.3, 22: 0.2, 23: 0.1,
            },
            # Is: sabah cok yogun, aksam yogun (eve donus)
            "is": {
                5: 0.1, 6: 0.2, 7: 0.6, 8: 1.0, 9: 0.9,
                10: 0.3, 11: 0.2, 12: 0.3, 13: 0.3, 14: 0.2,
                15: 0.3, 16: 0.5, 17: 0.8, 18: 1.0, 19: 0.7,
                20: 0.3, 21: 0.2, 22: 0.1, 23: 0.05,
            },
            # Konut: sabah yogun (ise gidis), aksam yogun (eve donus)
            "konut": {
                5: 0.1, 6: 0.4, 7: 0.8, 8: 1.0, 9: 0.6,
                10: 0.2, 11: 0.15, 12: 0.2, 13: 0.2, 14: 0.15,
                15: 0.2, 16: 0.4, 17: 0.7, 18: 0.9, 19: 0.8,
                20: 0.4, 21: 0.2, 22: 0.1, 23: 0.05,
            },
            # Ucak: dusuk ve flat
            "ucak": {
                5: 0.05, 6: 0.1, 7: 0.3, 8: 0.5, 9: 0.4,
                10: 0.3, 11: 0.2, 12: 0.25, 13: 0.25, 14: 0.2,
                15: 0.25, 16: 0.3, 17: 0.5, 18: 0.6, 19: 0.4,
                20: 0.2, 21: 0.15, 22: 0.1, 23: 0.05,
            },
        }

        profiles: Dict[str, Dict[int, float]] = {}
        for durak, cat in categories.items():
            profiles[durak] = hourly_patterns[cat]

        return cls(profiles=profiles, categories=categories)

    def get_demand_multiplier(
        self,
        stop_name: str,
        hour: float,
        is_weekend: bool = False,
    ) -> float:
        """
        Durak ve saat bazli talep carpanini dondur.

        Args:
            stop_name: Durak adi
            hour: Saati (float, 7.5 = 07:30)
            is_weekend: Hafta sonu mu
        """
        # Profildeki en yakin saati bul
        hour_int = max(5, min(23, int(hour)))

        if stop_name in self.profiles:
            base = self.profiles[stop_name].get(hour_int, 0.3)
        else:
            # Bilinmeyen durak -> orta duzey
            base = 0.3

        # Hafta sonu %40 azaltma
        if is_weekend:
            base *= 0.6

        return base

    def get_passenger_count(
        self,
        stop_name: str,
        hour: float,
        is_weekend: bool = False,
        rng: Optional[np.random.Generator] = None,
    ) -> int:
        """Talep profiline gore yolcu sayisi uret."""
        if rng is None:
            rng = np.random.default_rng()
        multiplier = self.get_demand_multiplier(stop_name, hour, is_weekend)
        base_passengers = 5 + int(multiplier * 20)

        # ±%15 rastgele gurultu
        noise = 1.0 + float(rng.uniform(-0.15, 0.15))
        return max(1, round(base_passengers * noise))

    def get_dwell_time(
        self,
        stop_name: str,
        hour: float,
        door_time: float = 5.0,
        per_passenger_time: float = 1.5,
        is_weekend: bool = False,
        rng: Optional[np.random.Generator] = None,
    ) -> float:
        """
        Talep profiline gore dwell suresi hesapla.
        door_time + yolcu_sayisi * per_passenger_time + gurultu
        """
        if rng is None:
            rng = np.random.default_rng()
        passengers = self.get_passenger_count(stop_name, hour, rng=rng)
        raw = door_time + passengers * per_passenger_time

        # ±%15 gurultu
        noise = 1.0 + float(rng.uniform(-0.15, 0.15))
        return max(10.0, min(90.0, raw * noise))


# Varsayilan talep profili
DEFAULT_DEMAND = DemandProfile.create_default()
