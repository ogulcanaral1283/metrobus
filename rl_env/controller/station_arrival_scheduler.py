"""
Aşama 1 — Station Arrival Scheduler (Durak Varış Zamanlaması)
================================================================

Her durağı bir havaalanı pisti gibi yönetir:
  - Slot zaman çizelgesi projeksiyonu (hangi slot ne zaman boşalır)
  - Yaklaşan araçların ETA hesabı
  - Greedy slot atama (her araca ideal varış zamanı)
  - Erken gelen araç → yavaşlatılır (800m+ önceden)

Temel Prensip:
    Düz yolda araçların birbirine yakın gitmesi SORUN DEĞİL.
    Sorun: durağa slot kapasitesinden fazla araç gelmesi.
    Çözüm: araçları duraklara TAM ZAMANINDA getir.

Algoritma:
    1. Perondaki araçların kalan dwell → slot_boşalma_zamanları
    2. Yaklaşan araçların ETA → varış_sırası
    3. Greedy matching: her araca en erken boş slotu ata
    4. ETA < slot_boşalma → araca speed_factor ver (yavaşlat)
    5. ETA >= slot_boşalma → müdahale yok (doğal hız yeterli)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

try:
    from ..config import SimVehicle, SimConfig, VEHICLE_LENGTH
    from ..route_data import LinearStop
    from ..station_fsm import compute_rear_free_slots
except ImportError:
    from config import SimVehicle, SimConfig, VEHICLE_LENGTH
    from route_data import LinearStop
    from station_fsm import compute_rear_free_slots


# ═══════════════════════════════════════════
# Sabitler
# ═══════════════════════════════════════════

# Minimum müdahale mesafesi (m) — bunun altında speed_factor vermek anlamsız
MIN_INTERVENTION_DISTANCE = 30.0

# Maksimum müdahale mesafesi (m) — bunun ötesinde ETA güvenilmez
MAX_INTERVENTION_DISTANCE = 3000.0

# Slot boşalma sonrası güvenlik tamponu (s) — tam boşalma anında değil, biraz sonra var
SLOT_BUFFER_SECONDS = 2.0

# Kapı kapanma + kalkış süresi (s) — araç dwell bittikten sonra peronu ne zaman terk eder
DEPARTURE_OVERHEAD = 4.0  # doorsClosed (2s) + departing ivme (~2s)

# Minimum speed_factor — bunun altına düşmek pratik değil
MIN_SPEED_FACTOR = 0.3

# Minimum hız (m/s) — çok yavaş seyir anlamsız
MIN_CRUISE_SPEED = 3.0

# Dwell süresi tahmin sabitleri
DWELL_BASE_NORMAL = 20.0
DWELL_BASE_RUSH = 26.0
DWELL_DOOR_TIME = 1.0


# ═══════════════════════════════════════════
# Veri Yapıları
# ═══════════════════════════════════════════

@dataclass
class SlotTimeline:
    """Bir durağın slot zaman çizelgesi."""
    stop_index: int
    stop_name: str
    slot_count: int
    # Her slot için: (slot_id, boşalma_zamanı_sn, mevcut_araç_id veya None)
    slots: List[Tuple[int, float, Optional[int]]]

    @property
    def earliest_free_time(self) -> float:
        """En erken boşalacak slotun zamanı."""
        if not self.slots:
            return 0.0
        return min(t for _, t, _ in self.slots)

    def next_free_slot(self, after_time: float = 0.0) -> Tuple[int, float]:
        """
        Belirli bir zamandan sonra ilk boşalan slotu döndür.
        Returns: (slot_id, boşalma_zamanı)
        """
        # Zaten boş slotlar (boşalma zamanı <= after_time)
        free_slots = [(sid, t) for sid, t, _ in self.slots if t <= after_time]
        if free_slots:
            return min(free_slots, key=lambda x: x[1])

        # Gelecekte boşalacak slotlar
        future_slots = [(sid, t) for sid, t, _ in self.slots if t > after_time]
        if future_slots:
            return min(future_slots, key=lambda x: x[1])

        # Hiç slot yok (olmaması lazım ama güvenlik)
        return (0, 0.0)

    def assign_slot(self, slot_id: int, new_free_time: float, vehicle_id: int) -> None:
        """Slotu bir araca ata ve yeni boşalma zamanını güncelle."""
        for i, (sid, t, vid) in enumerate(self.slots):
            if sid == slot_id:
                self.slots[i] = (sid, new_free_time, vehicle_id)
                return


@dataclass
class ArrivalPlan:
    """Tek araç için durak varış planı."""
    vehicle_id: int
    stop_index: int
    stop_name: str
    current_eta: float          # mevcut hızla tahmini varış (s)
    ideal_arrival: float        # ideal varış zamanı (s) — slot boşaldığında
    assigned_slot: int          # atanan slot ID
    needs_intervention: bool    # hız müdahalesi gerekiyor mu
    speed_factor: float         # önerilen hız çarpanı [0.3, 1.0]
    distance_to_stop: float     # durağa mesafe (m)
    overflow_risk: float        # taşma riski (yaklaşan/kapasite)
    estimated_wait: float       # müdahalesiz bekleme süresi tahmini (s)


@dataclass
class StationSchedule:
    """Tüm filo için durak bazlı zamanlama planı."""
    plans: List[ArrivalPlan]
    timelines: dict  # {stop_index: SlotTimeline}
    total_overflow_risk: float
    total_estimated_wait_saved: float  # müdahaleyle kurtarılan bekleme süresi


# ═══════════════════════════════════════════
# ETA Hesaplama
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
        # Durmuş veya çok yavaş — ortalama hızla tahmin
        return distance / MIN_CRUISE_SPEED

    if distance <= approach_distance:
        # Zaten frenleme bölgesinde — kinematik: t = v / b (v'den 0'a frenle)
        # Ortalama hız = v/2, süre = distance / (v/2) = 2*distance/v
        v_entry = min(current_speed, math.sqrt(2.0 * comfort_braking * distance))
        avg_speed = max(v_entry / 2.0, 0.5)
        return distance / avg_speed

    cruise_dist = distance - approach_distance
    t_cruise = cruise_dist / current_speed
    # Frenleme fazı: approach_distance boyunca yavaşla
    v_entry = min(current_speed, math.sqrt(2.0 * comfort_braking * approach_distance))
    t_brake = approach_distance / max(v_entry / 2.0, 0.5)
    return t_cruise + t_brake


def estimate_dwell(stop: LinearStop, is_rush_hour: bool = False) -> float:
    """Deterministik dwell süresi tahmini."""
    base = DWELL_BASE_RUSH if is_rush_hour else DWELL_BASE_NORMAL
    return DWELL_DOOR_TIME + base


# ═══════════════════════════════════════════
# Station Arrival Scheduler
# ═══════════════════════════════════════════

class StationArrivalScheduler:
    """
    Durak varış zamanlaması optimizer.

    Her durak için slot zaman çizelgesi oluşturur ve yaklaşan
    araçlara ideal varış zamanı atayarak kuyruk oluşumunu önler.
    """

    def __init__(
        self,
        approach_distance: float = 150.0,
        comfort_braking: float = 2.0,
        max_speed: float = 14.0,
    ):
        self.approach_distance = approach_distance
        self.comfort_braking = comfort_braking
        self.max_speed = max_speed

    def schedule(
        self,
        vehicles: List[SimVehicle],
        stops: List[LinearStop],
        is_rush_hour: bool = False,
    ) -> StationSchedule:
        """
        Tüm filo için durak varış planı oluştur.

        Akış:
            1. Her durak için slot zaman çizelgesi oluştur
            2. Her durağa yaklaşan araçları tespit et
            3. Greedy slot atama — ideal varış zamanı belirle
            4. Erken gelenlere speed_factor hesapla

        Returns:
            StationSchedule — her araç için ArrivalPlan + durak timelines
        """
        all_plans: List[ArrivalPlan] = []
        timelines: dict[int, SlotTimeline] = {}
        total_wait_saved = 0.0

        for stop in stops:
            # 1. Bu durağın slot zaman çizelgesini oluştur
            timeline = self._build_slot_timeline(stop, vehicles, is_rush_hour)
            timelines[stop.index] = timeline

            # 2. Bu durağa yaklaşan araçları bul ve ETA hesapla
            approaching = self._get_approaching_vehicles(stop, vehicles)

            if not approaching:
                continue

            # 3. ETA'ya göre sırala (en erken varacak önce)
            approaching.sort(key=lambda x: x[1])  # (vehicle, eta, distance)

            # Taşma riski
            overflow_risk = len(approaching) / max(timeline.slot_count, 1)

            # 4. Greedy slot atama
            for veh, eta, dist in approaching:
                plan = self._assign_to_slot(
                    veh, stop, timeline, eta, dist,
                    overflow_risk, is_rush_hour,
                )
                all_plans.append(plan)
                total_wait_saved += plan.estimated_wait

        # Toplam taşma riski
        total_risk = 0.0
        if timelines:
            risks = [
                len(self._get_approaching_vehicles(stops[si], vehicles)) / max(tl.slot_count, 1)
                for si, tl in timelines.items()
                if si < len(stops)
            ]
            total_risk = max(risks) if risks else 0.0

        return StationSchedule(
            plans=all_plans,
            timelines=timelines,
            total_overflow_risk=total_risk,
            total_estimated_wait_saved=total_wait_saved,
        )

    def _build_slot_timeline(
        self,
        stop: LinearStop,
        vehicles: List[SimVehicle],
        is_rush_hour: bool,
    ) -> SlotTimeline:
        """
        Durağın slot zaman çizelgesini oluştur.

        KRİTİK: Araçlar perona ARKADAN girer. Sadece en arkadaki
        aracın arkasındaki slotlar fiziksel olarak erişilebilir.

        Örnek: 4 slotlu peron, 3. slotta 1 araç:
            Toplam kapasite: 4
            Perondaki araç: 1
            Toplam boş: 3 (slot 1, 2, 4)
            Ama ERİŞİLEBİLİR boş: 1 (sadece slot 4 — aracın arkası)
            Slot 1 ve 2 boş ama öndekine ulaşılamaz.

        Bu fonksiyon SADECE arkadan erişilebilir slotları timeline'a
        ekler. Böylece hız filtreleme doğru hesaplanır.
        """
        total_capacity = max(stop.slot_count, 1)

        # Perondaki araçları bul
        on_platform: List[SimVehicle] = []
        for v in vehicles:
            if v.next_stop_index == stop.index and v.phase in (
                "stopped", "doorsClosed", "blocked", "docking"
            ):
                on_platform.append(v)

        # Pozisyona göre sırala (en öndeki en yüksek metre)
        on_platform.sort(key=lambda v: v.position_meters, reverse=True)

        # Arkadan erişilebilir boş slot sayısı
        rear_free = compute_rear_free_slots(stop, vehicles)

        # Dolu slotlar (perondaki araçlar)
        slots: List[Tuple[int, float, Optional[int]]] = []

        for slot_id, veh in enumerate(on_platform):
            # Bu araç ne zaman peronu terk eder?
            if veh.phase == "stopped":
                free_time = veh.dwell_remaining + DEPARTURE_OVERHEAD
            elif veh.phase == "doorsClosed":
                free_time = veh.dwell_remaining + 2.0  # kalkış ivmesi
            elif veh.phase == "blocked":
                free_time = 3.0  # tahmini — önü açılınca gider
            elif veh.phase == "docking":
                dwell = estimate_dwell(stop, is_rush_hour)
                free_time = 2.0 + dwell + DEPARTURE_OVERHEAD
            else:
                free_time = 0.0
            slots.append((slot_id, free_time, veh.id))

        # Arkadan erişilebilir boş slotları ekle
        # (Öndeki boş slotlar eklenmez — fiziksel olarak erişilemez)
        for i in range(rear_free):
            slot_id = len(on_platform) + i
            slots.append((slot_id, 0.0, None))

        # Efektif kapasite = perondaki araçlar + arkadan erişilebilir slotlar
        effective_capacity = len(on_platform) + rear_free

        return SlotTimeline(
            stop_index=stop.index,
            stop_name=stop.name,
            slot_count=effective_capacity,
            slots=slots,
        )

    def _get_approaching_vehicles(
        self,
        stop: LinearStop,
        vehicles: List[SimVehicle],
    ) -> List[Tuple[SimVehicle, float, float]]:
        """
        Bu durağa yaklaşan araçları bul.

        Returns: [(vehicle, eta, distance), ...] — sadece cruising/approaching fazındakiler
        """
        result = []

        for v in vehicles:
            # Sadece bu durağa gidecek ve hareket halinde olan araçlar
            if v.next_stop_index != stop.index:
                continue
            if v.phase not in ("cruising", "approaching", "docking"):
                continue

            dist = stop.meter_position - v.position_meters
            if dist <= 0 or dist > MAX_INTERVENTION_DISTANCE:
                continue

            eta = compute_eta(dist, v.speed, self.approach_distance, self.comfort_braking)
            result.append((v, eta, dist))

        return result

    def _assign_to_slot(
        self,
        vehicle: SimVehicle,
        stop: LinearStop,
        timeline: SlotTimeline,
        eta: float,
        distance: float,
        overflow_risk: float,
        is_rush_hour: bool,
    ) -> ArrivalPlan:
        """
        Araca slot ata ve ideal varış zamanı hesapla.

        Greedy: en erken boşalan slotu al.
        Eğer ETA < slot boşalma → yavaşlat (speed_factor).
        Eğer ETA >= slot boşalma → müdahale yok.
        """
        # En erken boş slotu bul
        slot_id, slot_free_time = timeline.next_free_slot(after_time=0.0)

        # İdeal varış zamanı: slot boşaldıktan SLOT_BUFFER sonra
        ideal_arrival = slot_free_time + SLOT_BUFFER_SECONDS

        # Müdahale gerekiyor mu?
        needs_intervention = False
        speed_factor = 1.0
        estimated_wait = 0.0

        if distance > MIN_INTERVENTION_DISTANCE:
            if eta < ideal_arrival:
                # Araç erken varacak → slot henüz boş olmayacak → yavaşlat
                needs_intervention = True
                estimated_wait = ideal_arrival - eta

                needed_time = ideal_arrival
                if needed_time > 0:
                    brake_dist = min(self.approach_distance, distance * 0.3)
                    v_brake = math.sqrt(2.0 * self.comfort_braking * brake_dist)
                    brake_time = brake_dist / max(v_brake / 2.0, 0.5)

                    cruise_time = needed_time - brake_time
                    cruise_dist = distance - brake_dist

                    if cruise_time > 0 and cruise_dist > 0:
                        needed_speed = cruise_dist / cruise_time
                    else:
                        needed_speed = distance / needed_time

                    if needed_speed < MIN_CRUISE_SPEED:
                        speed_factor = MIN_SPEED_FACTOR
                    else:
                        speed_factor = max(
                            MIN_SPEED_FACTOR,
                            min(1.0, needed_speed / self.max_speed),
                        )

            elif eta > ideal_arrival * 1.1:
                # Araç geç kalacak → slot boş bekliyor → hızlandır
                needs_intervention = True
                delay = eta - ideal_arrival

                needed_time = ideal_arrival
                if needed_time > 0:
                    needed_speed = distance / needed_time
                    # Üst sınır: max hızın %20 fazlası
                    speed_factor = min(1.2, needed_speed / self.max_speed)
                    speed_factor = max(1.0, speed_factor)

        # Slotu bu araca ata
        new_dwell = estimate_dwell(stop, is_rush_hour)
        new_free_time = ideal_arrival + new_dwell + DEPARTURE_OVERHEAD
        timeline.assign_slot(slot_id, new_free_time, vehicle.id)

        return ArrivalPlan(
            vehicle_id=vehicle.id,
            stop_index=stop.index,
            stop_name=stop.name,
            current_eta=eta,
            ideal_arrival=ideal_arrival,
            assigned_slot=slot_id,
            needs_intervention=needs_intervention,
            speed_factor=speed_factor,
            distance_to_stop=distance,
            overflow_risk=overflow_risk,
            estimated_wait=estimated_wait,
        )

    def get_vehicle_plan(
        self,
        vehicle_id: int,
        schedule: StationSchedule,
    ) -> Optional[ArrivalPlan]:
        """Belirli bir aracın planını al."""
        for plan in schedule.plans:
            if plan.vehicle_id == vehicle_id:
                return plan
        return None

    def get_plans_for_stop(
        self,
        stop_index: int,
        schedule: StationSchedule,
    ) -> List[ArrivalPlan]:
        """Belirli bir durağın tüm planlarını al."""
        return [p for p in schedule.plans if p.stop_index == stop_index]
