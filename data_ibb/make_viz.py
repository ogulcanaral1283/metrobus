# -*- coding: utf-8 -*-
"""
Metrobüs durak-bazlı saatlik yoğunluk görseli (İBB/BELBİM Ekim 2024).

Ana görsel: koridor-sıralı durak x saat ısı haritası
  + üst marjinal: sistem saatlik profili
  + sağ marjinal: durak günlük toplamları
Sıralı (sequential) tek ton: Blues — açık→koyu = az→çok yolcu.

Çalıştır:  python data_ibb/make_viz.py
Çıktı  :  data_ibb/metrobus_yogunluk_ekim2024.png
"""
import sys, re, unicodedata
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import gridspec
from matplotlib.colors import PowerNorm

sys.path.insert(0, ".")
from rl_env.route_data import load_route

# ── veriler ──────────────────────────────────────────────────────────
pivot = pd.read_csv("data_ibb/metrobus_station_hourly_202410.csv", index_col=0)
pivot.columns = [int(c) for c in pivot.columns]
pivot = pivot.reindex(columns=range(24), fill_value=0)

route_names = [s.name for s in load_route().stops]


def norm(s: str) -> str:
    s = str(s)
    tr = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    s = s.translate(tr)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", s.upper())


# İBB adı -> sim rota adı (elle eşleme; kısaltma/farklı yazımlar)
MANUAL = {
    "AVCILARMRKUNVKAMP": "AvcilarMerkezUniversiteKampusu",
    "IBBSOSYALTESISLER": "BuyuksehirBelediyesiSosyalTesisleri",
    "OKMEYDANIHASTANE": "OkmeydaniHastaneMetrobusduragi",
    "TOPKAPI": "TopkapiSehitMustafaCambaz",
    "BAYRAMPASAMALTEPE": "BayrampasaMaltepeKocUniversitesiHastanesi",
    "15TEMMUZSEHITLERKOPRUSU": "15TemmuzSehitlerKoprusu",
    "BOGAZICIKOPRUSU": "15TemmuzSehitlerKoprusu",
    "BOGAZKOPRUSU": "15TemmuzSehitlerKoprusu",
    "CIHANGIRUNIVERSITEMAH": "CihangirUnivmah",
    "HARAMIDERESANAYISITESI": "HaramidereSanayi",
    "AYVANSARAY": "AyvansarayEyupsultan",
    "BEYLIKDUZUBELEDIYESI": "BeylikduzuBelediye",
    "CIHANGIRUNIVMAH": "CihangirUnivmah",
    "DARULACEZEPERPA": "DarulacezePerpa",
}
MANUAL = {k: norm(v) for k, v in MANUAL.items()}

route_norm = {norm(n): n for n in route_names}

order, matched, unmatched = [], {}, []
for st in pivot.index:
    key = norm(st)
    key = MANUAL.get(key, key)
    hit = None
    if key in route_norm:
        hit = key
    else:
        # En UZUN rota adayini tercih et — 'HARAMIDERESANAYISITESI' kisa olan
        # 'HARAMIDERE'ye degil 'HARAMIDERESANAYI'ye oturmali.
        for rn in sorted(route_norm, key=len, reverse=True):
            if key and (rn.startswith(key) or key.startswith(rn)):
                hit = rn
                break
    if hit:
        matched[st] = hit
    else:
        unmatched.append(st)

# koridor sirasina diz (bati -> dogu)
ordered_stations = []
for rn_norm, rn in ((norm(n), n) for n in route_names):
    for st, hit in matched.items():
        if hit == rn_norm and st not in ordered_stations:
            ordered_stations.append(st)

print("eslesen:", len(ordered_stations), "/", len(pivot.index))
if unmatched:
    print("ESLESMEYEN:", unmatched)

M = pivot.loc[ordered_stations].values.astype(float)
# Ekranda kisaltilacak uzun adlar
SHORT = {
    "Bayrampaşa - Maltepe / Koç Üniversitesi Hastanesi": "Bayrampaşa - Maltepe",
    "Büyükşehir Belediyesi Sosyal Tesisleri": "İBB Sosyal Tesisler",
    "Okmeydanı Hastane Metrobüs durağı": "Okmeydanı Hastane",
    "Avcılar Merkez-Üniversite Kampüsü": "Avcılar Merkez-Ünv.",
    "Topkapı - Şehit Mustafa Cambaz": "Topkapı",
}
labels = [SHORT.get(route_norm[matched[st]], route_norm[matched[st]])
          for st in ordered_stations]
hours = np.arange(24)

# ── stil ─────────────────────────────────────────────────────────────
INK, INK2, LINE = "#1F2933", "#5B6470", "#D7DDE4"
BLUE = "#2962 9C".replace(" ", "")
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "text.color": INK, "axes.edgecolor": LINE,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
})

