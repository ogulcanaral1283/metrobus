"""
Test Predictive Lookahead Decision Engine
==========================================

Senaryo: 4 otobüs, 3 slot kapasiteli durak.
4. otobüs bunching riski altında → sistem karar verir:
  - Senaryo A: Bunching kabul (bekleme)
  - Senaryo B: Hız filtreleme (yavaşla, tam zamanında var)
"""

import math
import sys
import os

# Parent module import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rl_env.predictive_engine import (
    BusSnapshot, StopInfo, Decision, PredictiveDecision,
    compute_eta, estimate_dwell,
    detect_bunching_risk,
    simulate_scenario_a, simulate_scenario_b,
    evaluate_decision, evaluate_all_buses,
    compute_target_slot_position,
    compute_weighted_score,
)


def make_scenario():
    """
    4 otobüs, 3 slot kapasiteli durak senaryosu.
    
    Durak pozisyonu: 2000m (yeterli mesafe)
    Bus 0: 1800m (200m uzakta) — 10 m/s
    Bus 1: 1600m (400m uzakta) — 10 m/s
    Bus 2: 1400m (600m uzakta) — 10 m/s
    Bus 3: 1200m (800m uzakta) — 10 m/s ← bunching riski
    """
    stop = StopInfo(
        index=5,
        name="Test Durağı",
        position=2000.0,
        capacity=3,
        platform_length=60.0,
    )

    buses = [
        BusSnapshot(bus_id=0, position=1800.0, speed=10.0, acceleration=0.0,
                    phase="cruising", next_stop_index=5,
                    dwell_remaining=0.0, holding_extra=0.0),
        BusSnapshot(bus_id=1, position=1600.0, speed=10.0, acceleration=0.0,
                    phase="cruising", next_stop_index=5,
                    dwell_remaining=0.0, holding_extra=0.0),
        BusSnapshot(bus_id=2, position=1400.0, speed=10.0, acceleration=0.0,
                    phase="cruising", next_stop_index=5,
                    dwell_remaining=0.0, holding_extra=0.0),
        BusSnapshot(bus_id=3, position=1200.0, speed=10.0, acceleration=0.0,
                    phase="cruising", next_stop_index=5,
                    dwell_remaining=0.0, holding_extra=0.0),
    ]

    return buses, stop


class TestETA:
    """ETA hesaplama testleri."""

    def test_basic_eta(self):
        """Basit sabit hızla ETA."""
        # 100m, 10 m/s → ~10sn (+frenleme)
        eta = compute_eta(100.0, 10.0, approach_distance=150.0, comfort_braking=2.0)
        assert eta > 0
        print(f"  ETA(100m, 10m/s) = {eta:.2f}s")

    def test_far_eta(self):
        """Uzak mesafe ETA."""
        # 500m, 10 m/s → cruise(350m/10=35s) + brake(10/2=5s) = ~40s
        eta = compute_eta(500.0, 10.0, approach_distance=150.0, comfort_braking=2.0)
        assert 35 < eta < 50, f"ETA={eta}, expected 35-50"
        print(f"  ETA(500m, 10m/s) = {eta:.2f}s")

    def test_zero_speed(self):
        """Durmuş araç ETA = sonsuz."""
        eta = compute_eta(100.0, 0.0)
        assert eta == float('inf')
        print(f"  ETA(100m, 0m/s) = {eta}")

    def test_zero_distance(self):
        """Mesafe sıfır → ETA = 0."""
        eta = compute_eta(0.0, 10.0)
        assert eta == 0.0
        print(f"  ETA(0m, 10m/s) = {eta:.2f}s")


class TestBunchingDetection:
    """Bunching riski tespiti testleri."""

    def test_4_bus_3_slot_detects_risk(self):
        """4 otobüs, 3 slot → en son varacak otobüs bunching riski."""
        buses, stop = make_scenario()
        
        # 4 otobüsün tamamını kontrol et, en az biri risk altında olmalı
        any_risk = False
        for bus in buses:
            has_risk, rank, etas = detect_bunching_risk(bus, buses, stop)
            if has_risk:
                any_risk = True
                print(f"  Bus {bus.bus_id}: risk=True, rank={rank}")
                print(f"  ETAs: {[(bid, f'{eta:.1f}s') for bid, eta in sorted(etas.items())]}")
        
        assert any_risk, "4 bus / 3 slot → en az bir otobüs bunching riski altında olmalı"

    def test_3_bus_3_slot_no_risk(self):
        """3 otobüs, 3 slot → risk yok."""
        buses, stop = make_scenario()
        buses_3 = buses[:3]
        has_risk, rank, etas = detect_bunching_risk(buses_3[2], buses_3, stop)
        
        assert not has_risk, "3 otobüs 3 slot → risk olmamalı"
        print(f"  3 bus/3 slot: risk={has_risk}, rank={rank}")

    def test_bus_at_station_reduces_capacity(self):
        """Durakta araç varken kapasite azalır."""
        buses, stop = make_scenario()
        # Bus 0 zaten durakta
        buses[0].phase = "stopped"
        buses[0].dwell_remaining = 20.0
        
        # Artık 3-1=2 slot kaldı, bus 2 bile risk altında olabilir
        has_risk, rank, etas = detect_bunching_risk(buses[2], buses, stop)
        print(f"  Durakta araç var: risk={has_risk}, rank={rank}")


