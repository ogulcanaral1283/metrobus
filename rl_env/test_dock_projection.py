"""
Dock Projeksiyonu doğrulaması.
Çalıştır:  cd rl_env && python test_dock_projection.py
"""

import sys
sys.path.insert(0, ".")
sys.path.insert(0, "controller")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import random

from controller.dock_projection import (
    project_dock,
    static_front_queue_time,
    DockResult,
)

OVERHEAD = 4.0   # dwell bitince kapı + kalkış (station_arrival_scheduler ile aynı)


# ════════════════════════════════════════════════════════════════
# Birim senaryolar — kullanıcının iki örneği
# Geometri: peron önü = 0, araç+boşluk = 25.5 m (25 araç + 0.5 boşluk),
# kapasite = 2 (DOLU). Yaklaşan otobüs full-bekleme noktasına (-51) ~10 sn'de
# varacak şekilde konumlanmış (hız 8.5 m/s).
# ════════════════════════════════════════════════════════════════

STOP_FRONT = 0.0
SPACING = 25.5
CAP = 2
SPEED = 8.5
BUS_POS = -51.0 - SPEED * 10.0   # -136 → wait noktasına ~10 sn


def _print(tag, r: DockResult, static_qt: float):
    print(f"  [{tag}]")
    print(f"     dock_time     = {r.dock_time:6.1f} sn")
    print(f"     dock_pos      = {r.dock_pos:7.1f} m   (peron önü=0)")
    print(f"     free_flow     = {r.free_flow_time:6.1f} sn")
    print(f"     queue_time    = {r.queue_time:6.1f} sn   (projeksiyon)")
    print(f"     flowed_through= {r.flowed_through}")
    print(f"     static qt     = {static_qt:6.1f} sn   (mevcut model)")


def scenario_fast_drain():
    """Öndeki araç 5 sn sonra kalkar → otobüs varmadan slot açılır → AKAR."""
    print("\nSENARYO A — kuyruk HIZLI boşalıyor (dwell 5 sn)")
    releases = [5.0 + OVERHEAD, 20.0 + OVERHEAD]   # ön: 9 sn, arka: 24 sn
    r = project_dock(BUS_POS, SPEED, releases,
                     stop_front=STOP_FRONT, capacity=CAP, slot_spacing=SPACING)
    static_qt = static_front_queue_time(BUS_POS, SPEED, min(releases),
                                        stop_front=STOP_FRONT)
    _print("A", r, static_qt)
    assert r.flowed_through, "A: otobüs akıp geçmeliydi"
    assert r.queue_time < 2.0, f"A: queue_time küçük olmalı, {r.queue_time}"
    print("     -> BEKLENEN: akıp geçti, müdahale gereksiz  [OK]")


def scenario_slow_drain():
    """Öndeki araç 15 sn sonra kalkar → otobüs uçta bekler → YAVAŞLAT gerek."""
    print("\nSENARYO B — kuyruk YAVAŞ boşalıyor (dwell 15 sn)")
    releases = [15.0 + OVERHEAD, 20.0 + OVERHEAD]  # ön: 19 sn, arka: 24 sn
    r = project_dock(BUS_POS, SPEED, releases,
                     stop_front=STOP_FRONT, capacity=CAP, slot_spacing=SPACING)
    static_qt = static_front_queue_time(BUS_POS, SPEED, min(releases),
                                        stop_front=STOP_FRONT)
    _print("B", r, static_qt)
    assert not r.flowed_through, "B: otobüs beklemeliydi"
    assert r.queue_time > 5.0, f"B: queue_time büyük olmalı, {r.queue_time}"
    print("     -> BEKLENEN: uçta bekledi, YAVAŞLAT gerekli  [OK]")


# ════════════════════════════════════════════════════════════════
# 200 araç — toplu kıyas: mevcut (sabit-peron) ETA vs projeksiyon
# Kaç vakada mevcut model 'on_time' (müdahale yok) der ama projeksiyon
# 'uçta sert dur' (queue_time > 2) der → ALTINDA-MÜDAHALE vakaları.
# ════════════════════════════════════════════════════════════════

def aggregate_200():
    print("\n" + "=" * 60)
    print("200 ARAÇ — sabit-peron ETA vs dock projeksiyonu")
    print("=" * 60)
    rng = random.Random(42)
    SP = 20.5   # gerçek sim slot aralığı (20 araç + 0.5 boşluk)
    INTERVENE = 2.0

    n = 200
    under = 0       # static: dokunma, projeksiyon: yavaşlat (kaçırılan müdahale)
    over = 0        # static: yavaşlat, projeksiyon: gereksiz
    agree_slow = 0
    agree_flow = 0
    abs_diff_sum = 0.0

    for _ in range(n):
        cap = rng.randint(1, 5)
        occ = cap if rng.random() < 0.6 else rng.randint(1, cap)  # %60 dolu peron
        releases = [rng.uniform(0.0, 18.0) + OVERHEAD for _ in range(occ)]
        speed = rng.uniform(6.0, 10.0)
        wait_point = -cap * SP
        dist_to_wait = rng.uniform(20.0, 220.0)
        bus_pos = wait_point - dist_to_wait

        r = project_dock(bus_pos, speed, releases,
                         stop_front=0.0, capacity=cap, slot_spacing=SP)
        static_qt = static_front_queue_time(bus_pos, speed, min(releases),
                                            stop_front=0.0)

        proj_slow = r.queue_time > INTERVENE
        stat_slow = static_qt > INTERVENE
        abs_diff_sum += abs(r.queue_time - max(0.0, static_qt))

        if proj_slow and not stat_slow:
            under += 1
        elif stat_slow and not proj_slow:
            over += 1
        elif proj_slow and stat_slow:
            agree_slow += 1
        else:
            agree_flow += 1

    print(f"  Uyum (ikisi de YAVAŞLAT)     : {agree_slow}")
    print(f"  Uyum (ikisi de AKsın)        : {agree_flow}")
    print(f"  ALTINDA-MÜDAHALE (static kaçırdı): {under}   <-- asıl kusur")
    print(f"  Üstünde-müdahale (static fazla)  : {over}")
    print(f"  Ortalama |queue_time farkı|  : {abs_diff_sum / n:5.1f} sn")
    print(f"\n  Sonuç: {under}/{n} vakada mevcut model otobüsü 'zamanında' sanıp")
    print( "  müdahale etmiyor; projeksiyon ise uçta sert duracağını görüyor.")


if __name__ == "__main__":
    print("DOCK PROJEKSİYONU — DOĞRULAMA")
    scenario_fast_drain()
    scenario_slow_drain()
    aggregate_200()
    print("\n[TUM TESTLER GECTI]")