fig = plt.figure(figsize=(15, 13.5), facecolor="white")
gs = gridspec.GridSpec(
    2, 3, width_ratios=[10, 2.2, 0.28], height_ratios=[1.6, 10],
    wspace=0.03, hspace=0.03,
    left=0.19, right=0.93, top=0.90, bottom=0.05,
)
ax_top  = fig.add_subplot(gs[0, 0])
ax_hm   = fig.add_subplot(gs[1, 0])
ax_bar  = fig.add_subplot(gs[1, 1], sharey=ax_hm)
ax_cb   = fig.add_subplot(gs[1, 2])

# ── isi haritasi ─────────────────────────────────────────────────────
vmax = np.percentile(M[M > 0], 98)
norm_ = PowerNorm(gamma=0.55, vmin=0, vmax=vmax)
im = ax_hm.imshow(M, aspect="auto", cmap="Blues", norm=norm_,
                  interpolation="nearest")
ax_hm.set_yticks(range(len(labels)))
ax_hm.set_yticklabels(labels, fontsize=9.5)
ax_hm.set_xticks(range(0, 24, 2))
ax_hm.set_xticklabels([f"{h:02d}" for h in range(0, 24, 2)], fontsize=10)
ax_hm.set_xlabel("Saat", fontsize=11)
for sp in ax_hm.spines.values():
    sp.set_visible(False)
ax_hm.tick_params(length=0)

# zirve saat kolonlarini isaretle (recessive)
for h in (8, 18):
    ax_hm.axvline(h, color="white", lw=0.0)
    ax_hm.annotate("▲", xy=(h, len(labels) - 0.2), xytext=(h, len(labels) + 0.9),
                   ha="center", fontsize=9, color=INK2,
                   annotation_clip=False)

# ── ust marjinal: sistem saatlik profili ─────────────────────────────
tot = M.sum(axis=0)
ax_top.fill_between(hours, tot, color="#B8CFE8", alpha=0.85, zorder=2)
ax_top.plot(hours, tot, color=BLUE, lw=2, zorder=3)
peak_h = int(tot.argmax())
ax_top.annotate(f"zirve {peak_h:02d}:00 — {tot.max():,.0f} yolcu/sa".replace(",", "."),
                xy=(peak_h, tot.max()), xytext=(peak_h - 7.2, tot.max() * 0.86),
                fontsize=10, color=INK,
                arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
ax_top.set_xlim(ax_hm.get_xlim())
ax_top.set_xticks([])
ax_top.set_yticks([])
for sp in ax_top.spines.values():
    sp.set_visible(False)
ax_top.set_ylabel("Sistem\ntoplamı", fontsize=9.5, rotation=0, ha="right",
                  va="center", color=INK2)

# ── sag marjinal: durak gunluk toplami ───────────────────────────────
daily = M.sum(axis=1)
ax_bar.barh(range(len(labels)), daily, height=0.62, color="#7FA8D4",
            edgecolor="white", linewidth=0.6, zorder=2)
top3 = np.argsort(daily)[-3:]
for i in top3:
    ax_bar.text(daily[i] + daily.max() * 0.02, i, f"{daily[i]/1000:.1f}k",
                va="center", fontsize=8.5, color=INK)
ax_bar.set_xlim(0, daily.max() * 1.30)   # etiketler kesilmesin
ax_bar.set_xticks([])
ax_bar.tick_params(axis="y", length=0, labelleft=False)
for sp in ax_bar.spines.values():
    sp.set_visible(False)
ax_bar.set_title("Günlük giriş", fontsize=9.5, color=INK2, pad=4)
ax_bar.invert_yaxis() if False else None
ax_bar.margins(y=0)

# ── renk cubugu ──────────────────────────────────────────────────────
cb = fig.colorbar(im, cax=ax_cb)
cb.outline.set_visible(False)
cb.set_label("yolcu / saat (hafta içi ort.)", fontsize=9.5, color=INK2)
cb.ax.tick_params(labelsize=8.5, length=0, color=INK2)

# ── baslik / kaynak ──────────────────────────────────────────────────
fig.text(0.19, 0.965, "Metrobüs durak yoğunluğu — saat saat",
         fontsize=19, fontweight="bold", color=INK)
fig.text(0.19, 0.935,
         "İstasyon turnike girişleri, hafta içi ortalaması · duraklar koridor "
         "sırasında (üst: Beylikdüzü → alt: Söğütlüçeşme) · ▲ zirve saatler",
         fontsize=11, color=INK2)
fig.text(0.19, 0.015,
         "Kaynak: İBB Açık Veri Portalı — Saatlik Toplu Ulaşım Veri Seti "
         "(BELBİM), Ekim 2024 · data.ibb.gov.tr",
         fontsize=9, color=INK2)

out = "data_ibb/metrobus_yogunluk_ekim2024.png"
fig.savefig(out, dpi=180, facecolor="white")
print("OK:", out)
