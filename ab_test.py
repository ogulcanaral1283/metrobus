"""
Headless A/B Test — Analitik Motor AÇIK vs KAPALI
=================================================

Aynı seed'den iki özdeş simülasyon koşar (biri motor AÇIK, biri KAPALI),
sabit bir horizon boyunca warm-up'ı dışlayarak metrik biriktirir ve tek bir
karşılaştırma sonucu üretir. Canlı dashboard akışının aksine bu, tekrarlanabilir
ve raporlanabilir bir A/B ÖLÇÜMÜ verir.

Kullanım:
    python ab_test.py                       # varsayılan: 200 araç
    python ab_test.py --vehicles 200 --measure 1800 --warmup 300
    python ab_test.py --check-determinism    # motor-KAPALI iki kez → birebir aynı mı?

Tasarım kararları:
  * Trafik ve dwell ayrı RNG akışlarından beslendiği için (bkz. SimManager),
    AÇIK ve KAPALI sim AYNI trafiği yaşar. Bunu measurement boyunca
    invariant olarak doğrularız (traffic_zones birebir eşit kalmalı).
  * Metrikler warm-up sonrası, sabit aralıklarla, İKİ sim için de AYNI tick'te
    örneklenir → same-tick karşılaştırma.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from dataclasses import dataclass, field

# Windows konsolu CP1254/charmap olabilir; bazı karakterler (ör. ok) çöker.
# stdout'u UTF-8'e çevir, kodlanamayanı değiştir — asla crash etme.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from rl_env.config import DT
from sim_server import SimManager


@dataclass
class ArmResult:
    """Tek bir kol (motor AÇIK ya da KAPALI) için biriktirilmiş metrikler."""
    cv_samples: list[float] = field(default_factory=list)
    bunching_samples: list[float] = field(default_factory=list)
    mean_headway_samples: list[float] = field(default_factory=list)
    final: dict = field(default_factory=dict)

    def _mean(self, xs: list[float]) -> float:
        return statistics.fmean(xs) if xs else 0.0

    def _p95(self, xs: list[float]) -> float:
        if not xs:
            return 0.0
        s = sorted(xs)
        k = min(len(s) - 1, int(round(0.95 * (len(s) - 1))))
        return s[k]

    def summary(self) -> dict:
        return {
            "headwayCV_mean": round(self._mean(self.cv_samples), 4),
            "headwayCV_p95": round(self._p95(self.cv_samples), 4),
            "bunching_mean": round(self._mean(self.bunching_samples), 3),
            "bunching_p95": round(self._p95(self.bunching_samples), 3),
            "meanHeadway_mean": round(self._mean(self.mean_headway_samples), 2),
            "tripCount": self.final.get("tripCount", 0),
            "tripAvgDuration": self.final.get("tripAvgDuration", 0),
            "tripAvgQueueTime": self.final.get("tripAvgQueueTime", 0),
            "tripAvgDwellTime": self.final.get("tripAvgDwellTime", 0),
            # Yaklaşma kaybı: A (kuyruk) vs B (proaktif yavaşlama), kapı açana kadar
            "approachQueueLossMean": self.final.get("approachQueueLossMean", 0),
            "approachQueueCount": self.final.get("approachQueueCount", 0),
            "approachSlowLossMean": self.final.get("approachSlowLossMean", 0),
            "approachSlowCount": self.final.get("approachSlowCount", 0),
            "samples": len(self.cv_samples),
        }


def _build_arm(vehicle_count: int, seed: int, direction: str,
               start_hour: float, engine: bool,
               seg_start: int | None = None,
               seg_end: int | None = None) -> SimManager:
    sim = SimManager(
        vehicle_count=vehicle_count, direction=direction,
        start_hour=start_hour, time_scale=1.0, seed=seed,
    )
    sim.engine_enabled = engine
    # Segment kısıtı: araçları iki durak arasına dağıt ve orada döngüye al.
    # set_route_segment indeks tabanlı (RNG yok) → iki kol birebir aynı
    # başlangıç konumlarından başlar. Motor AÇIK/KAPALI yalnızca t=0 sonrası ayrışır.
    if seg_start is not None and seg_end is not None:
        sim.set_route_segment(seg_start, seg_end)
    return sim


def run_ab(vehicle_count: int = 200, warmup_s: float = 300.0,
           measure_s: float = 1800.0, sample_interval_s: float = 10.0,
           seed: int = 42, direction: str = "gidis",
           start_hour: float = 7.0,
           seg_start: int | None = None,
           seg_end: int | None = None) -> dict:
    """İki kollu A/B koşusu. Sonuç dict döndürür."""
    sim_on = _build_arm(vehicle_count, seed, direction, start_hour, engine=True,
                        seg_start=seg_start, seg_end=seg_end)
    sim_off = _build_arm(vehicle_count, seed, direction, start_hour, engine=False,
                         seg_start=seg_start, seg_end=seg_end)

    # Başlangıç konumları birebir aynı mı? (segment dağıtımı deterministik olmalı)
    p_on = [round(v.position_meters, 3) for v in sim_on.vehicles]
    p_off = [round(v.position_meters, 3) for v in sim_off.vehicles]
    start_identical = p_on == p_off

    warmup_steps = int(round(warmup_s / DT))
    measure_steps = int(round(measure_s / DT))
    sample_every = max(1, int(round(sample_interval_s / DT)))

    # --- Warm-up (metrik toplanmaz) ---
    for _ in range(warmup_steps):
        sim_on._step()
        sim_off._step()

    # Yaklaşma kaybı örnekleri kümülatif birikir → warm-up'takileri at, sadece
    # ölçüm penceresindeki durak ziyaretleri sayılsın.
    sim_on.reset_approach_metrics()
    sim_off.reset_approach_metrics()

    res_on, res_off = ArmResult(), ArmResult()
    traffic_diverged_at: float | None = None

    # --- Measurement penceresi ---
    for i in range(measure_steps):
        sim_on._step()
        sim_off._step()

        # Invariant: ayrık RNG akışları sayesinde trafik İKİ simde de özdeş
        # kalmalı. Eşit değilse confound geri dönmüş demektir.
        if traffic_diverged_at is None and sim_on.traffic_zones != sim_off.traffic_zones:
            traffic_diverged_at = round(sim_on.sim_time, 1)

        if i % sample_every == 0:
            m_on = sim_on.compute_comparison_metrics()
            m_off = sim_off.compute_comparison_metrics()
            res_on.cv_samples.append(m_on["headwayCV"])
            res_on.bunching_samples.append(m_on["bunchingPairs"])
            res_on.mean_headway_samples.append(m_on["meanHeadway"])
            res_off.cv_samples.append(m_off["headwayCV"])
            res_off.bunching_samples.append(m_off["bunchingPairs"])
            res_off.mean_headway_samples.append(m_off["meanHeadway"])

    res_on.final = sim_on.compute_comparison_metrics()
    res_off.final = sim_off.compute_comparison_metrics()

    on_sum = res_on.summary()
    off_sum = res_off.summary()

    def _improvement(off_val: float, on_val: float) -> float:
        """Düşmesi istenen metrikte iyileşme yüzdesi (off → on)."""
        if off_val == 0:
            return 0.0
        return round(100.0 * (off_val - on_val) / off_val, 1)

    seg_names = None
    if seg_start is not None and seg_end is not None:
        seg_names = (sim_on.stops[seg_start].name, sim_on.stops[seg_end].name)

    return {
        "config": {
            "vehicle_count": vehicle_count, "seed": seed,
            "warmup_s": warmup_s, "measure_s": measure_s,
            "sample_interval_s": sample_interval_s,
            "direction": direction, "start_hour": start_hour,
            "seg_start": seg_start, "seg_end": seg_end,
            "seg_names": seg_names,
        },
        "start_identical": start_identical,
        "engine_on": on_sum,
        "engine_off": off_sum,
        "improvement_pct": {
            "headwayCV": _improvement(off_sum["headwayCV_mean"], on_sum["headwayCV_mean"]),
            "bunching": _improvement(off_sum["bunching_mean"], on_sum["bunching_mean"]),
            "tripAvgQueueTime": _improvement(off_sum["tripAvgQueueTime"], on_sum["tripAvgQueueTime"]),
            "tripAvgDuration": _improvement(off_sum["tripAvgDuration"], on_sum["tripAvgDuration"]),
        },
        "traffic_identical": traffic_diverged_at is None,
        "traffic_diverged_at": traffic_diverged_at,
    }


def check_determinism(vehicle_count: int = 200, steps_s: float = 300.0,
                      seed: int = 42, direction: str = "gidis",
                      start_hour: float = 7.0) -> bool:
    """Motor-KAPALI iki özdeş koşu birebir aynı sonucu veriyor mu?

    2.1 düzeltmesinin determinizmi bozmadığını kanıtlar: aynı seed → aynı
    araç konumları (bit-level).
    """
    a = _build_arm(vehicle_count, seed, direction, start_hour, engine=False)
    b = _build_arm(vehicle_count, seed, direction, start_hour, engine=False)
    steps = int(round(steps_s / DT))
    for _ in range(steps):
        a._step()
        b._step()
    pa = [v.position_meters for v in a.vehicles]
    pb = [v.position_meters for v in b.vehicles]
    identical = pa == pb
    max_diff = max((abs(x - y) for x, y in zip(pa, pb)), default=0.0)
    print(f"[DETERMINIZM] {vehicle_count} arac, {steps_s:.0f}s -> "
          f"{'BIREBIR AYNI' if identical else 'FARKLI'} (max konum farki: {max_diff:.2e} m)")
    return identical


def run_multi(seeds: list[int], **kwargs) -> dict:
    """Birden fazla seed ile A/B koş, seed'ler arası ortalama ± std üret."""
    results = []
    for idx, sd in enumerate(seeds, 1):
        print(f"[A/B] seed {sd} ({idx}/{len(seeds)}) kosuluyor...")
        r = run_ab(seed=sd, **kwargs)
        results.append(r)
        on, off = r["engine_on"], r["engine_off"]
        imp = r["improvement_pct"]
        print(f"      -> CV {off['headwayCV_mean']:.3f}->{on['headwayCV_mean']:.3f} "
              f"({imp['headwayCV']:+.1f}%) | bunching {imp['bunching']:+.1f}% | "
              f"kuyruk {imp['tripAvgQueueTime']:+.1f}% | "
              f"trafik {'OK' if r['traffic_identical'] else 'DIVERGED'}")
    return _aggregate(results)


