"""
Eşleştirilmiş Segment Sefer Testi — Beylikdüzü → Mecidiyeköy
=============================================================

Aynı seed'den İKİ özdeş sim (200 araç, segment 0→35, yoğun saat):
biri analitik motor AÇIK (skip-stop dahil), biri KAPALI. Her aracın her
sefer tamamlama süresi iki kolda da kayıt altına alınır ve araç bazında
EŞLEŞTİRİLEREK karşılaştırılır → "skip modeli toplam sefer süresinde
gerçekten iş görüyor mu?" sorusunun doğrudan cevabı.

Kullanım:
    python segment_trip_test.py                      # seed 42, 4500 sim-sn
    python segment_trip_test.py --seed 43 --measure 6000
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from rl_env.config import DT
from sim_server import SimManager

SEG_START = 0    # Beylikdüzü Sondurak
SEG_END   = 35   # Mecidiyeköy
START_HOUR = 8.0  # sabah zirvesi (İBB verisinde sistem tepe saati)


def build(vehicles: int, seed: int, engine: bool) -> SimManager:
    sim = SimManager(vehicle_count=vehicles, seed=seed, start_hour=START_HOUR)
    sim.engine_enabled = engine
    sim.set_route_segment(SEG_START, SEG_END)
    return sim


def per_vehicle_trips(trip_log) -> dict[int, list[float]]:
    """Araç → sefer süreleri (kronolojik). İlk sefer PARÇALIDIR (araç yolun
    ortasından başlar) → analizde atılır."""
    out: dict[int, list[float]] = {}
    for vid, _t, dur, _q, _d in trip_log:
        out.setdefault(vid, []).append(dur)
    return {vid: durs[1:] for vid, durs in out.items() if len(durs) > 1}


def stats(xs: list[float]) -> str:
    if not xs:
        return "veri yok"
    s = sorted(xs)
    p95 = s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]
    return (f"n={len(xs)}  ort={statistics.fmean(xs):7.1f}  "
            f"medyan={statistics.median(xs):7.1f}  p95={p95:7.1f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vehicles", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--measure", type=float, default=4500.0,
                    help="sim süresi (sn)")
    args = ap.parse_args()

    on  = build(args.vehicles, args.seed, engine=True)
    off = build(args.vehicles, args.seed, engine=False)

    seg_name_s = on.stops[SEG_START].name
    seg_name_e = on.stops[SEG_END].name
    print(f"Segment: {seg_name_s} -> {seg_name_e}  |  {args.vehicles} araç  "
          f"|  seed {args.seed}  |  saat {START_HOUR:.0f}:00  "
          f"|  {args.measure:.0f} sim-sn")

    # Özdeş başlangıç doğrulaması
    pos_on  = [round(v.position_meters, 3) for v in on.vehicles]
    pos_off = [round(v.position_meters, 3) for v in off.vehicles]
    assert pos_on == pos_off, "Başlangıç konumları özdeş DEĞİL!"

    steps = int(args.measure / DT)
    traffic_ok = True

    # Durak GEÇİŞ zamanları: (kol, araç, sefer_no) → {stop_idx: sim_time}
    # next_stop_index her arttığında araç o durağı geçmiş demektir
    # (durmuş da olsa atlamış da olsa). Sefer no = o ana dek tamamlanan sefer.
    passage: dict[str, dict] = {"on": {}, "off": {}}
    prev_nsi = {"on": {v.id: v.next_stop_index for v in on.vehicles},
                "off": {v.id: v.next_stop_index for v in off.vehicles}}

    # Konum farkı örneklemesi: her 60 sn'de araç başına (ON − OFF) metre
    pos_gap_samples: list[tuple] = []   # (sim_time, mean, p10, p90)

    def track(arm: str, sim: SimManager) -> None:
        pn = prev_nsi[arm]
        for v in sim.vehicles:
            old = pn.get(v.id, v.next_stop_index)
            if v.next_stop_index != old:
                # eski hedef durak geçildi (artış normalde 1'er olur)
                if v.next_stop_index > old:
                    for si in range(old, v.next_stop_index):
                        key = (v.id, v.trip_completed_count)
                        passage[arm].setdefault(key, {})[si] = sim.sim_time
                pn[v.id] = v.next_stop_index

    for k in range(steps):
        on._step()
        off._step()
        track("on", on)
        track("off", off)
        if k % 600 == 0:   # her 60 sim-sn
            # Tur sıçramasından etkilenmemek için TOPLAM İLERLEME kıyaslanır:
            # ilerleme = tamamlanan_sefer × segment_uzunluğu + segment_içi_konum
            span = on._seg_end_threshold - on._seg_start_pos
            def prog(v):
                return (v.trip_completed_count * span
                        + (v.position_meters - on._seg_start_pos))
            gaps = sorted(prog(a) - prog(b)
                          for a, b in zip(on.vehicles, off.vehicles))
            n = len(gaps)
            pos_gap_samples.append((
                round(on.sim_time), round(sum(gaps) / n, 1),
                round(gaps[int(0.1 * (n - 1))], 1),
                round(gaps[int(0.9 * (n - 1))], 1),
            ))
        if k % 1000 == 0:
            tz_on  = [(round(t.start_meter), round(t.end_meter),
                       round(t.max_speed_ms, 2)) for t in on.traffic_zones]
            tz_off = [(round(t.start_meter), round(t.end_meter),
                       round(t.max_speed_ms, 2)) for t in off.traffic_zones]
            if tz_on != tz_off:
                traffic_ok = False

    print(f"Trafik özdeş kaldı mı: {'EVET' if traffic_ok else 'HAYIR (GEÇERSİZ!)'}")
    print(f"Motor AÇIK kolda skip: {on._skip_total} atlama "
          f"({len(on.trip_log)} sefer kaydı; KAPALI: {len(off.trip_log)})")

    trips_on  = per_vehicle_trips(on.trip_log)
    trips_off = per_vehicle_trips(off.trip_log)

    all_on  = [d for durs in trips_on.values() for d in durs]
    all_off = [d for durs in trips_off.values() for d in durs]
    print()
    print("TAM SEFER SÜRELERİ (ilk parçalı sefer hariç, sn):")
    print(f"  Motor KAPALI : {stats(all_off)}")
    print(f"  Motor AÇIK   : {stats(all_on)}")

    # ── Araç bazında eşleştirilmiş karşılaştırma ─────────────────────
    rows = []
    diffs = []
    for vid in sorted(set(trips_on) & set(trips_off)):
        a, b = trips_on[vid], trips_off[vid]
        n = min(len(a), len(b))
        if n == 0:
            continue
        mean_on  = statistics.fmean(a[:n])
        mean_off = statistics.fmean(b[:n])
        diffs.append(mean_off - mean_on)   # pozitif → AÇIK daha hızlı
        rows.append([vid, n, round(mean_off, 1), round(mean_on, 1),
                     round(mean_off - mean_on, 1)])

    wins = sum(1 for d in diffs if d > 0)
    print()
    print(f"EŞLEŞTİRİLMİŞ KARŞILAŞTIRMA ({len(diffs)} araç, k'inci sefer "
          f"k'inci seferle):")
    if diffs:
        md = statistics.fmean(diffs)
        base = statistics.fmean([r[2] for r in rows])
        print(f"  Ort. sefer farkı  : {md:+.1f} sn/sefer "
              f"({100 * md / base:+.2f}%)  [pozitif = motor AÇIK hızlı]")
        print(f"  Medyan fark       : {statistics.median(diffs):+.1f} sn")
        print(f"  AÇIK'ın kazandığı : {wins}/{len(diffs)} araç "
              f"({100 * wins / len(diffs):.0f}%)")

    out_csv = f"segment_test_s{args.seed}.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["vehicle_id", "paired_trips", "mean_off_s", "mean_on_s",
                    "diff_s_positive_is_on_faster"])
        w.writerows(rows)
    print(f"\nAraç bazlı tablo: {out_csv}")

    # ── Durak bazında skip dökümü ────────────────────────────────────
    skip_csv = f"segment_skips_s{args.seed}.csv"
    with open(skip_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["stop_index", "stop_name", "skip_count"])
        for si, c in sorted(on._skip_by_stop.items(), key=lambda x: -x[1]):
            w.writerow([si, on.stops[si].name, c])
    print(f"Skip dökümü      : {skip_csv}")
    print("\nSKIP YAPILAN DURAKLAR:")
    for si, c in sorted(on._skip_by_stop.items(), key=lambda x: -x[1]):
        print(f"  {on.stops[si].name:<32} {c:3d} atlama")

    # ── Durak-durak kümülatif zaman farkı profili ────────────────────
    # Aynı (araç, sefer)'in aynı durağa varışı: OFF_zamanı − ON_zamanı.
    # NOT: kollar arasında sefer_no hizalaması için yalnızca her iki kolda
    # da mevcut (araç, sefer, durak) üçlüleri eşleştirilir; ilk (parçalı)
    # sefer 0 atılır.
    per_stop_diffs: dict[int, list[float]] = {}
    for key, stops_on in passage["on"].items():
        if key[1] == 0:
            continue
        stops_off = passage["off"].get(key)
        if not stops_off:
            continue
        for si, t_on in stops_on.items():
            t_off = stops_off.get(si)
            if t_off is not None:
                per_stop_diffs.setdefault(si, []).append(t_off - t_on)

    prof_csv = f"segment_station_delta_s{args.seed}.csv"
    with open(prof_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["stop_index", "stop_name", "n_paired",
                    "mean_cum_saving_s", "median_cum_saving_s"])
        for si in sorted(per_stop_diffs):
            ds = per_stop_diffs[si]
            w.writerow([si, on.stops[si].name, len(ds),
                        round(statistics.fmean(ds), 1),
                        round(statistics.median(ds), 1)])
    print(f"Durak-durak kümülatif kazanç profili: {prof_csv}")

    # ── Konum farkı zaman serisi ─────────────────────────────────────
    gap_csv = f"segment_posgap_s{args.seed}.csv"
    with open(gap_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sim_time_s", "mean_gap_m_on_minus_off", "p10_m", "p90_m"])
        w.writerows(pos_gap_samples)
    print(f"Konum farkı serisi (60 sn örneklem): {gap_csv}")
    if pos_gap_samples:
        last = pos_gap_samples[-1]
        print(f"  Koşu sonunda ort. konum farkı: {last[1]:+.0f} m "
              f"(p10 {last[2]:+.0f} / p90 {last[3]:+.0f})")


if __name__ == "__main__":
    main()