class TestScenarioA:
    """Senaryo A (bunching kabul) testleri."""

    def test_basic_scenario_a(self):
        """4 otobüs senaryosu — bunching bekleme süresi."""
        buses, stop = make_scenario()
        etas = {b.bus_id: compute_eta(stop.position - b.position, b.speed) for b in buses}
        
        result = simulate_scenario_a(buses[3], buses, stop, etas, rank_k=4)
        
        assert result.feasible
        assert result.wait_time >= 0, f"Bekleme süresi negatif olamaz: {result.wait_time}"
        assert result.total_time > 0
        print(f"  Senaryo A:")
        print(f"    Varış:    {result.arrival_time:.2f}s")
        print(f"    Bekleme:  {result.wait_time:.2f}s")
        print(f"    Dwell:    {result.dwell_time:.2f}s")
        print(f"    TOPLAM:   {result.total_time:.2f}s")


class TestScenarioB:
    """Senaryo B (hız filtreleme) testleri."""

    def test_basic_scenario_b(self):
        """4 otobüs senaryosu — hız filtreleme."""
        buses, stop = make_scenario()
        etas = {b.bus_id: compute_eta(stop.position - b.position, b.speed) for b in buses}
        
        result = simulate_scenario_b(buses[3], buses, stop, etas, rank_k=4)
        
        if result.feasible:
            assert result.wait_time == 0.0, "Senaryo B'de bekleme olmamalı!"
            assert result.v_filtered < buses[3].speed, \
                f"Filtrelenmiş hız ({result.v_filtered:.2f}) orijinal hızdan ({buses[3].speed}) düşük olmalı"
            assert result.v_filtered > 0
            print(f"  Senaryo B:")
            print(f"    v_filtered: {result.v_filtered:.2f} m/s (orijinal: {buses[3].speed} m/s)")
            print(f"    Hız düşüşü: {(1 - result.v_filtered/buses[3].speed)*100:.1f}%")
            print(f"    Varış:      {result.arrival_time:.2f}s")
            print(f"    Bekleme:    {result.wait_time:.2f}s")
            print(f"    Dwell:      {result.dwell_time:.2f}s")
            print(f"    TOPLAM:     {result.total_time:.2f}s")
        else:
            print(f"  Senaryo B fiziksel olarak uygulanamaz → Senaryo A kazanır")


class TestDecision:
    """Karar karşılaştırma testleri."""

    def test_evaluate_decision(self):
        """Tam karar döngüsü."""
        buses, stop = make_scenario()
        
        decision = evaluate_decision(buses[3], buses, stop)
        
        print(f"  Karar: {decision.decision.value}")
        print(f"  Score A: {decision.score_a:.2f}")
        print(f"  Score B: {decision.score_b:.2f}")
        print(f"  Zaman farkı: {decision.time_saved:.2f}s")
        
        if decision.scenario_a:
            print(f"  Senaryo A — Toplam: {decision.scenario_a.total_time:.2f}s "
                  f"(varış: {decision.scenario_a.arrival_time:.2f}, "
                  f"bekleme: {decision.scenario_a.wait_time:.2f}, "
                  f"dwell: {decision.scenario_a.dwell_time:.2f})")
        if decision.scenario_b and decision.scenario_b.feasible:
            print(f"  Senaryo B — Toplam: {decision.scenario_b.total_time:.2f}s "
                  f"(v_filtered: {decision.scenario_b.v_filtered:.2f} m/s)")
        
        print(f"  Debug: {decision.debug}")

    def test_no_risk_scenario(self):
        """3 otobüs, 3 slot → NO_RISK."""
        _, stop = make_scenario()
        buses_3 = [
            BusSnapshot(bus_id=0, position=900.0, speed=10.0, acceleration=0.0,
                        phase="cruising", next_stop_index=5,
                        dwell_remaining=0.0, holding_extra=0.0),
            BusSnapshot(bus_id=1, position=850.0, speed=10.0, acceleration=0.0,
                        phase="cruising", next_stop_index=5,
                        dwell_remaining=0.0, holding_extra=0.0),
            BusSnapshot(bus_id=2, position=800.0, speed=10.0, acceleration=0.0,
                        phase="cruising", next_stop_index=5,
                        dwell_remaining=0.0, holding_extra=0.0),
        ]
        
        decision = evaluate_decision(buses_3[2], buses_3, stop)
        assert decision.decision == Decision.NO_RISK
        print(f"  3 bus / 3 slot → karar: {decision.decision.value} ✓")

    def test_bunching_accept_when_faster(self):
        """Bunching kabul edilmesi gereken senaryo — araçlar çok yakın."""
        _, stop = make_scenario()
        # Araçları çok yakın koy → hız filtreleme imkansız veya daha yavaş
        buses = [
            BusSnapshot(bus_id=0, position=1990.0, speed=2.0, acceleration=0.0,
                        phase="cruising", next_stop_index=5,
                        dwell_remaining=0.0, holding_extra=0.0),
            BusSnapshot(bus_id=1, position=1985.0, speed=2.0, acceleration=0.0,
                        phase="cruising", next_stop_index=5,
                        dwell_remaining=0.0, holding_extra=0.0),
            BusSnapshot(bus_id=2, position=1980.0, speed=2.0, acceleration=0.0,
                        phase="cruising", next_stop_index=5,
                        dwell_remaining=0.0, holding_extra=0.0),
            BusSnapshot(bus_id=3, position=1975.0, speed=2.0, acceleration=0.0,
                        phase="cruising", next_stop_index=5,
                        dwell_remaining=0.0, holding_extra=0.0),
        ]
        
        decision = evaluate_decision(buses[3], buses, stop)
        print(f"  Yakın araçlar → karar: {decision.decision.value}")
        print(f"  Score A={decision.score_a:.2f}, Score B={decision.score_b:.2f}")