def _stats(vals: list[float]) -> tuple[float, float]:
    """(ortalama, std). Tek eleman varsa std=0."""
    m = statistics.fmean(vals) if vals else 0.0
    s = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    return m, s


def _aggregate(results: list[dict]) -> dict:
    seeds = [r["config"]["seed"] for r in results]
    imp_keys = ["headwayCV", "bunching", "tripAvgQueueTime", "tripAvgDuration"]
    agg_imp = {k: _stats([r["improvement_pct"][k] for r in results]) for k in imp_keys}

    def arm(name: str) -> dict:
        mk = ["headwayCV_mean", "bunching_mean", "meanHeadway_mean",
              "tripAvgQueueTime", "tripAvgDuration", "tripCount"]
        return {k: _stats([r[name][k] for r in results]) for k in mk}

    return {
        "n": len(results),
        "seeds": seeds,
        "config": results[0]["config"] if results else {},
        "engine_on": arm("engine_on"),
        "engine_off": arm("engine_off"),
        "improvement_pct": agg_imp,
        "all_traffic_identical": all(r["traffic_identical"] for r in results),
        "per_seed": results,
    }


def _print_multi(agg: dict) -> None:
    c = agg["config"]
    on, off, imp = agg["engine_on"], agg["engine_off"], agg["improvement_pct"]
    print("=" * 72)
    print(f"COK-SEED A/B SONUCU  (n={agg['n']} seed: {agg['seeds']})")
    print("=" * 72)
    print(f"  Arac: {c['vehicle_count']} | warm-up: {c['warmup_s']:.0f}s | "
          f"olcum: {c['measure_s']:.0f}s | ornek araligi: {c['sample_interval_s']:.0f}s")
    print(f"  Tum kosularda trafik ozdes (A==B): "
          f"{'EVET' if agg['all_traffic_identical'] else 'HAYIR'}")
    print("-" * 72)
    print(f"  {'Metrik':<20}{'KAPALI (m+/-s)':>20}{'ACIK (m+/-s)':>20}{'Iyilesme':>12}")
    print("-" * 72)

    def row(label, off_key, on_key, imp_key):
        om, os_ = off[off_key]
        nm, ns = on[on_key]
        im, is_ = imp[imp_key]
        print(f"  {label:<20}{om:>9.3f}+/-{os_:<7.3f}{nm:>9.3f}+/-{ns:<7.3f}"
              f"{im:>+7.1f}%")

    row("Headway CV", "headwayCV_mean", "headwayCV_mean", "headwayCV")
    row("Bunching", "bunching_mean", "bunching_mean", "bunching")
    row("Sefer kuyruk (sn)", "tripAvgQueueTime", "tripAvgQueueTime", "tripAvgQueueTime")
    row("Sefer suresi (sn)", "tripAvgDuration", "tripAvgDuration", "tripAvgDuration")
    mhm, mhs = off["meanHeadway_mean"]
    nhm, nhs = on["meanHeadway_mean"]
    print(f"  {'Mean headway (sn)':<20}{mhm:>9.2f}+/-{mhs:<7.2f}{nhm:>9.2f}+/-{nhs:<7.2f}")
    tcm, _ = off["tripCount"]
    ntm, _ = on["tripCount"]
    print(f"  {'Tamamlanan sefer':<20}{tcm:>16.1f}{ntm:>20.1f}")
    print("=" * 72)
    print("  (Iyilesme: pozitif = motor ACIK daha iyi; +/- = seed'ler arasi std)")
    print("=" * 72)


