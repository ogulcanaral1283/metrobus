"""
Durak Arayüzü — SmartStop'lar Arası İletişim Katmanı
=====================================================

Her SmartStop kendi bölgesinin durumunu bu arayüze yayınlar.
Diğer duraklar bu bilgileri okuyarak koordineli kararlar alır.

Yayınlanan bilgiler:
    - Bölgedeki araç sayısı ve fazları
    - Slot doluluk durumu
    - Yaklaşan araçların ETA'ları
    - Tıkanıklık seviyesi (congestion_level)

Kullanım:
    interface = StopInterface()

    # Her SmartStop kendi durumunu yayınlar
    interface.publish(stop_index=5, state=my_state)

    # Komşu durakların durumunu okur
    ds_pressure = interface.get_downstream_pressure(stop_index=5, lookahead=2)
    us_density  = interface.get_upstream_density(stop_index=5, lookbehind=2)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class StopZoneState:
    """
    Bir durağın anlık bölge durumu.

    SmartStop tarafından her tick hesaplanır ve StopInterface'e yayınlanır.
    Komşu duraklar bu veriyi okuyarak koordineli karar alır.
    """
    stop_index: int
    stop_name: str

    # ── Bölgedeki araçlar ──────────────────────────────────────────
    vehicles_in_zone: int                   # cruising/approaching araç sayısı
    phase_counts: Dict[str, int]            # {"cruising": 2, "approaching": 1, ...}

    # ── Slot durumu ────────────────────────────────────────────────
    occupied_slots: int                     # şu an dolu slot sayısı
    slot_capacity: int                      # toplam slot kapasitesi

    # ── Yaklaşan araçların ETA'ları ────────────────────────────────
    incoming_etas: List[float]              # saniye cinsinden, küçükten büyüğe

    # ── Türetilmiş metrikler ───────────────────────────────────────
    congestion_level: float                 # 0.0 = boş  →  1.0+ = yığılma
    overflow_count: int                     # kapasiteden fazla yaklaşan araç

    # ── Zaman damgası ──────────────────────────────────────────────
    sim_time: float                         # bu durum ne zaman hesaplandı (sim saniyesi)


class StopInterface:
    """
    Tüm SmartStop'ların paylaştığı iletişim katmanı.

    Her SmartStop:
        1. Kendi durumunu publish() ile yayınlar.
        2. Komşularının durumunu get_state() ile okur.
        3. Downstream baskıyı get_downstream_pressure() ile hesaplar.
        4. Upstream yoğunluğu get_upstream_density() ile hesaplar.

    Merkezi bir koordinatör yoktur — duraklar bu arayüz üzerinden
    dolaylı olarak koordineli davranır.
    """

    def __init__(self) -> None:
        self._states: Dict[int, StopZoneState] = {}

    # ──────────────────────────────────────────────────────────────
    # Yayın / Okuma
    # ──────────────────────────────────────────────────────────────

    def publish(self, stop_index: int, state: StopZoneState) -> None:
        """Durak kendi bölge durumunu yayınlar."""
        self._states[stop_index] = state

    def get_state(self, stop_index: int) -> Optional[StopZoneState]:
        """Bir durağın en son yayınlanan durumunu al. Yoksa None."""
        return self._states.get(stop_index)

    # ──────────────────────────────────────────────────────────────
    # Komşu Baskı Hesaplamaları
    # ──────────────────────────────────────────────────────────────

    def get_downstream_pressure(
        self,
        stop_index: int,
        lookahead: int = 2,
    ) -> float:
        """
        Downstream durakların toplam tıkanıklık baskısını hesapla.

        Yöntem:
            İlerideki her durak için congestion_level alınır.
            Uzaktaki durakların etkisi üssel olarak azalır (weight *= 0.6).

        Returns:
            0.0  → downstream tamamen boş
            1.0+ → ciddi tıkanıklık var
        """
        total = 0.0
        weight = 1.0
        for i in range(1, lookahead + 1):
            state = self._states.get(stop_index + i)
            if state is not None:
                total += state.congestion_level * weight
            weight *= 0.6
        return total

    def get_upstream_density(
        self,
        stop_index: int,
        lookbehind: int = 2,
    ) -> float:
        """
        Upstream bölgelerdeki araç yoğunluğunu hesapla.

        Bu durağa yakında kaç araç akacağını tahmin eder.
        Her upstream bölgenin vehicles_in_zone / slot_capacity oranı kullanılır.

        Returns:
            0.0  → upstream boş, az araç geliyor
            1.0+ → yoğun akış bekleniyor
        """
        total = 0.0
        weight = 1.0
        for i in range(1, lookbehind + 1):
            state = self._states.get(stop_index - i)
            if state is not None:
                density = state.vehicles_in_zone / max(state.slot_capacity, 1)
                total += density * weight
            weight *= 0.6
        return total

    # ──────────────────────────────────────────────────────────────
    # Genel Sorgular
    # ──────────────────────────────────────────────────────────────

    def get_all_states(self) -> Dict[int, StopZoneState]:
        """Tüm durak durumlarını döndür (dashboard / debug için)."""
        return dict(self._states)

    def most_congested_stop(self) -> Optional[StopZoneState]:
        """En yüksek congestion_level'a sahip durağı döndür."""
        if not self._states:
            return None
        return max(self._states.values(), key=lambda s: s.congestion_level)

    def total_overflow_count(self) -> int:
        """Tüm hattaki toplam taşma sayısı."""
        return sum(s.overflow_count for s in self._states.values())

    def reset(self) -> None:
        """Tüm durumları sıfırla (yeni episode başında çağrılır)."""
        self._states.clear()
