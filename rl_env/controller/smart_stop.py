"""
Smart Stop — Durak Bölgesi Akıllı Yöneticisi
=============================================

Her SmartStop bir durağın bölgesinden sorumludur:
    zone = [önceki_durak.meter_position → bu_durak.meter_position]

Sorumluluklar:
    1. Bölgesindeki araçları tespit et  (O(zone_araç_sayısı) ≈ O(1-2))
    2. Slot zaman çizelgesi hesapla
    3. Gecikme bütçesini hesaba kat     (TOTAL_DELAY_BUDGET saniye)
    4. Kost-fayda analizi yap           (yavaşla mı? queue kabul et mi?)
    5. Hız önerisi üret
    6. Durum bilgisini StopInterface'e yayınla

Gecikme Bütçesi:
    Önerimiz şoföre ulaşana ve araç tepki verene kadar geçen toplam
    gecikmeyi temsil eder. Bu süre içinde araç ilerlemeye devam eder.
    Öneri bu mesafe hesaba katılarak üretilir.

Kost-Fayda Analizi:
    Seçenek A (hızı koru → queue'da bekle):
        Bu araç için maliyet  = queue_time (sn)
        Cascade maliyet       = queue_time × arkadaki_araç × CASCADE_FACTOR
        Downstream maliyet    = downstream_pressure × DOWNSTREAM_WEIGHT

    Seçenek B (yavaşla → direkt gir):
        Bu araç için maliyet  = extra_travel_time ≈ queue_time

    Karar: cascade_cost + downstream_cost > intervention_cost → YAVAŞLA
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

try:
    from ..config import SimVehicle, VEHICLE_LENGTH
    from ..route_data import LinearStop
    from .stop_interface import StopInterface, StopZoneState
    from .station_arrival_scheduler import (
        compute_eta,
        estimate_dwell,
        DEPARTURE_OVERHEAD,
        SLOT_BUFFER_SECONDS,
    )
except ImportError:
    from config import SimVehicle, VEHICLE_LENGTH
    from route_data import LinearStop
    from stop_interface import StopInterface, StopZoneState
    from station_arrival_scheduler import (
        compute_eta,
        estimate_dwell,
        DEPARTURE_OVERHEAD,
        SLOT_BUFFER_SECONDS,
    )


# ═══════════════════════════════════════════════════════════════════
# Sabitler
# ═══════════════════════════════════════════════════════════════════

# Toplam gecikme bütçesi (sn):
#   hesaplama ~1s + iletişim ~0.5s + şoför algılama+karar ~4s + araç tepkisi ~2s
TOTAL_DELAY_BUDGET: float = 7.5

# Gecikme bütçesinden sonra kalması gereken minimum etkin mesafe (m)
MIN_EFFECTIVE_DISTANCE: float = 30.0

# Minimum hız çarpanı
MIN_SPEED_FACTOR: float = 0.3

# Cascade faktörü — arkadaki her araç için queue_time çarpanı
CASCADE_FACTOR: float = 0.7

# Downstream baskı ağırlığı
DOWNSTREAM_PRESSURE_WEIGHT: float = 8.0

# [FIX-3] Tek araç için minimum müdahale eşiği (sn)
# Cascade yoksa bile bu kadar queue beklenmesi halinde müdahale et
MIN_QUEUE_TO_INTERVENE: float = 2.0

# [FIX-5] Histerezis tamponu (sn) — salınımı önler
# ETA bu kadar erken olmadıkça müdahale başlatma
INTERVENTION_THRESHOLD: float = 2.0

# [FIX-4] Cascade lookahead penceresi (sn)
# Slot doluyken bu süre içinde gelebilecek araçlar cascade'e dahil edilir
CASCADE_WINDOW: float = 30.0

# [FIX-2] Fiziksel slot hesabı sabitleri (station_fsm.py ile senkron)
_SLOT_SIZE: float = 25.0   # VEHICLE_LENGTH(20) + VEHICLE_GAP_METERS(5)
_BUS_LENGTH: float = 20.0
_SAFE_GAP: float = 0.5

# Faz filtreleri
_ZONE_PHASES = {"cruising", "approaching"}
_PLATFORM_PHASES = {"stopped", "doorsClosed", "blocked", "docking"}


# ═══════════════════════════════════════════════════════════════════
# Veri Yapıları
# ═══════════════════════════════════════════════════════════════════

@dataclass
class SpeedRecommendation:
    """Tek araç için hız önerisi."""
    vehicle_id: int
    speed_factor: float         # [MIN_SPEED_FACTOR, 1.2]
    source: str                 # "smart_stop" | "none"
    reason: str                 # "cascade" | "downstream" | "overflow" | "on_time" | "too_close" | "queue_cheaper"

    # Debug / dashboard bilgileri
    eta_to_stop: float          # mevcut hızla tahmini varış (sn)
    ideal_arrival: float        # slot boşaldığında ideal varış (sn)
    queue_time_avoided: float   # müdahaleyle önlenen bekleme süresi (sn)
    net_benefit: float          # pozitif → yavaşlamak kârlı
    stop_index: int = 0         # hedef durağın index'i


# ═══════════════════════════════════════════════════════════════════
# SmartStop
# ═══════════════════════════════════════════════════════════════════

class SmartStop:
    """
    Tek bir durağın akıllı bölge yöneticisi.

    Her simulation tick'inde update() çağrılır.
    Sadece kendi bölgesindeki araçlara bakar → O(1-2) işlem.
    StopInterface üzerinden komşu durakları dinler ve durumunu yayınlar.
    """

    def __init__(
        self,
        stop: LinearStop,
        zone_start: float,
        interface: StopInterface,
        approach_distance: float = 150.0,
        comfort_braking: float = 2.0,
        max_speed: float = 14.0,
    ) -> None:
        self.stop = stop
        self.zone_start = zone_start            # önceki durağın pozisyonu (m)
        self.zone_end = stop.meter_position     # bu durağın pozisyonu (m)
        self.interface = interface
        self.approach_distance = approach_distance
        self.comfort_braking = comfort_braking
        self.max_speed = max_speed

    # ──────────────────────────────────────────────────────────────
    # Ana Güncelleme Döngüsü
    # ──────────────────────────────────────────────────────────────

    def update(
        self,
        vehicles: List[SimVehicle],
        is_rush_hour: bool,
        sim_time: float,
    ) -> List[SpeedRecommendation]:
        """
        Bölgeyi güncelle, hız önerileri üret, durumu yayınla.

        Akış:
            1. Bölgedeki araçları tespit et
            2. Platform slot timeline oluştur
            3. Downstream baskıyı interface'den oku
            4. Her araç için kost-fayda analizi → SpeedRecommendation
            5. Durumu interface'e yayınla

        Returns:
            Her bölge aracı için bir SpeedRecommendation listesi.
        """
        zone_buses     = self._buses_in_zone(vehicles)
        platform_buses = self._buses_on_platform(vehicles)

        slot_timeline     = self._build_slot_timeline(platform_buses, is_rush_hour)
        downstream_press  = self.interface.get_downstream_pressure(self.stop.index)

        # ETA'ya göre sırala — en erken varacak önce işlenir
        zone_buses_sorted = sorted(
            zone_buses,
            key=lambda v: compute_eta(
                self.zone_end - v.position_meters,
                v.speed,
                self.approach_distance,
                self.comfort_braking,
            ),
        )

        recommendations: List[SpeedRecommendation] = []

        for i, bus in enumerate(zone_buses_sorted):
            # Bu araçtan SONRA bölgeye girecek araçlar (cascade analizi için)
            following = zone_buses_sorted[i + 1:]

            rec = self._compute_recommendation(
                bus, slot_timeline, following, downstream_press, is_rush_hour,
            )
            recommendations.append(rec)

            # [FIX-6] Her araç için slotu GERCEK ETA ile rezerve et.
            # "on_time" ve "too_close" dahil TUM zone araçları slotlarını rezerve
            # etmeli; aksi hâlde takip eden araç aynı slotu boş görür → zincir kırılır.
            actual_eta = compute_eta(
                self.zone_end - bus.position_meters,
                bus.speed,
                self.approach_distance,
                self.comfort_braking,
            )
            _update_slot_timeline(
                slot_timeline, actual_eta, bus.id, self.stop, is_rush_hour,
            )  # arrival_eta = actual_eta (gerçek ETA, yavaşlatılmış değil)

        # Durumu interface'e yayınla
        state = self._build_state(zone_buses, platform_buses, slot_timeline, sim_time)
        self.interface.publish(self.stop.index, state)

        return recommendations

    # ──────────────────────────────────────────────────────────────
    # Araç Filtreleme
    # ──────────────────────────────────────────────────────────────

    def _buses_in_zone(self, vehicles: List[SimVehicle]) -> List[SimVehicle]:
        """
        Bölgedeki hareket halindeki araçlar.
        Koşul: pozisyon bölge içinde VE sonraki durak bu durak VE aktif faz.
        """
        return [
            v for v in vehicles
            if (self.zone_start < v.position_meters <= self.zone_end
                and v.next_stop_index == self.stop.index
                and v.phase in _ZONE_PHASES)
        ]

    def _buses_on_platform(self, vehicles: List[SimVehicle]) -> List[SimVehicle]:
        """
        Platformdaki araçlar — slot işgal edenler.
        Not: 'docking' fazı burada sayılır, zone araçlarından ayrılır.
        """
        return [
            v for v in vehicles
            if (v.next_stop_index == self.stop.index
                and v.phase in _PLATFORM_PHASES)
        ]

    # ──────────────────────────────────────────────────────────────
    # Slot Zaman Çizelgesi
    # ──────────────────────────────────────────────────────────────

    def _build_slot_timeline(
        self,
        platform_buses: List[SimVehicle],
        is_rush_hour: bool,
    ) -> List[Tuple[int, float, Optional[int]]]:
        """
        Slot zaman çizelgesi: [(slot_id, boşalma_zamanı_sn, araç_id), ...]

        Dolu slotlar: perondaki araçların kalan dwell süresi + kalkış overhead'i
        Boş slotlar: arkadan erişilebilir kapasite (boşalma_zamanı = 0.0)

        Not: Araçlar perona arkadan girer. Öndeki boş slotlara
             fiziksel olarak erişilemez, bu yüzden sayılmaz.
        """
        # En öndeki araç en yüksek pozisyonda → reverse sıralı
        sorted_buses = sorted(platform_buses, key=lambda v: v.position_meters, reverse=True)

        slots: List[Tuple[int, float, Optional[int]]] = []

        for slot_id, veh in enumerate(sorted_buses):
            if veh.phase == "stopped":
                free_time = veh.dwell_remaining + DEPARTURE_OVERHEAD
            elif veh.phase == "doorsClosed":
                free_time = veh.dwell_remaining + 2.0
            elif veh.phase == "blocked":
                free_time = 3.0
            elif veh.phase == "docking":
                dwell = estimate_dwell(self.stop, is_rush_hour)
                free_time = 2.0 + dwell + DEPARTURE_OVERHEAD
            else:
                free_time = 0.0
            slots.append((slot_id, free_time, veh.id))

        # [FIX-2] Fiziksel arkadan erişilebilir slot sayısı
        # Araçlar perona arkadan girer → sadece en arkadaki aracın gerisindeki
        # alan erişilebilir. Öndeki boş slotlar fiziksel olarak erişilemez.
        occupied       = len(sorted_buses)
        total_capacity = max(self.stop.slot_count, 1)

        if sorted_buses:
            platform_len = (self.stop.platform_length_meters
                            if self.stop.platform_length_meters > 0 else 60.0)
            platform_tail  = self.zone_end - platform_len
            rearmost       = sorted_buses[-1]           # en düşük pozisyon = en arkada
            rearmost_rear  = rearmost.position_meters - _BUS_LENGTH
            rear_space     = rearmost_rear - platform_tail - _SAFE_GAP
            rear_free      = max(0, min(int(rear_space / _SLOT_SIZE),
                                        total_capacity - occupied))
        else:
            rear_free = total_capacity

        for i in range(rear_free):
            slots.append((occupied + i, 0.0, None))

        return slots

    # ──────────────────────────────────────────────────────────────
    # Kost-Fayda Analizi + Hız Önerisi
    # ──────────────────────────────────────────────────────────────

    def _compute_recommendation(
        self,
        bus: SimVehicle,
        slot_timeline: List[Tuple[int, float, Optional[int]]],
        following_buses: List[SimVehicle],
        downstream_pressure: float,
        is_rush_hour: bool,
    ) -> SpeedRecommendation:
        """
        Tek araç için kost-fayda analizi.

        1. Gecikme bütçesiyle etkin mesafeyi hesapla
        2. ETA ve ideal varış zamanını karşılaştır
        3. Cascade + downstream maliyeti hesapla
        4. En kârlı seçeneği seç
        """
        distance = self.zone_end - bus.position_meters

        # ── 1. Gecikme bütçesi kontrolü ───────────────────────────
        # Öneri şoföre ulaşıp uygulandığında araç bu kadar daha ilerlemiş olur
        effective_distance = distance - bus.speed * TOTAL_DELAY_BUDGET

        if effective_distance < MIN_EFFECTIVE_DISTANCE:
            return SpeedRecommendation(
                vehicle_id=bus.id, speed_factor=1.0,
                source="none", reason="too_close",
                eta_to_stop=0.0, ideal_arrival=0.0,
                queue_time_avoided=0.0, net_benefit=0.0,
                stop_index=self.stop.index,
            )

        # ── 2. ETA hesabı ─────────────────────────────────────────
        eta = compute_eta(distance, bus.speed, self.approach_distance, self.comfort_braking)

        # ── 3. En erken boş slot ──────────────────────────────────
        if not slot_timeline:
            return SpeedRecommendation(
                vehicle_id=bus.id, speed_factor=1.0,
                source="none", reason="on_time",
                eta_to_stop=eta, ideal_arrival=0.0,
                queue_time_avoided=0.0, net_benefit=0.0,
                stop_index=self.stop.index,
            )

        slot_id, slot_free_time, _ = min(slot_timeline, key=lambda x: x[1])
        ideal_arrival = slot_free_time + SLOT_BUFFER_SECONDS

        # [FIX-5] Histerezis: sadece araç INTERVENTION_THRESHOLD'dan daha erken
        # geliyorsa müdahale başlat. Küçük farklarda salınımı önler.
        if eta >= ideal_arrival - INTERVENTION_THRESHOLD:
            return SpeedRecommendation(
                vehicle_id=bus.id, speed_factor=1.0,
                source="none", reason="on_time",
                eta_to_stop=eta, ideal_arrival=ideal_arrival,
                queue_time_avoided=0.0, net_benefit=0.0,
                stop_index=self.stop.index,
            )

        # ── 4. Kost-Fayda Analizi ─────────────────────────────────
        queue_time = ideal_arrival - eta  # müdahalesiz bekleme süresi

        # [FIX-4] Cascade: sadece slot DOLUYKEN gelebilecek araçları say
        # Uzaktaki araçlar slot boşaldıktan sonra gelecek → cascade etkileri yok
        relevant_following = [
            f for f in following_buses
            if compute_eta(
                self.zone_end - f.position_meters, f.speed,
                self.approach_distance, self.comfort_braking,
            ) < slot_free_time + CASCADE_WINDOW
        ]
        cascade_cost     = queue_time * len(relevant_following) * CASCADE_FACTOR
        downstream_cost  = downstream_pressure * DOWNSTREAM_PRESSURE_WEIGHT
        intervention_cost = queue_time

        net_benefit = cascade_cost + downstream_cost - intervention_cost

        if net_benefit > 0:
            speed_factor = self._compute_speed_factor(effective_distance, eta, ideal_arrival)
            reason = "cascade" if cascade_cost >= downstream_cost else "downstream"
            return SpeedRecommendation(
                vehicle_id=bus.id,
                speed_factor=speed_factor,
                source="smart_stop",
                reason=reason,
                eta_to_stop=eta,
                ideal_arrival=ideal_arrival,
                queue_time_avoided=queue_time,
                net_benefit=net_benefit,
                stop_index=self.stop.index,
            )

        # [FIX-3] Cascade yoksa bile: queue_time eşiği aştıysa müdahale et
        # Gerekçe: slot meşguliyet + yolcu konforu + upstream akış
        if queue_time >= MIN_QUEUE_TO_INTERVENE:
            speed_factor = self._compute_speed_factor(effective_distance, eta, ideal_arrival)
            return SpeedRecommendation(
                vehicle_id=bus.id,
                speed_factor=speed_factor,
                source="smart_stop",
                reason="overflow",
                eta_to_stop=eta,
                ideal_arrival=ideal_arrival,
                queue_time_avoided=queue_time,
                net_benefit=queue_time - MIN_QUEUE_TO_INTERVENE,
                stop_index=self.stop.index,
            )

        # Queue kabul etmek daha kârlı (küçük, kısa süreli bekleme)
        return SpeedRecommendation(
            vehicle_id=bus.id, speed_factor=1.0,
            source="none", reason="queue_cheaper",
            eta_to_stop=eta, ideal_arrival=ideal_arrival,
            queue_time_avoided=0.0, net_benefit=net_benefit,
            stop_index=self.stop.index,
        )

    def _compute_speed_factor(
        self,
        effective_distance: float,
        eta: float,
        ideal_arrival: float,
    ) -> float:
        """
        Aracın ideal_arrival zamanında durağa ulaşması için
        gereken hız çarpanını hesapla.

        Gecikme bütçesi zaten effective_distance'a yansıtılmış.
        İki fazlı model:
            Faz 1: Cruise (effective_distance - brake_dist boyunca)
            Faz 2: Brake  (brake_dist boyunca frenleme)
        """
        needed_time = max(ideal_arrival - TOTAL_DELAY_BUDGET, 1.0)

        brake_dist = min(self.approach_distance, effective_distance * 0.3)
        v_brake    = math.sqrt(2.0 * self.comfort_braking * brake_dist)
        brake_time = brake_dist / max(v_brake / 2.0, 0.5)

        cruise_time = needed_time - brake_time
        cruise_dist = effective_distance - brake_dist

        if cruise_time > 0 and cruise_dist > 0:
            needed_speed = cruise_dist / cruise_time
        else:
            needed_speed = effective_distance / max(needed_time, 1.0)

        if needed_speed < 3.0:
            return MIN_SPEED_FACTOR

        return max(MIN_SPEED_FACTOR, min(1.0, needed_speed / self.max_speed))

    # ──────────────────────────────────────────────────────────────
    # Durum Yayını
    # ──────────────────────────────────────────────────────────────

    def _build_state(
        self,
        zone_buses: List[SimVehicle],
        platform_buses: List[SimVehicle],
        slot_timeline: List[Tuple[int, float, Optional[int]]],
        sim_time: float,
    ) -> StopZoneState:
        """Interface'e yayınlanacak durum nesnesini oluştur."""
        # Faz sayımı
        phase_counts: Dict[str, int] = {}
        for v in zone_buses + platform_buses:
            phase_counts[v.phase] = phase_counts.get(v.phase, 0) + 1

        # Yaklaşan araçların ETA'ları
        incoming_etas = sorted(
            compute_eta(
                self.zone_end - v.position_meters,
                v.speed,
                self.approach_distance,
                self.comfort_braking,
            )
            for v in zone_buses
        )

        # Slot metrikleri
        occupied   = sum(1 for _, _, vid in slot_timeline if vid is not None)
        total_cap  = max(self.stop.slot_count, 1)
        approaching = len(zone_buses)

        congestion     = (occupied + approaching) / total_cap
        overflow_count = max(0, occupied + approaching - total_cap)

        # Komşu baskı metrikleri
        downstream_pressure = self.interface.get_downstream_pressure(self.stop.index)
        upstream_density    = self.interface.get_upstream_density(self.stop.index)

        return StopZoneState(
            stop_index=self.stop.index,
            stop_name=self.stop.name,
            vehicles_in_zone=approaching,
            phase_counts=phase_counts,
            occupied_slots=occupied,
            slot_capacity=total_cap,
            incoming_etas=incoming_etas,
            congestion_level=congestion,
            overflow_count=overflow_count,
            sim_time=sim_time,
            slot_timeline=list(slot_timeline),
            downstream_pressure=downstream_pressure,
            upstream_density=upstream_density,
        )