def _print_report(r: dict) -> None:
    c = r["config"]
    on, off = r["engine_on"], r["engine_off"]
    imp = r["improvement_pct"]
    print("=" * 64)
    print("A/B TEST SONUCU — Analitik Motor AÇIK vs KAPALI")
    print("=" * 64)
    print(f"  Araç: {c['vehicle_count']} | seed: {c['seed']} | "
          f"warm-up: {c['warmup_s']:.0f}s | ölçüm: {c['measure_s']:.0f}s "
          f"| örnek: {on['samples']}")
    if c.get("seg_names"):
        print(f"  Segment: {c['seg_names'][0]} -> {c['seg_names'][1]} "
              f"(durak {c['seg_start']}..{c['seg_end']})")
    print(f"  Başlangıç konumları özdeş mi (A==B): "
          f"{'EVET' if r.get('start_identical') else 'HAYIR'}")
    print(f"  Trafik özdeş mi (A==B): "
          f"{'EVET' if r['traffic_identical'] else 'HAYIR @ %.1fs' % r['traffic_diverged_at']}")
    print("-" * 64)
    print(f"  {'Metrik':<22}{'KAPALI':>12}{'AÇIK':>12}{'İyileşme':>14}")
    print("-" * 64)

    def row(label, off_v, on_v, imp_key, unit=""):
        ip = imp.get(imp_key)
        ip_s = f"{ip:+.1f}%" if ip is not None else ""
        print(f"  {label:<22}{off_v:>12}{on_v:>12}{ip_s:>14}")

    row("Headway CV (ort)", off["headwayCV_mean"], on["headwayCV_mean"], "headwayCV")
    print(f"  {'Headway CV (p95)':<22}{off['headwayCV_p95']:>12}{on['headwayCV_p95']:>12}")
    row("Bunching (ort)", off["bunching_mean"], on["bunching_mean"], "bunching")
    print(f"  {'Mean headway (sn)':<22}{off['meanHeadway_mean']:>12}{on['meanHeadway_mean']:>12}")
    row("Sefer kuyruk (sn)", off["tripAvgQueueTime"], on["tripAvgQueueTime"], "tripAvgQueueTime")
    row("Sefer süresi (sn)", off["tripAvgDuration"], on["tripAvgDuration"], "tripAvgDuration")
    print(f"  {'Tamamlanan sefer':<22}{off['tripCount']:>12}{on['tripCount']:>12}")
    print("=" * 64)
    print("  (İyileşme: pozitif = motor AÇIK daha iyi — metrik düştü)")
    print("=" * 64)

    # --- Yaklaşma kaybı: Senaryo A (kuyruk) vs B (proaktif yavaşlama) ---
    # Tanım: bir durak ziyaretinde 'müdahale anından kapı açılmaya' kadar süre.
    #   A = kuyruğa girişten (motor KAPALI'da baskın yol)
    #   B = ilk yavaşlatmadan (motor AÇIK'ta baskın yol)
    print("YAKLAŞMA KAYBI — müdahaleden kapı açılmaya kadar (durak ziyareti başına)")
    print("-" * 64)
    print(f"  {'':<22}{'KAPALI':>12}{'AÇIK':>12}")
    print(f"  {'A kuyruk ort (sn)':<22}{off['approachQueueLossMean']:>12}{on['approachQueueLossMean']:>12}")
    print(f"  {'A kuyruk olay':<22}{off['approachQueueCount']:>12}{on['approachQueueCount']:>12}")
    print(f"  {'B yavaşla ort (sn)':<22}{off['approachSlowLossMean']:>12}{on['approachSlowLossMean']:>12}")
    print(f"  {'B yavaşla olay':<22}{off['approachSlowCount']:>12}{on['approachSlowCount']:>12}")
    print("=" * 64)
    print("  (Motor AÇIK: kuyruk olayları B-yavaşlama olaylarına dönüşür;")
    print("   kuyruğa giren araç sayısı düşerken yolda yumuşak yavaşlama artar.)")
    print("=" * 64)


