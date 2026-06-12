"""
Dock Projeksiyonu — Uzay-Zaman Kuyruk Modeli (PROTOTİP)
======================================================

Mevcut modelde ETA, durağın SABİT ön noktasına (zone_end) ölçülür. Peron
doluyken otobüs oraya ulaşamaz; kuyruğun arkaya kaçan ucunda durur. Üstelik
otobüs o uca varana dek öndeki araçlar kalkıp kuyruk ileri kayar → uç perona
doğru geri çekilir. Daha geride olan otobüsler bu yüzden perona daha YAKIN bir
noktaya kenetlenir.

Bu modül, yaklaşan bir otobüsün kenetlenme anını ve gerçek bekleme süresini,
iki hareketli cephenin (otobüs yörüngesi + geri çekilen kuyruk ucu) uzay-zaman
kesişimini adım adım ileri sararak bulur.

PROTOTİP VARSAYIMLARI (bilinçli sadeleştirmeler — belgelenmiştir):
  * Yaklaşan otobüs sabit `bus_speed` ile gelir (frenleme profili kuyruk
    etkisinden bağımsız olduğu için ihmal; ileride compute_eta ile değişir).
  * Perondaki her araç slotunu `release` (mutlak sn) anında boşaltır
    = dwell_remaining + kalkış overhead. (Açık-yol modeli: her araç önündeki
    boşaldıkça ilerler; mevcut slot_free_time mantığıyla aynı.)
  * Araçlar kalktıkça kuyruk öne doğru kompaktlaşır; kalan n araç ön slotları
    (0..n-1) doldurur, yeni gelen frontmost boş slota (index n) kenetlenir.
  * Otobüs yalnızca peron DOLUYKEN (n == capacity) bekler; erişilebilir boş
    slot varsa beklemeden kenetlenir (bunching = peron doygunluğu).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DockResult:
    dock_time: float        # kenetlenme anı (sn, şimdiden itibaren)
    dock_pos: float         # kenetlenme pozisyonu (metre, peron önü referans)
    queue_time: float       # uçta bloklanıp beklenen süre (sn)
    flowed_through: bool    # durmadan akıp geçti mi
    free_flow_time: float   # engelsiz olsa varış süresi (sn)


def project_dock(
    bus_pos: float,
    bus_speed: float,
    releases: list[float],
    *,
    stop_front: float,
    capacity: int,
    slot_spacing: float,
    dt: float = 0.1,
    max_t: float = 240.0,
) -> DockResult:
    """Tek yaklaşan otobüs için uzay-zaman dock projeksiyonu.

    Args:
        bus_pos:    otobüsün şu anki ön pozisyonu (m), bus_pos < stop_front
        bus_speed:  yaklaşma hızı (m/s)
        releases:   perondaki araçların slot boşaltma anları (sn); uzunluğu =
                    mevcut doluluk
        stop_front: peron ön (kenetlenme) çizgisi pozisyonu (m)
        capacity:   peron slot kapasitesi
        slot_spacing: ardışık araç ön pozisyonları arası mesafe (araç boyu + boşluk)
    """
    rel = sorted(releases)
    t = 0.0
    front = bus_pos
    queue_time = 0.0

    while t <= max_t:
        n_present = sum(1 for r in rel if r > t)

        if n_present < capacity:
            # frontmost boş slotun ön pozisyonu = mevcut araçların hemen arkası
            target = stop_front - n_present * slot_spacing
            slot_free = True
        else:
            # peron dolu: en arkadaki aracın gerisinde bekle
            target = stop_front - capacity * slot_spacing
            slot_free = False

        reach = front + bus_speed * dt
        new_front = target if reach >= target else reach
        at_target = abs(new_front - target) < 1e-6

        if at_target and slot_free:
            dock_time = t + dt
            dock_pos = target
            free_flow = max(0.0, (dock_pos - bus_pos) / bus_speed) if bus_speed > 0 else 0.0
            queue_time = max(0.0, dock_time - free_flow)
            return DockResult(
                dock_time=dock_time,
                dock_pos=dock_pos,
                queue_time=queue_time,
                flowed_through=queue_time < 0.5,
                free_flow_time=free_flow,
            )

        if at_target and not slot_free:
            queue_time += dt   # uçta bloklanmış, slot boşalmasını bekliyor

        front = new_front
        t += dt

    # ufuk içinde kenetlenemedi (aşırı tıkanma)
    free_flow = max(0.0, (stop_front - capacity * slot_spacing - bus_pos) / bus_speed) if bus_speed > 0 else 0.0
    return DockResult(
        dock_time=max_t,
        dock_pos=stop_front - capacity * slot_spacing,
        queue_time=max(0.0, max_t - free_flow),
        flowed_through=False,
        free_flow_time=free_flow,
    )


def static_front_queue_time(
    bus_pos: float,
    bus_speed: float,
    slot_free_time: float,
    *,
    stop_front: float,
    slot_buffer: float = 2.0,
) -> float:
    """MEVCUT model: ETA durağın SABİT ön noktasına ölçülür (bloklamayı yok sayar).

    queue_time = ideal_arrival - eta_front. >0 → müdahale; <=0 → "on_time".
    Kıyas için baz alınır.
    """
    if bus_speed <= 0:
        return 0.0
    eta_front = (stop_front - bus_pos) / bus_speed
    ideal_arrival = slot_free_time + slot_buffer
    return ideal_arrival - eta_front
