# -*- coding: utf-8 -*-
"""
Sunum icin buyuk-fontlu sonuc grafikleri:
  slides/ab_improvement.png : 3-seed A/B iyilesme cubuklari
  slides/trip_time_bars.png : segment deneyi sefer suresi OFF vs ON
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INK, INK2, LINE = "#1F2933", "#5B6470", "#D7DDE4"
BLUE, GREEN, FILLB = "#29629C", "#2EA043", "#B8CFE8"

os.makedirs("slides", exist_ok=True)
plt.rcParams.update({
    "font.family": "DejaVu Sans", "text.color": INK,
    "axes.edgecolor": LINE, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2,
})

# ── 1. A/B iyilesme cubuklari (3 seed ortalamasi) ───────────────────
metrics = [
    ("Station queue time", 44.8),
    ("Bunching pairs", 10.9),
    ("Headway CV", 4.1),
    ("Trip duration", 0.5),
]
fig, ax = plt.subplots(figsize=(7.6, 4.2), facecolor="white")
fig.subplots_adjust(left=0.34, right=0.90, top=0.86, bottom=0.14)
names = [m[0] for m in metrics][::-1]
vals = [m[1] for m in metrics][::-1]
colors = [FILLB if v < 2 else "#7FA8D4" if v < 20 else BLUE for v in vals]
ax.barh(range(len(vals)), vals, height=0.58, color=colors, edgecolor="white")
for i, v in enumerate(vals):
    ax.text(v + 0.8, i, f"−{v:.1f}%", va="center", fontsize=17,
            fontweight="bold", color=BLUE if v > 2 else INK2)
ax.set_yticks(range(len(names)))
ax.set_yticklabels(names, fontsize=16)
ax.set_xlim(0, 52)
ax.set_xticks([])
for sp in ("top", "right", "bottom"):
    ax.spines[sp].set_visible(False)
ax.tick_params(length=0)
ax.set_title("Engine ON vs OFF — reduction, mean of 3 seeds (200 vehicles)",
             fontsize=15, loc="left", color=INK, pad=12)
fig.savefig("slides/ab_improvement.png", dpi=200, facecolor="white")
print("OK: slides/ab_improvement.png")

# ── 2. Segment sefer suresi cubuklari ───────────────────────────────
fig, ax = plt.subplots(figsize=(6.4, 4.4), facecolor="white")
fig.subplots_adjust(left=0.14, right=0.96, top=0.84, bottom=0.12)
vals = [3786.9 / 60, 3535.0 / 60]
labels = ["Engine OFF", "Engine ON"]
bars = ax.bar([0, 1], vals, width=0.52, color=["#9AA7B4", BLUE],
              edgecolor="white")
for x, v in zip([0, 1], vals):
    ax.text(x, v + 0.5, f"{v:.1f} min", ha="center", fontsize=18,
            fontweight="bold", color=INK)
ax.annotate("", xy=(1, vals[1] + 5.6), xytext=(0, vals[0] + 5.6),
            arrowprops=dict(arrowstyle="->", color=GREEN, lw=2.4))
ax.text(0.5, vals[0] + 7.4, "−4.1 min per trip (−6.5%)",
        ha="center", fontsize=17, fontweight="bold", color=GREEN)
ax.set_xticks([0, 1])
ax.set_xticklabels(labels, fontsize=16)
ax.set_ylim(0, 78)
ax.set_yticks([0, 20, 40, 60])
ax.set_ylabel("Mean trip time (min)", fontsize=13)
for sp in ("top", "right"):
    ax.spines[sp].set_visible(False)
ax.grid(axis="y", color=LINE, lw=0.6, alpha=0.6)
ax.set_title("Beylikdüzü → Mecidiyeköy, 200 vehicles, 08:00 rush",
             fontsize=15, loc="left", color=INK, pad=12)
fig.savefig("slides/trip_time_bars.png", dpi=200, facecolor="white")
print("OK: slides/trip_time_bars.png")