def main() -> None:
    p = argparse.ArgumentParser(description="Headless A/B test (motor AÇIK vs KAPALI)")
    p.add_argument("--vehicles", type=int, default=200)
    p.add_argument("--warmup", type=float, default=300.0, help="warm-up süresi (sn)")
    p.add_argument("--measure", type=float, default=1800.0, help="ölçüm süresi (sn)")
    p.add_argument("--sample", type=float, default=10.0, help="örnekleme aralığı (sn)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--seeds", type=int, nargs="+", default=None,
                   help="cok-seedli kosu: birden fazla seed (orn: --seeds 1 2 3)")
    p.add_argument("--num-seeds", type=int, default=None,
                   help="cok-seedli kosu: --seed'ten baslayarak N ardisik seed")
    p.add_argument("--direction", type=str, default="gidis")
    p.add_argument("--start-hour", type=float, default=7.0)
    p.add_argument("--seg-start", type=int, default=None,
                   help="segment baslangic durak index'i (orn: 0 = Beylikduzu Sondurak)")
    p.add_argument("--seg-end", type=int, default=None,
                   help="segment bitis durak index'i (orn: 25 = Cevizlibag)")
    p.add_argument("--check-determinism", action="store_true",
                   help="A/B yerine: motor-KAPALI iki koşu birebir aynı mı?")
    args = p.parse_args()

    if args.check_determinism:
        ok = check_determinism(vehicle_count=args.vehicles, steps_s=args.warmup,
                               seed=args.seed, direction=args.direction,
                               start_hour=args.start_hour)
        raise SystemExit(0 if ok else 1)

    seed_list = None
    if args.seeds:
        seed_list = args.seeds
    elif args.num_seeds:
        seed_list = [args.seed + i for i in range(args.num_seeds)]

    if seed_list:
        agg = run_multi(
            seeds=seed_list,
            vehicle_count=args.vehicles, warmup_s=args.warmup,
            measure_s=args.measure, sample_interval_s=args.sample,
            direction=args.direction, start_hour=args.start_hour,
            seg_start=args.seg_start, seg_end=args.seg_end,
        )
        _print_multi(agg)
        return

    result = run_ab(
        vehicle_count=args.vehicles, warmup_s=args.warmup,
        measure_s=args.measure, sample_interval_s=args.sample,
        seg_start=args.seg_start, seg_end=args.seg_end,
        seed=args.seed, direction=args.direction, start_hour=args.start_hour,
    )
    _print_report(result)


if __name__ == "__main__":
    main()