# ═══════════════════════════════════════════════════════════════════
# Yardımcı Fonksiyonlar
# ═══════════════════════════════════════════════════════════════════

def _update_slot_timeline(
    slots: List[Tuple[int, float, Optional[int]]],
    arrival_eta: float,
    vehicle_id: int,
    stop: LinearStop,
    is_rush_hour: bool,
) -> None:
    """
    Bir araca atanan en erken slotu güncelle.
    Sonraki araç bu slotu dolu (gelecekte boşalacak) olarak görecek.
    """
    if not slots:
        return
    min_idx = min(range(len(slots)), key=lambda i: slots[i][1])
    slot_id, _, _ = slots[min_idx]
    dwell        = estimate_dwell(stop, is_rush_hour)
    new_free     = arrival_eta + dwell + DEPARTURE_OVERHEAD
    slots[min_idx] = (slot_id, new_free, vehicle_id)


def build_smart_stops(
    stops: List[LinearStop],
    interface: StopInterface,
    approach_distance: float = 150.0,
    comfort_braking: float = 2.0,
    max_speed: float = 14.0,
) -> List[SmartStop]:
    """
    Bir rota için SmartStop listesi oluştur.

    Her durağın zone_start'ı bir önceki durağın pozisyonudur.
    İlk durak için zone_start = 0.0 kullanılır.
    """
    smart_stops: List[SmartStop] = []
    for i, stop in enumerate(stops):
        zone_start = stops[i - 1].meter_position if i > 0 else 0.0
        smart_stops.append(SmartStop(
            stop=stop,
            zone_start=zone_start,
            interface=interface,
            approach_distance=approach_distance,
            comfort_braking=comfort_braking,
            max_speed=max_speed,
        ))
    return smart_stops
