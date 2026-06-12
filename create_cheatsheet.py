"""
Metrobus Karar Motoru — Tek Sayfalik Formul Cheat-Sheet
Calistir: python create_cheatsheet.py
Cikti: Metrobus_Formul_CheatSheet.pdf  (+ .png onizleme)
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Renkler (sunumla ayni tema) ──────────────────────────────────
C_BG      = "#0F172A"
C_ACCENT  = "#00B4D8"
C_FORMULA = "#90E0EF"
C_GRAY    = "#AABBCC"
C_GREEN   = "#06D6A0"
C_YELLOW  = "#FFD166"
C_WHITE   = "#FFFFFF"

# ── Bloklar: (no, baslik, renk, [formul_satirlari], aciklama) ────
# formul satiri: (metin, is_math)
LEFT = [
    ("1", "Etkin Mesafe", C_ACCENT,
     [(r"$d_{eff} = d - v \cdot 7.5$", True)],
     "Komut ~7.5 s sonra islenir; otobus o ana dek ilerler."),

    ("2", "Varis Suresi (ETA)", C_ACCENT,
     [(r"$v_{in}=\min(v,\ \sqrt{2\cdot 3.5\cdot 150})$", True),
      (r"$ETA=(d-150)/v \ +\ 150/(v_{in}/2)$", True)],
     "Serbest seyir + son 150 m frenleme egrisi."),

    ("3", "Slot Bosalma Zamani", C_ACCENT,
     [("durakta: dwell_kalan + 4      bos slot: 0", False),
      ("kapi: dwell_kalan + 2    docking: 2+dwell+4", False)],
     "+4 = kapi kapanma + kalkis suresi."),

    ("4", "Ideal Varis Zamani", C_ACCENT,
     [(r"$t_{ideal}=\min(t_{free})+2$", True)],
     "En erken bosalan slot + 2 s guvenlik tamponu."),

    ("5", "Erisilebilir Bos Slot", C_ACCENT,
     [(r"$n_{free}=\lfloor s_{rear}/25 \rfloor$", True)],
     "Perona arkadan giris; ondeki bos slot ulasilamaz."),

    ("6", "Bekleme Suresi", C_ACCENT,
     [(r"$q = t_{ideal} - ETA$", True)],
     "Mudahalesiz durakta bekleyecegi sure."),
]

RIGHT = [
    ("7", "Maliyet-Fayda  (KARAR)", C_GREEN,
     [(r"$C = q\cdot N\cdot 0.7 + P_{down}\cdot 8$", True),
      (r"$net = C - q \quad\Rightarrow\quad net>0:\ yavasla$", True)],
     "Zincirleme tikanma maliyeti > yavaslama maliyeti -> yavaslat."),

    ("8", "Komsu Durak Baskisi", C_ACCENT,
     [(r"$P_{down}=c_{s+1}\cdot 1.0 + c_{s+2}\cdot 0.6$", True)],
     "Ileri duraklar dolu ise baski artar; uzak az etkili."),

    ("9", "Hiz Carpani", C_YELLOW,
     [(r"$v_{need}=(d_{eff}-d_{br})/(t_{need}-t_{br})$", True),
      (r"$\lambda=\mathrm{clamp}(v_{need}/v_{max},\ 0.3,\ 1.0)$", True)],
     "Ideal zamanda varmak icin gereken seyir hizi (maks tam hiz)."),

    ("10", "Surucu Bandi", C_YELLOW,
     [(r"$band=[\ \lambda\cdot 90 - 5,\ \ \lambda\cdot 90 + 5\ ]$", True)],
     "Carpan -> '60-70 km/h tut' (5'e yuvarlanir)."),

    ("11", "Band Yumusatma (EMA)", C_ACCENT,
     [(r"$\alpha = dt/(2.5+dt)$", True),
      (r"$ema = ema + \alpha\,(v_{need}-ema)$", True)],
     "Min-hold 8 s; >8 km/h sapmada yenilenir (titreme 171->2)."),

    ("12", "Dwell Suresi", C_ACCENT,
     [(r"$dwell=\min(30,\ 15-\theta\ln(1-u))$", True),
      (r"$E[dwell]=15+\theta(1-e^{-15/\theta})$", True)],
     "Saha: 15-30 s, ort ~18, saga carpik (theta~4)."),
]


def draw_block(ax, x, y, num, title, color, formulas, expl):
    """Blogu ciz, bir sonraki blok icin uygun ust-y degerini dondur."""
    # accent tick
    ax.add_patch(plt.Rectangle((x - 0.012, y - 0.026), 0.006, 0.026,
                               transform=ax.transAxes, color=color, clip_on=False))
    ax.text(x, y, f"{num}.  {title}", transform=ax.transAxes,
            color=color, fontsize=11.5, weight="bold", va="top")
    yy = y - 0.042
    for txt, is_math in formulas:
        ax.text(x + 0.012, yy, txt, transform=ax.transAxes,
                color=C_FORMULA, fontsize=11.5 if is_math else 9.5,
                family=None if is_math else "monospace", va="top")
        yy -= 0.032
    ax.text(x + 0.012, yy + 0.003, expl, transform=ax.transAxes,
            color=C_GRAY, fontsize=8.5, va="top")
    bottom = yy - 0.024
    return bottom - 0.016   # blok arasi bosluk


def main():
    fig = plt.figure(figsize=(13.33, 9.3))
    fig.patch.set_facecolor(C_BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(C_BG)
    ax.axis("off")

    # Baslik
    ax.text(0.035, 0.97, "Metrobus Karar Motoru — Formul Ozeti",
            transform=ax.transAxes, color=C_WHITE, fontsize=20, weight="bold", va="top")
    ax.text(0.035, 0.925, "Her tick, her arac icin calisan 12 adimlik hesap zinciri  "
                          "(analitik / deterministik — ML yok)",
            transform=ax.transAxes, color=C_GRAY, fontsize=11, va="top")
    ax.add_patch(plt.Rectangle((0.035, 0.905), 0.93, 0.004,
                               transform=ax.transAxes, color=C_ACCENT, clip_on=False))

    # Sutunlar — dinamik istifleme (blok yuksekligi formul sayisina gore degisir)
    TOP_Y = 0.86
    y = TOP_Y
    for num, title, color, formulas, expl in LEFT:
        y = draw_block(ax, 0.05, y, num, title, color, formulas, expl)
    y = TOP_Y
    for num, title, color, formulas, expl in RIGHT:
        y = draw_block(ax, 0.53, y, num, title, color, formulas, expl)

    # Alt sabitler serisi
    consts = ("Sabitler:  gecikme butcesi 7.5 s   |   approach 150 m   |   konfor fren 3.5 m/s^2   |   "
              "slot 25 m   |   max hiz 90 km/h   |   cascade 0.7   |   downstream 8   |   band 10 km/h")
    ax.text(0.035, 0.075, consts, transform=ax.transAxes,
            color=C_YELLOW, fontsize=9.0, va="top")
    ax.add_patch(plt.Rectangle((0.035, 0.055), 0.93, 0.003,
                               transform=ax.transAxes, color="#1E3A4A", clip_on=False))
    ax.text(0.035, 0.04, "Karar: net_benefit > 0  ->  YAVASLA  (band duser)   |   risk gecince band tam hiza tirmanir (HIZLAN)",
            transform=ax.transAxes, color=C_GREEN, fontsize=9.5, weight="bold", va="top")

    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    fig.savefig("Metrobus_Formul_CheatSheet.pdf", facecolor=C_BG, bbox_inches=None)
    fig.savefig("Metrobus_Formul_CheatSheet.png", dpi=150, facecolor=C_BG)
    plt.close(fig)
    print("Kaydedildi: Metrobus_Formul_CheatSheet.pdf  ve  .png")


if __name__ == "__main__":
    main()
