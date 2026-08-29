"""
Durak Talep Modeli — İBB/BELBİM turnike verisinden
===================================================

data/station_demand_hourly.csv: durak x saat, hafta içi ortalama yolcu/saat
(Ekim 2024, İBB Açık Veri Portalı / BELBİM). Turnike girişleri iki yönün
toplamı olduğundan değerler mutlak biniş değil, durak AĞIRLIĞI olarak
kullanılır: skip-stop kararında "bu durak bu saatte düşük talepli mi?"
sorusuna cevap verir.

Tamamen analitik: veri tablosu + yüzdelik eşiği. ML yok.
"""

from __future__ import annotations

import csv
import os
from typing import Dict, List, Optional

_DATA_FILE = os.path.join(os.path.dirname(__file__), "data",
                          "station_demand_hourly.csv")

# Bir durak, o saatteki durak-talep dağılımının bu yüzdeliğinin ALTINDAysa
# "düşük talepli" sayılır ve skip adayı olur. (ör. Mecidiyeköy hiçbir saatte
# bu eşiğin altına inmez → asla atlanmaz.)
LOW_DEMAND_PERCENTILE: float = 30.0


def _percentile(sorted_vals: List[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


class DemandModel:
    """Durak başına saatlik yolcu talebi + saatlik düşük-talep eşiği."""

    def __init__(self, path: str = _DATA_FILE) -> None:
        self._rates: Dict[int, List[float]] = {}
        self.available = False
        if not os.path.exists(path):
            return
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                idx = int(row["stop_index"])
                self._rates[idx] = [float(row[f"h{h:02d}"]) for h in range(24)]
        if not self._rates:
            return
        # Saat başına düşük-talep eşiği (duraklar arası yüzdelik)
        self._low_thresh: List[float] = []
        for h in range(24):
            vals = sorted(r[h] for r in self._rates.values())
            self._low_thresh.append(_percentile(vals, LOW_DEMAND_PERCENTILE))
        self.available = True

    def rate(self, stop_index: int, hour: float) -> float:
        """Durağın o saatteki talebi (yolcu/saat). Veri yoksa +inf (koruma)."""
        r = self._rates.get(stop_index)
        if r is None:
            return float("inf")
        return r[int(hour) % 24]

    def low_threshold(self, hour: float) -> float:
        return self._low_thresh[int(hour) % 24] if self.available else 0.0

    def is_low_demand(self, stop_index: int, hour: float) -> bool:
        """Durak bu saatte koridorun düşük-talepli dilimimde mi?"""
        if not self.available:
            return False   # veri yoksa hicbir durak atlanamaz (guvenli taraf)
        return self.rate(stop_index, hour) <= self.low_threshold(hour)
