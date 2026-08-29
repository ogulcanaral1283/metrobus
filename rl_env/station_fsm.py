"""
Durak State Machine (FSM) — Paralel Peron Operasyonu
TypeScript station-fsm.ts'den Python'a taşındı.

TEMEL PRENSİP: Araçlar peron alanı içine girdiği anda
yolcu operasyonuna BAŞLAR. En öne gitmeyi BEKLEMEZler.

Paralel Operasyon:
  - Peron üzerinde birden fazla araç aynı anda kapı açık
  - Her araç kendi dwell_remaining'ini bağımsız sayar
  - Süre dolan araç, önü açılınca kalkış yapar
  - İleri kayma YOK — araç durduğu yerde kalır

State Machine:
  cruising    → approaching  (approachDistance veya platformZone)
  approaching → queued       (peron dolu — yer yok)
  approaching → docking      (peron alanında yer var)
  approaching → stopped      (platformZone içinde + hız ≈ 0)
  queued      → docking      (yer boşaldı)
  docking     → stopped      (pozisyona ulaştı → ANINDA yolcu op.)
  stopped     → doorsClosed  (dwell doldu)
  doorsClosed → blocked      (gap < SAFE_GAP)
  doorsClosed → departing    (gap >= SAFE_GAP veya önde araç yok)
  blocked     → departing    (önü açıldı)
  departing   → cruising     (hız > 3 m/s)
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

try:
    from .config import SimConfig, SimVehicle, VEHICLE_LENGTH
    from .route_data import LinearStop
    from .controller.station_arrival_scheduler import sample_dwell
except ImportError:
    from config import SimConfig, SimVehicle, VEHICLE_LENGTH
    from route_data import LinearStop
    from controller.station_arrival_scheduler import sample_dwell

# Istanbul metrobus araci uzunlugu (metre) — TS VEHICLE_TYPES ile senkron
BUS_LENGTH_METERS = 20.0

# Araçlar arası boşluk (metre) — peron içi park mesafesi (saha gözlemi ~0.5m)
VEHICLE_GAP_METERS = 0.5

# Güvenli kalkış mesafesi (metre)
SAFE_GAP = 0.5

# [DEFRAG] Kapı açmadan önce doğru giriş pozisyonuna (öndeki aracın arkası /
# peron önü) bu toleranstan daha uzaksa araç durduğu yerde OPERASYON BAŞLATMAZ;
# 'docking' fazıyla öne çeker. Aksi hâlde peron ortasında kapı açan araç ön
# slotları erişilmez kılıyor (fragmantasyon) → peron kısmen boşken kuyruk.
DOCK_SNAP_TOLERANCE = 3.0


# Varsayılan platform uzunluğu (metre) — veri eksik duraklarda kullanılır
DEFAULT_PLATFORM_LENGTH = 60.0


# ============================================
# Yardımcı Fonksiyonlar
# ============================================

def _effective_platform_length(stop: LinearStop) -> float:
    """Durağın efektif platform uzunluğu. Veri eksikse varsayılan kullan."""
    if stop.platform_length_meters > 0:
        return stop.platform_length_meters
    return DEFAULT_PLATFORM_LENGTH


def is_inside_platform_zone(
    vehicle_position: float,
    vehicle_length: float,
    stop: LinearStop,
) -> bool:
    """
    Araç peron alanı içinde mi?
    Peron alanı = [stop.meter_position - platform_length, stop.meter_position + 15]
    """
    platform_len = _effective_platform_length(stop)
    vehicle_rear = vehicle_position - vehicle_length
    platform_start = stop.meter_position - platform_len
    platform_end = stop.meter_position + vehicle_length  # araç uzunluğu kadar tolerans

    return vehicle_position <= platform_end and vehicle_rear >= platform_start - 2


def compute_rear_free_slots(
    stop: LinearStop,
    all_vehicles: list[SimVehicle],
) -> int:
    """
    Peronda ARKADAN ERİŞİLEBİLİR boş slot sayısını hesapla.

    Fiziksel kısıt: araçlar perona arkadan girer. Sadece en arkadaki
    aracın arkasındaki alan kullanılabilir. Öndeki boşluklar erişilemez.

    Örnek: 4 slotlu peron, 3. slotta 1 araç var
        Toplam boş slot: 3 (slot 1, 2, 4)
        Ama fiziksel erişilebilir: sadece 1 (slot 4 — aracın arkası)
        Slot 1 ve 2 erişilemez çünkü aracın önünde.
    """
    platform_len = _effective_platform_length(stop)
    platform_tail = stop.meter_position - platform_len  # peronun en arkası

    # Perondaki araçları bul
    platform_vehicles = get_vehicles_on_platform(stop.index, all_vehicles)

    if not platform_vehicles:
        # Peron tamamen boş → tüm slotlar erişilebilir
        return max(stop.slot_count, 1)

    # [CONVOY] Arka alanı yalnızca peronun İÇİNDEKİ araçlar fiziksel olarak
    # sınırlar. Henüz peron kuyruğuna ULAŞMAMIŞ docking araçları (arkadan
    # yaklaşanlar) alanı BLOKLAMAZ — ama birer slot REZERVE eder. Eski kod
    # dışarıdaki docking aracı 'en arkadaki' sayıp alanı negatife düşürüyordu:
    # içeri giren tek araç tüm girişleri serileştiriyor, takipçiler bol boş
    # slot varken 'queued' etiketiyle sürünüyordu.
    inside = [v for v in platform_vehicles
              if v.position_meters - VEHICLE_LENGTH >= platform_tail - 2.0]
    reserving = len(platform_vehicles) - len(inside)

    slot_size = VEHICLE_LENGTH + VEHICLE_GAP_METERS  # 20.5m
    if not inside:
        base = max(stop.slot_count, 1)
    else:
        # En arkadaki İÇERİDEKİ araç (desc sıralı, [-1] en arkadaki)
        rearmost_rear = inside[-1].position_meters - VEHICLE_LENGTH
        rear_space = rearmost_rear - platform_tail - SAFE_GAP
        base = max(0, int(rear_space / slot_size))

    return max(0, base - reserving)


def compute_max_buses_at_stop(stop: LinearStop) -> int:
    """
    Platform kapasitesi: platform_uzunluğu / (araç_uzunluğu + araçlar_arası_boşluk).

    Her otobüs BUS_LENGTH_METERS (20m) + VEHICLE_GAP_METERS (0.5m) = 20.5m yer kaplar.
    Platform uzunluğu bu değere bölünerek slot sayısı hesaplanır.

    Örnek: 118m platform → 118 / 20.5 = 5 slot
           91m platform  → 91 / 20.5  = 4 slot
           55m platform  → 55 / 20.5  = 2 slot
    """
    platform_len = _effective_platform_length(stop)
    slot_size = BUS_LENGTH_METERS + VEHICLE_GAP_METERS  # 20.5m
    return max(1, math.floor(platform_len / slot_size))


def get_vehicles_on_platform(
    stop_index: int,
    all_vehicles: list[SimVehicle],
) -> list[SimVehicle]:
    """
    Perondaki TÜM araçları al.
    stopped + doorsClosed + blocked + docking hepsi peronda.
    En öndeki → en arkadaki sırasıyla.
    """
    result = []
    for v in all_vehicles:
        if v.phase in ("stopped", "doorsClosed", "blocked", "docking"):
            if v.next_stop_index == stop_index:
                result.append(v)
    result.sort(key=lambda v: v.position_meters, reverse=True)
    return result


def compute_entry_position(
    stop: LinearStop,
    platform_vehicles: list[SimVehicle],
) -> float:
    """
    Perondaki en arkadaki aracın arkasına yeni araç için durma pozisyonu.
    Araçlar perona arkadan girer — öndeki boşluklara atlayamaz.
    """
    if not platform_vehicles:
        return stop.meter_position
    last_vehicle = platform_vehicles[-1]
    last_rear = last_vehicle.position_meters - VEHICLE_LENGTH
    return last_rear - SAFE_GAP


def fits_in_platform(
    stop_position: float,
    vehicle_length: float,
    stop: LinearStop,
) -> bool:
    """Aracın tamamı peron alanına sığıyor mu? (TS fitsInPlatform ile senkron)"""
    platform_len = _effective_platform_length(stop)
    vehicle_rear = stop_position - vehicle_length
    platform_start = stop.meter_position - platform_len
    front_ok = stop_position <= stop.meter_position + 2   # TS: +2m
    rear_ok = vehicle_rear >= platform_start - 1           # TS: -1m
    return front_ok and rear_ok


def is_blocked_by_gap(
    vehicle: SimVehicle,
    stop_index: int,
    all_vehicles: list[SimVehicle],
) -> bool:
    """
    Fiziksel gap kontrolü — önde engel var mı?
    Kalkış şartı: önde hiç araç yok VEYA öndeki aracın
    arka tamponu ile bizim ön tamponumuz arasında >= SAFE_GAP
    """
    for v in all_vehicles:
        if v.id == vehicle.id:
            continue
        if v.position_meters <= vehicle.position_meters:
            continue

        # Aynı duraktaki statik araçlar → kesin engel
        if v.phase in ("stopped", "doorsClosed", "blocked"):
            if v.next_stop_index == stop_index:
                return True

        # Departing araç — fiziksel gap kontrolü
        if v.phase == "departing":
            v_rear = v.position_meters - VEHICLE_LENGTH
            gap = v_rear - vehicle.position_meters
            if gap < SAFE_GAP:
                return True

    return False


def physical_position_limit(
    vehicle: SimVehicle,
    all_vehicles: list[SimVehicle],
) -> float:
    """[CLAMP] Aracın ilerleyebileceği mutlak fiziksel sınır.

    Fazdan ve hedef duraktan BAĞIMSIZ: öndeki en yakın aracın arkası − SAFE_GAP.
    queued/docking hareketleri hedeflerini yalnızca aynı-durak liderine göre
    kurar; araya farklı hedefli bir araç (ör. yavaş seyreden) girdiğinde bu
    kelepçe olmadan içinden geçebiliyorlardı.
    """
    limit = float("inf")
    for v in all_vehicles:
        if v.id == vehicle.id:
            continue
        if v.position_meters <= vehicle.position_meters:
            continue
        rear = v.position_meters - VEHICLE_LENGTH - SAFE_GAP
        if rear < limit:
            limit = rear
    # Zaten ihlal varsa (spawn artefaktı vb.) aracı geriye ışınlama
    return max(limit, vehicle.position_meters)


def find_nearest_leader_on_platform(
    vehicle: SimVehicle,
    all_vehicles: list[SimVehicle],
) -> SimVehicle | None:
    """Peron üzerinde bu aracın en yakın önündeki aracı bul."""
    nearest = None
    nearest_dist = float("inf")

    for v in all_vehicles:
        if v.id == vehicle.id:
            continue
        if v.next_stop_index != vehicle.next_stop_index:
            continue
        if v.position_meters <= vehicle.position_meters:
            continue

        if v.phase in ("stopped", "doorsClosed", "blocked", "docking"):
            dist = v.position_meters - vehicle.position_meters
            if dist < nearest_dist:
                nearest_dist = dist
                nearest = v

    return nearest


# ============================================
# Ana FSM Güncelleme
# ============================================

def update_station_fsm(
    vehicle: SimVehicle,
    dt: float,
    stops: list[LinearStop],
    config: SimConfig,
    is_rush_hour: bool,
    all_vehicles: list[SimVehicle] | None = None,
    use_fixed_dwell: bool = False,
    fixed_dwell_seconds: float = 15.0,
    rng: Optional[np.random.Generator] = None,
    current_hour: float = 8.0,
) -> None:
    """
    Durak state machine — PARALEL PERON OPERASYONU.

    Araç peron alanına girip durduğu anda yolcu operasyonu başlar.
    En öne gitmeyi beklemez. Birden fazla araç aynı anda kapı açık.
    """
    if rng is None:
        rng = np.random.default_rng()

    if vehicle.next_stop_index >= len(stops):
        return

    next_stop = stops[vehicle.next_stop_index]
    dist_to_stop = next_stop.meter_position - vehicle.position_meters
    vehicle_list = all_vehicles if all_vehicles is not None else []

    # ============================================
    # CRUISING
    # ============================================
    if vehicle.phase == "cruising":
        vehicle.is_queuing = False
        vehicle.queue_wait_time = 0.0

        v_len = VEHICLE_LENGTH
        in_zone = is_inside_platform_zone(vehicle.position_meters, v_len, next_stop)

        if in_zone:
            # Kontrolcü kararı: durak atlama
            if vehicle.skip_next_stop:
                vehicle.next_stop_index += 1
                vehicle.skip_next_stop = False
                return
            vehicle.phase = "approaching"
            return

        # Normal yaklaşma mesafesi
        if 0 < dist_to_stop < config.approach_distance:
            if vehicle.skip_next_stop:
                vehicle.next_stop_index += 1
                vehicle.skip_next_stop = False
                return
            vehicle.phase = "approaching"

        # Sadece peronu tamamen geçtiyse ve peron içinde değilse
        if dist_to_stop < -15 and not in_zone:
            vehicle.next_stop_index += 1

    # ============================================
    # APPROACHING — Alan Tabanlı Giriş
    # ============================================
    elif vehicle.phase == "approaching":
        v_len = VEHICLE_LENGTH
        in_zone = is_inside_platform_zone(vehicle.position_meters, v_len, next_stop)

        # === PERON ALANI İÇİNDE VE DURMUŞ ===
        if in_zone and vehicle.speed < 0.5:
            # Slot pozisyonunu doğru hesapla (üst üste binme önleme)
            platform_vehicles = get_vehicles_on_platform(vehicle.next_stop_index, vehicle_list)
            # Kendini listeden çıkar
            platform_vehicles = [pv for pv in platform_vehicles if pv.id != vehicle.id]

            # Peron arkadan dolu mu? Dashboard'daki 'girilebilir' ile AYNI ölçüt
            # (compute_rear_free_slots). Erişilebilir slot yoksa araç peron içine
            # park ETMEZ → KUYRUĞA geçer. Aksi halde fits_in_platform'un gevşek
            # toleransı yüzünden taşan araç 'stopped' sanılıp kuyruk gizleniyordu.
            if platform_vehicles and compute_rear_free_slots(next_stop, vehicle_list) <= 0:
                vehicle.phase = "queued"
                vehicle.is_queuing = True
                vehicle.speed = 0.0
                vehicle.acceleration = 0.0
                return

            entry_pos = compute_entry_position(next_stop, platform_vehicles)

            # [DEFRAG] Giriş pozisyonuna uzaksak kapı AÇMA — docking ile öne çek.
            # Şoför davranışı: boş peronun arkasında durup kapı açılmaz, öne
            # çekilir. docking dinamik hedefle lideri takip eder ve sıkı paketler.
            if entry_pos - vehicle.position_meters > DOCK_SNAP_TOLERANCE:
                vehicle.phase = "docking"
                vehicle.is_queuing = False
                vehicle.queue_wait_time = 0.0
                vehicle.slot_meter_position = entry_pos
                return

            # Mevcut pozisyon ile hesaplanan slot arasında makul olanı seç
            # Araç zaten peron içindeyse, geriye gitmesine gerek yok
            slot_pos = max(entry_pos, vehicle.position_meters) if platform_vehicles else vehicle.position_meters

            vehicle.phase = "stopped"
            vehicle.speed = 0.0
            vehicle.acceleration = 0.0
            vehicle.slot_meter_position = slot_pos
            vehicle.position_meters = slot_pos
            vehicle.is_queuing = False
            vehicle.queue_wait_time = 0.0
            vehicle.total_stops += 1

            dwell = _compute_realistic_dwell(
                next_stop, config, is_rush_hour, rng,
                use_fixed_dwell, fixed_dwell_seconds,
                current_hour,
            )
            dwell += vehicle.holding_extra
            vehicle.holding_extra = 0.0
            vehicle.dwell_remaining = dwell
            vehicle.last_dwell_time = dwell
            return

        # === PERON ALANI İÇİNDE AMA HAREKET EDİYOR ===
        if in_zone and vehicle.speed >= 0.5:
            leader = find_nearest_leader_on_platform(vehicle, vehicle_list)
            if leader:
                leader_rear = leader.position_meters - VEHICLE_LENGTH
                gap = leader_rear - vehicle.position_meters
                if gap < SAFE_GAP:
                    # Peron arkadan dolu mu? Erişilebilir slot yoksa KUYRUĞA geç
                    # (dashboard 'girilebilir' ile tutarlı). Taşan araç peron
                    # ucuna 'stopped' park edip kuyruğu gizlemesin.
                    if compute_rear_free_slots(next_stop, vehicle_list) <= 0:
                        vehicle.phase = "queued"
                        vehicle.is_queuing = True
                        vehicle.speed = 0.0
                        vehicle.acceleration = 0.0
                        return
                    # [DEFRAG] Hemen kapı AÇMA — docking'e geç. Docking dinamik
                    # hedefle lideri takip eder; lider durağansa bir tick içinde
                    # zaten 'stopped'a döner (blocked_stationary yolu), lider hâlâ
                    # ilerliyorsa (docking) peşinden gidip sıkı paketlenir. Eski
                    # davranış ilerleyen liderin arkasında kapı açıp aradaki
                    # boşluğu kalıcılaştırıyordu (fragmantasyon).
                    vehicle.phase = "docking"
                    vehicle.is_queuing = False
                    vehicle.queue_wait_time = 0.0
                    vehicle.slot_meter_position = leader_rear - SAFE_GAP
                    return
            # Frenlemeye devam
            return

        # === PERON ALANI DIŞINDA ===
        platform_vehicles = get_vehicles_on_platform(vehicle.next_stop_index, vehicle_list)
        entry_pos = compute_entry_position(next_stop, platform_vehicles)

        # === ERKEN KUYRUK KATILIMI ===
        # Peron arkadan DOLU ve önümüzde aynı durağa giden bir araç (kuyruğun
        # ucu) var; ona takip mesafesinde yetiştiysek → daha FRENLERKEN bile
        # 'queued' ol. Böylece dashboard'da peronu bekleyen TÜM araçlar sarı
        # görünür (yalnız öndeki 2'si değil). Uzaktaki seyir/yaklaşma hâlindeki
        # araçları yanlışlıkla işaretlememek için yalnız lidere yaklaşınca.
        if compute_rear_free_slots(next_stop, vehicle_list) <= 0:
            q_leader = None
            q_near = float("inf")
            for v in vehicle_list:
                if v.id == vehicle.id:
                    continue
                if v.next_stop_index != vehicle.next_stop_index:
                    continue
                if v.phase not in ("queued", "docking", "stopped",
                                   "doorsClosed", "blocked", "departing"):
                    continue
                if v.position_meters <= vehicle.position_meters:
                    continue
                d = v.position_meters - vehicle.position_meters
                if d < q_near:
                    q_near = d
                    q_leader = v
            if q_leader is not None:
                # Hıza bağlı takip eşiği: yüksek hızda daha erken yakala.
                follow_threshold = (VEHICLE_LENGTH + SAFE_GAP
                                    + max(15.0, vehicle.speed * 3.0))
                if q_near <= follow_threshold:
                    vehicle.phase = "queued"
                    vehicle.is_queuing = True
                    return

        if vehicle.speed < 3.0 and -5 < dist_to_stop < 8:
            if compute_rear_free_slots(next_stop, vehicle_list) > 0:
                vehicle.phase = "docking"
                vehicle.is_queuing = False
                vehicle.queue_wait_time = 0.0
                vehicle.slot_meter_position = entry_pos
            else:
                vehicle.phase = "queued"
                vehicle.is_queuing = True
                vehicle.speed = 0.0
                vehicle.acceleration = 0.0

        # Araç durmuş (hız ≈ 0) ama henüz queued/docking'a geçmemiş
        # Durağa 8m'den fazla uzaklıkta durmuş olabilir (fizik motoru frenledi)
        elif vehicle.speed < 0.3 and dist_to_stop > 0:
            if compute_rear_free_slots(next_stop, vehicle_list) > 0:
                # Slot boşalmış — direkt docking'e geç
                vehicle.phase = "docking"
                vehicle.is_queuing = False
                vehicle.queue_wait_time = 0.0
                vehicle.slot_meter_position = entry_pos
            else:
                vehicle.phase = "queued"
                vehicle.is_queuing = True
                vehicle.speed = 0.0
                vehicle.acceleration = 0.0

        # Durağı tamamen geçtiyse → bir sonraki durağa ilerle (sonsuz döngü önleme)
        overshoot_limit = max(5, next_stop.platform_length_meters * 0.5)
        if dist_to_stop <= -overshoot_limit and not in_zone:
            vehicle.phase = "cruising"
            vehicle.next_stop_index += 1

    # ============================================
    # QUEUED — Peron girişinde bekleme
    # ============================================
    elif vehicle.phase == "queued":
        # Kuyruk = peron DIŞINDA araç-takip (car-following) zinciri.
        # Kuyruktaki araç HİÇBİR operasyon YAPMAZ; sadece önündeki aracın
        # arkasında SAFE_GAP korur ve o hareket edince onu takip eder.
        # Yolcu operasyonu YALNIZCA peron içinde (docking→stopped) yapılır.
        vehicle.is_queuing = True
        vehicle.queue_wait_time += dt
        vehicle.acceleration = 0.0

        # 1) Lider: en yakın ÖNDEKİ araç (aynı durağa giden, yer kaplayan/giden faz).
        #    'departing' DAHİL → öndeki kalkmaya başlayınca kuyruk onun ardından akar.
        leader = None
        nearest = float("inf")
        for v in vehicle_list:
            if v.id == vehicle.id:
                continue
            if v.next_stop_index != vehicle.next_stop_index:
                continue
            if v.phase not in ("queued", "docking", "stopped",
                               "doorsClosed", "blocked", "departing"):
                continue
            if v.position_meters <= vehicle.position_meters:
                continue
            d = v.position_meters - vehicle.position_meters
            if d < nearest:
                nearest = d
                leader = v

        # 2) Kuyruğun en önünde miyiz? (önümüzde başka 'queued' araç yoksa)
        at_front = (leader is None) or (leader.phase != "queued")

        # 3) En öndeysek VE perona erişilebilir GERÇEK boş slot açıldıysa → perona gir.
        if at_front and compute_rear_free_slots(next_stop, vehicle_list) > 0:
            platform_vehicles = get_vehicles_on_platform(
                vehicle.next_stop_index, vehicle_list)
            platform_vehicles = [pv for pv in platform_vehicles
                                 if pv.id != vehicle.id]
            vehicle.phase = "docking"
            vehicle.is_queuing = False
            vehicle.queue_wait_time = 0.0
            vehicle.slot_meter_position = compute_entry_position(
                next_stop, platform_vehicles)
            return

        # 4) Aksi halde lideri TAKİP ET. Hedef = lider arkası - SAFE_GAP.
        if leader is not None:
            target = leader.position_meters - VEHICLE_LENGTH - SAFE_GAP
        else:
            # Lider yok ama slot da yok → olduğun yerde bekle (ilerleme yok).
            target = vehicle.position_meters

        # [CLAMP] Hedef, öndeki EN YAKIN aracın (fazı/durağı ne olursa olsun)
        # arkasını asla geçemez — aynı-durak liderine kilitli hedef, araya
        # giren yabancı araçların içinden geçirmesin.
        target = min(target, physical_position_limit(vehicle, vehicle_list))

        # ÇARPIŞMA KESİN ÖNLEME: pozisyon hedefi (lider arkası - SAFE_GAP) ASLA geçemez.
        if vehicle.position_meters >= target:
            vehicle.position_meters = min(vehicle.position_meters, target)
            vehicle.speed = 0.0
        else:
            QUEUE_MAX_SPEED = 6.0   # kuyrukta ilerleme hız tavanı (~22 km/h)
            dist = target - vehicle.position_meters
            step = min(dist, QUEUE_MAX_SPEED * dt)
            vehicle.position_meters += step
            vehicle.speed = step / dt if dt > 0 else 0.0

    # ============================================
    # DOCKING — Slot'a yavaş ilerleme (2 m/s)
    # ============================================
    elif vehicle.phase == "docking":
        # DİNAMİK HEDEF: araç sabit bir slota kilitlenmez — her tick öndeki en yakın
        # peron-içi aracı (lider) takip eder, arkasında SAFE_GAP korur. Lider perona
        # doğru ilerledikçe takipçi de ilerler (peşinden gider). Önünde lider yoksa
        # hedef peronun en başıdır. Böylece araçlar peronda SIKI paketlenir (0.5m),
        # lider öne gidince arada koca boşluk kalmaz.
        leader = find_nearest_leader_on_platform(vehicle, vehicle_list)
        if leader is not None:
            target = (leader.position_meters - VEHICLE_LENGTH) - SAFE_GAP
        else:
            target = next_stop.meter_position   # peron önü (en baş)
        # Hedef geriye gitmesin (lider gelip dayanırsa olduğun yerde kal)
        target = max(target, vehicle.position_meters - 0.01)
        vehicle.slot_meter_position = target
        dist_to_slot = target - vehicle.position_meters

        # Çarpışma kontrolü:
        #  - blocked_move: önde SAFE_GAP içinde herhangi bir araç (departing DAHİL)
        #    → ilerleme. Departing araca çarpmamak için bekle.
        #  - blocked_stationary: önde SAFE_GAP içinde DURAĞAN araç → operasyona başla
        #    (gerçek metrobüs: ilerleyemiyorsan olduğun yerde kapıları aç).
        blocked_move = False
        blocked_stationary = False
        for v in vehicle_list:
            if v.id == vehicle.id:
                continue
            if v.position_meters <= vehicle.position_meters:
                continue
            is_same_stop = (v.next_stop_index == vehicle.next_stop_index
                           and v.phase in ("stopped", "doorsClosed", "blocked", "docking"))
            is_departing_ahead = (v.phase == "departing")
            if is_same_stop or is_departing_ahead:
                v_rear = v.position_meters - VEHICLE_LENGTH
                gap = v_rear - vehicle.position_meters
                if gap < SAFE_GAP:
                    blocked_move = True
                    if v.phase in ("stopped", "doorsClosed", "blocked"):
                        blocked_stationary = True

        in_platform = is_inside_platform_zone(vehicle.position_meters, VEHICLE_LENGTH, next_stop)

        # Operasyona başlama: hedefe oturdu VE lider durağan (önde hareket eden yok)
        # → bu son sıkı pozisyon. Lider hâlâ ilerliyorsa (docking) operasyona BAŞLAMA,
        # takip etmeye devam et. Ya da peron içinde durağan bir araca dayanıp kaldıysan.
        leader_stationary = (leader is None
                             or leader.phase in ("stopped", "doorsClosed", "blocked"))
        should_stop = (
            (dist_to_slot <= 0.05 and leader_stationary)
            or (blocked_stationary and in_platform)
        )

        if should_stop:
            vehicle.phase = "stopped"
            vehicle.speed = 0.0
            vehicle.acceleration = 0.0
            # Slota çok yakınsa kalan birkaç cm'i snap et (görünmez), değilse olduğu yerde kal
            if 0 <= dist_to_slot <= 0.5:
                vehicle.position_meters = vehicle.slot_meter_position
            else:
                vehicle.slot_meter_position = vehicle.position_meters
            vehicle.total_stops += 1

            dwell = _compute_realistic_dwell(
                next_stop, config, is_rush_hour, rng,
                use_fixed_dwell, fixed_dwell_seconds,
                current_hour,
            )
            dwell += vehicle.holding_extra
            vehicle.holding_extra = 0.0
            vehicle.dwell_remaining = dwell
            vehicle.last_dwell_time = dwell
        else:
            if blocked_move:
                vehicle.speed = 0.0
                vehicle.acceleration = 0.0
                return

            # Peron içi doğal hız profili: ivmelen → frenle → dur
            PLATFORM_ACCEL = config.max_acceleration * 0.4   # ~0.5 m/s²
            PLATFORM_BRAKE = config.comfort_braking * 0.6    # ~2.1 m/s² (fiili fren tavanı)
            # Hedef yavaşlama eğrisi gerçek tavandan daha yumuşak tutulur: araç,
            # eğriyi her zaman tavan içinde takip edebildiği için slota sıcak
            # girmez, hız tabana (~0) kadar pürüzsüz iner.
            PLATFORM_PROFILE_BRAKE = PLATFORM_BRAKE * 0.5    # ~1.05 m/s² hedef eğri
            PLATFORM_MAX_SPEED = 7.0                         # ~25 km/h peron içi limit

            v_old = vehicle.speed

            # Frenleme mesafesi (yumuşak hedef eğriye göre): v² / (2 * a_profile)
            braking_dist = (v_old * v_old) / (2.0 * PLATFORM_PROFILE_BRAKE) if PLATFORM_PROFILE_BRAKE > 0 else 0.0

            if dist_to_slot <= braking_dist + 1.0:
                # Frenleme bölgesi — slota yaklaşıyoruz, yavaşla.
                # Hedef hız profili v = sqrt(2*a_profile*d): slota tam değdiğinde v→0.
                # Profil deceli tavanın altında olduğundan accel nadiren tavana dayanır;
                # araç eğriyi 5 cm eşiğine kadar pürüzsüz takip eder, kilitlenmez.
                desired_v = math.sqrt(max(0.0, 2.0 * PLATFORM_PROFILE_BRAKE * max(0.0, dist_to_slot)))
                dock_accel = (desired_v - v_old) / dt if dt > 0 else 0.0
                dock_accel = max(-PLATFORM_BRAKE, dock_accel)
            else:
                # İvmelenme bölgesi — henüz uzaktayız, hızlan
                if v_old < PLATFORM_MAX_SPEED:
                    dock_accel = PLATFORM_ACCEL
                else:
                    dock_accel = 0.0

            ds = v_old * dt + 0.5 * dock_accel * dt * dt
            new_pos = vehicle.position_meters + max(0.0, ds)
            # [CLAMP] Öndeki en yakın aracın arkası (fazdan bağımsız) aşılamaz.
            # blocked_move yalnızca aynı-durak/departing araçları görüyor; kalkıp
            # 'cruising'e dönen ama hâlâ hemen önde olan araç aksi hâlde deliniyordu.
            limit = physical_position_limit(vehicle, vehicle_list)
            if new_pos >= limit:
                new_pos = limit
                vehicle.speed = 0.0
                vehicle.acceleration = 0.0
            else:
                vehicle.speed = max(0.0, min(PLATFORM_MAX_SPEED, v_old + dock_accel * dt))
                vehicle.acceleration = dock_accel
            vehicle.position_meters = new_pos

    # ============================================
    # STOPPED — Kapılar açık, yolcu operasyonu (PARALEL)
    # ============================================
    elif vehicle.phase == "stopped":
        vehicle.position_meters = vehicle.slot_meter_position
        vehicle.speed = 0.0

        vehicle.dwell_remaining -= dt

        if vehicle.dwell_remaining <= 0:
            vehicle.dwell_remaining = 0.0
            vehicle.phase = "doorsClosed"
            vehicle.dwell_remaining = 1.0  # Kapı kapanma 1s (gerçek metrobüs ~1s)

    # ============================================
    # DOORS CLOSED — Kapılar kapanıyor (2s)
    # ============================================
    elif vehicle.phase == "doorsClosed":
        vehicle.position_meters = vehicle.slot_meter_position
        vehicle.speed = 0.0

        vehicle.dwell_remaining -= dt

        if vehicle.dwell_remaining <= 0:
            vehicle.dwell_remaining = 0.0
            if is_blocked_by_gap(vehicle, vehicle.next_stop_index, vehicle_list):
                vehicle.phase = "blocked"
            else:
                vehicle.phase = "departing"
                vehicle.next_stop_index += 1

    # ============================================
    # BLOCKED — Önde engel var
    # ============================================
    elif vehicle.phase == "blocked":
        vehicle.position_meters = vehicle.slot_meter_position
        vehicle.speed = 0.0

        # Deadlock önleme: 5 saniye beklediyse VE önü açıksa kalk
        vehicle.queue_wait_time += dt
        if vehicle.queue_wait_time > 5.0 and not is_blocked_by_gap(vehicle, vehicle.next_stop_index, vehicle_list):
            vehicle.phase = "departing"
            vehicle.queue_wait_time = 0.0
            vehicle.next_stop_index += 1
        elif vehicle.queue_wait_time > 15.0:
            # Gerçek deadlock: 15s sonra zorla kalk (son çare)
            vehicle.phase = "departing"
            vehicle.queue_wait_time = 0.0
            vehicle.next_stop_index += 1
        elif not is_blocked_by_gap(vehicle, vehicle.next_stop_index, vehicle_list):
            vehicle.phase = "departing"
            vehicle.queue_wait_time = 0.0
            vehicle.next_stop_index += 1

    # ============================================
    # DEPARTING — Kalkış ivmelenmesi
    # ============================================
    elif vehicle.phase == "departing":
        vehicle.acceleration = config.max_acceleration  # TS ile senkron: kalkışta ivme ata
        if vehicle.speed > 3.0:
            vehicle.phase = "cruising"


# ============================================
# Dwell Time Hesaplama
# ============================================

def _compute_realistic_dwell(
    stop: LinearStop,
    config: SimConfig,
    is_rush_hour: bool,
    rng: np.random.Generator,
    use_fixed_dwell: bool = False,
    fixed_dwell_seconds: float = 15.0,
    current_hour: float = 8.0,
) -> float:
    """
    Gerçek dwell süresi — sahada ölçülen sağa çarpık dağılımdan örneklenir.

    sample_dwell (station_arrival_scheduler) kullanılır: [15,30] sn, ort ~18-20,
    çoğu 15-20 sn, durağa göre değil ziyaret başına rastgele. Kontrolcünün
    scheduler tahmini (estimate_dwell) bu dağılımın BEKLENEN değerini kullanır.
    """
    if use_fixed_dwell:
        return fixed_dwell_seconds

    return sample_dwell(rng, is_rush_hour)