class TestSlotSelection:
    """Slot seçim testleri."""

    def test_empty_platform(self):
        """Boş platform → slot 1 seç."""
        stop = StopInfo(index=0, name="Test", position=1000.0,
                        capacity=3, platform_length=60.0)
        slot, pos = compute_target_slot_position(stop, [])
        assert slot == 1
        assert pos == 1000.0
        print(f"  Boş platform: slot={slot}, pos={pos}m ✓")

    def test_slot1_occupied(self):
        """Slot 1 dolu → slot 2 seç."""
        stop = StopInfo(index=0, name="Test", position=1000.0,
                        capacity=3, platform_length=60.0)
        slot, pos = compute_target_slot_position(stop, [1])
        assert slot == 2
        print(f"  Slot 1 dolu: slot={slot}, pos={pos:.1f}m ✓")

    def test_all_full(self):
        """Tüm slotlar dolu → dışarıda kal."""
        stop = StopInfo(index=0, name="Test", position=1000.0,
                        capacity=3, platform_length=60.0)
        slot, pos = compute_target_slot_position(stop, [1, 2, 3])
        assert slot == -1
        print(f"  Tümü dolu: slot={slot}, pos={pos:.1f}m ✓")


class TestEvaluateAll:
    """Toplu değerlendirme testleri."""

    def test_evaluate_all(self):
        """Tüm otobüsleri değerlendir."""
        buses, stop = make_scenario()
        decisions = evaluate_all_buses(buses, [stop])
        
        print(f"  Toplam karar: {len(decisions)}")
        for bus_id, dec in decisions.items():
            print(f"    Bus {bus_id}: {dec.decision.value}")
        
        # Bus 3 bir karar almış olmalı (NO_RISK veya SPEED_FILTER veya BUNCHING_ACCEPT)
        assert 3 in decisions
        # İlk 3 otobüs risk altında olmamalı
        # (Rank 1-3 kapasiteye sığıyor)


def run_all():
    """Tüm testleri çalıştır."""
    test_classes = [
        TestETA, TestBunchingDetection, TestScenarioA,
        TestScenarioB, TestDecision, TestSlotSelection, TestEvaluateAll,
    ]

    total = 0
    passed = 0
    failed = 0

    for cls in test_classes:
        print(f"\n{'='*60}")
        print(f"  {cls.__name__}")
        print(f"{'='*60}")
        
        instance = cls()
        methods = [m for m in dir(instance) if m.startswith("test_")]
        
        for method_name in sorted(methods):
            total += 1
            method = getattr(instance, method_name)
            try:
                print(f"\n▶ {method_name}")
                method()
                passed += 1
                print(f"  ✓ PASSED")
            except AssertionError as e:
                failed += 1
                print(f"  ✗ FAILED: {e}")
            except Exception as e:
                failed += 1
                print(f"  ✗ ERROR: {type(e).__name__}: {e}")

    print(f"\n{'='*60}")
    print(f"  Sonuç: {passed}/{total} PASSED, {failed} FAILED")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
