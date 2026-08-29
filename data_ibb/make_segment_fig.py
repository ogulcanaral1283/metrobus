# -*- coding: utf-8 -*-
"""
Segment deneyi rapor figürü (İngilizce etiketler):
  Sol : AÇIK filonun KAPALI ikize göre ortalama ilerleme farkı (zaman serisi)
  Sağ : durak bazında skip dağılımı
Çıktı: report/figures/segment_ab_results.png
"""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INK, INK2, LINE = "#1F2933", "#5B6470", "#D7DDE4"
BLUE, FILLB = "#29629C", "#B8CFE8"

# ── veri ─────────────────────────────────────────────────────────────
t, mean_g, p10, p90 = [], [], [], []
with open("results/segment_posgap_s42.csv", newline="", encoding="utf-8") as fh:
    for row in csv.DictReader(fh):
        t.append(float(row["sim_time_s"]) / 60.0)   # dk
        mean_g.append(float(row["mean_gap_m_on_minus_off"]))
        p10.append(float(row["p10_m"]))
        p90.append(float(row["p90_m"]))

skips = []
with open("results/segment_skips_s42.csv", newline="", encoding="utf-8") as fh:
    for row in csv.DictReader(fh):
        skips.append((row["stop_name"], int(row["skip_count"])))
skips.sort(key=lambda x: x[1])

SHORT = {
    "Topkapı - Şehit Mustafa Cambaz": "Topkapı",
    "Okmeydanı Hastane Metrobüs durağı": "Okmeydanı Hastane",
    "Büyükşehir Belediyesi Sosyal Tesisleri": "İBB Sosyal Tesisler",
    "Ayvansaray Eyüpsultan": "Ayvansaray",
}
names = [SHORT.get(n, n) for n, _ in skips]
counts = [c for _, c in skips]

plt.rcParams.update({
    "font.family": "DejaVu Sans", "text.color": INK,
    "axes.edgecolor": LINE, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2,
})

fig, (ax1, ax2) = plt.subplots(
    1, 2, figsize=(12.5, 4.4), facecolor="white",
    gridspec_kw={"width_ratios": [1.5, 1], "wspace": 0.28,
                 "left": 0.07, "right": 0.98, "top": 0.86, "bottom": 0.15},
)

# ── Panel A: ilerleme farkı ─────────────────────────────────────────
ax1.fill_between(t, p10, p90, color=FILLB, alpha=0.55, label="P10–P90 band")
ax1.plot(t, mean_g, color=BLUE, lw=2.2, label="Fleet mean")
ax1.axhline(0, color=LINE, lw=1)
ax1.set_xlabel("Simulated time (min)", fontsize=10.5)
ax1.set_ylabel("Progress lead of engine-ON twin (m)", fontsize=10.5)
ax1.set_title("Per-vehicle progress lead over the engine-OFF twin",
              fontsize=11.5, color=INK, loc="left", pad=10)
ax1.legend(frameon=False, fontsize=9.5, loc="upper left")
ax1.annotate(f"+{mean_g[-1]:,.0f} m", xy=(t[-1], mean_g[-1]),
             xytext=(-64, 6), textcoords="offset points",
             fontsize=10.5, fontweight="bold", color=BLUE)
for sp in ("top", "right"):
    ax1.spines[sp].set_visible(False)
ax1.grid(axis="y", color=LINE, lw=0.6, alpha=0.6)
ax1.set_xlim(0, t[-1])

# ── Panel B: durak bazli skip ───────────────────────────────────────
ax2.barh(range(len(names)), counts, height=0.6, color="#7FA8D4",
         edgecolor="white")
ax2.set_yticks(range(len(names)))
ax2.set_yticklabels(names, fontsize=9.5)
for i, c in enumerate(counts):
    ax2.text(c + 1, i, str(c), va="center", fontsize=9.5, color=INK)
ax2.set_xlim(0, max(counts) * 1.14)
ax2.set_xlabel("Skips executed (2 h, engine-ON arm)", fontsize=10.5)
ax2.set_title("Skips by station — all in the low-demand tier",
              fontsize=11.5, color=INK, loc="left", pad=10)
for sp in ("top", "right"):
    ax2.spines[sp].set_visible(False)
ax2.tick_params(length=0)

out = "data_ibb/segment_ab_results.png"
fig.savefig(out, dpi=180, facecolor="white")
print("OK:", out)
