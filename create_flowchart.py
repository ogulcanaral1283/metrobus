"""
Metrobus Karar Motoru — Kosullu Karar Agaci (akis semasi)
Calistir: python create_flowchart.py
Cikti: Metrobus_Karar_Agaci.pdf  (+ .png onizleme)
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

# ── Renkler (sunumla ayni tema) ──────────────────────────────────
C_BG      = "#0F172A"
C_ACCENT  = "#00B4D8"
C_CYAN    = "#90E0EF"
C_BOX     = "#15233B"   # islem kutusu dolgu
C_GRAYTX  = "#AABBCC"
C_GREEN   = "#06D6A0"
C_YELLOW  = "#FFD166"
C_WHITE   = "#FFFFFF"
C_EXIT    = "#1B2A3D"   # "dokunma" cikis kutusu dolgu
C_EXITEC  = "#3A4A5E"


def box(ax, cx, cy, w, h, text, fc, ec, tc, fs=11, weight="normal"):
    p = FancyBboxPatch((cx - w / 2, cy - h / 2), w, h,
                       boxstyle="round,pad=0.004,rounding_size=0.014",
                       transform=ax.transAxes, facecolor=fc, edgecolor=ec,
                       linewidth=2.2, clip_on=False, zorder=2)
    ax.add_patch(p)
    ax.text(cx, cy, text, transform=ax.transAxes, color=tc, fontsize=fs,
            weight=weight, ha="center", va="center", zorder=3, linespacing=1.25)
    return dict(cx=cx, cy=cy, t=cy + h / 2, b=cy - h / 2, l=cx - w / 2, r=cx + w / 2)


def arrow(ax, x1, y1, x2, y2, color=C_ACCENT, conn="arc3,rad=0", lw=2.4):
    a = FancyArrowPatch((x1, y1), (x2, y2), transform=ax.transAxes,
                        arrowstyle="-|>", mutation_scale=18, color=color, lw=lw,
                        connectionstyle=conn, clip_on=False, zorder=1)
    ax.add_patch(a)


def tag(ax, x, y, t, color):
    ax.text(x, y, t, transform=ax.transAxes, color=color, fontsize=10,
            weight="bold", ha="center", va="center", zorder=4,
            bbox=dict(boxstyle="round,pad=0.18", fc=C_BG, ec="none"))


def main():
    fig = plt.figure(figsize=(13.33, 9.3))
    fig.patch.set_facecolor(C_BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(C_BG)
    ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    # ── Baslik ───────────────────────────────────────────────────
    ax.text(0.035, 0.965, "Karar Agaci — Bir Otobus Icin Tek Tur",
            color=C_WHITE, fontsize=21, weight="bold", va="top")
    ax.text(0.035, 0.922,
            "Her durak, bolgesindeki her otobus icin, saniyede 10 kez bu agaci calistirir. "
            "Cogu otobus ilk kapilarda 'sorun yok' diye gecer.",
            color=C_GRAYTX, fontsize=11.5, va="top")
    ax.add_patch(plt.Rectangle((0.035, 0.902), 0.93, 0.004, color=C_ACCENT, clip_on=False))

    SX, EX = 0.31, 0.74          # spine x, exit x
    WS, WE, H = 0.40, 0.30, 0.080

    # ── Kutular ──────────────────────────────────────────────────
    p0 = box(ax, SX, 0.855, WS, H,
             "Bolgedeki otobusler varis sirasina dizilir\n(en erken varan once islenir)",
             C_BOX, C_ACCENT, C_CYAN, 11)

    d1 = box(ax, SX, 0.730, WS, H,
             "Otobus cok mu yakin?\n(etkin mesafe < 30 m)",
             C_BOX, C_YELLOW, C_WHITE, 11.5, "bold")
    e1 = box(ax, EX, 0.730, WE, H,
             "DOKUNMA\n'too_close' — komut yetismez",
             C_EXIT, C_EXITEC, C_GRAYTX, 10)

    p2 = box(ax, SX, 0.605, WS, H,
             "Varis suresi (ETA) + en erken bos slot\n→ ideal varis zamani hesaplanir",
             C_BOX, C_ACCENT, C_CYAN, 11)

    d2 = box(ax, SX, 0.480, WS, H,
             "Slot bosalmadan mi gelecek?\n(ETA < ideal - 2 sn)",
             C_BOX, C_YELLOW, C_WHITE, 11.5, "bold")
    e2 = box(ax, EX, 0.480, WE, H,
             "DOKUNMA\n'on_time' — EN SIK durum",
             C_EXIT, C_EXITEC, C_GRAYTX, 10)

    p3 = box(ax, SX, 0.355, WS, H,
             "Bekleme suresi:  q = ideal - ETA",
             C_BOX, C_ACCENT, C_CYAN, 11.5)

    d3 = box(ax, SX, 0.230, WS, H,
             "KARAR: Tikanma maliyeti yavaslamadan pahali mi?\n"
             "net = zincir + komsu baski - q  > 0",
             C_BOX, C_GREEN, C_WHITE, 10.5, "bold")

    d4 = box(ax, SX, 0.110, WS, H,
             "Yine de uzun bekleme mi?  (q >= 2 sn)",
             C_BOX, C_YELLOW, C_WHITE, 11, "bold")
    e3 = box(ax, EX, 0.110, WE, H,
             "DOKUNMA\n'queue_cheaper' — kisa bekleme ucuz",
             C_EXIT, C_EXITEC, C_GRAYTX, 10)

    act = box(ax, 0.50, 0.035, 0.90, 0.066,
              "YAVASLA   →   hiz bandi uret   →   EMA ile yumusat   →   \"60-70 km/h tut\" komutu sofore",
              C_GREEN, C_GREEN, C_BG, 12.5, "bold")

    # ── Spine oklari ─────────────────────────────────────────────
    arrow(ax, SX, p0["b"], SX, d1["t"])
    arrow(ax, SX, d1["b"], SX, p2["t"]); tag(ax, SX, (d1["b"]+p2["t"])/2, "HAYIR", C_GRAYTX)
    arrow(ax, SX, p2["b"], SX, d2["t"])
    arrow(ax, SX, d2["b"], SX, p3["t"]); tag(ax, SX, (d2["b"]+p3["t"])/2, "EVET (erken)", C_CYAN)
    arrow(ax, SX, p3["b"], SX, d3["t"])
    arrow(ax, SX, d3["b"], SX, d4["t"]); tag(ax, SX, (d3["b"]+d4["t"])/2, "HAYIR", C_GRAYTX)
    arrow(ax, SX, d4["b"], 0.50, act["t"], color=C_GREEN)
    tag(ax, SX, (d4["b"]+act["t"])/2, "EVET", C_GREEN)

    # ── Cikis oklari (DOKUNMA) ───────────────────────────────────
    arrow(ax, d1["r"], d1["cy"], e1["l"], e1["cy"], color=C_EXITEC)
    tag(ax, (d1["r"]+e1["l"])/2, d1["cy"]+0.018, "EVET", C_GRAYTX)
    arrow(ax, d2["r"], d2["cy"], e2["l"], e2["cy"], color=C_EXITEC)
    tag(ax, (d2["r"]+e2["l"])/2, d2["cy"]+0.018, "HAYIR", C_GRAYTX)
    arrow(ax, d4["r"], d4["cy"], e3["l"], e3["cy"], color=C_EXITEC)
    tag(ax, (d4["r"]+e3["l"])/2, d4["cy"]+0.018, "HAYIR", C_GRAYTX)

    # ── KARAR 'EVET' kisa devre: d3 -> action (sol kavis) ────────
    arrow(ax, d3["l"], d3["cy"], 0.10, act["t"], color=C_GREEN,
          conn="arc3,rad=0.35")
    tag(ax, 0.085, 0.165, "EVET", C_GREEN)

    fig.savefig("Metrobus_Karar_Agaci.pdf", facecolor=C_BG)
    fig.savefig("Metrobus_Karar_Agaci.png", dpi=150, facecolor=C_BG)
    plt.close(fig)
    print("Kaydedildi: Metrobus_Karar_Agaci.pdf  ve  .png")


if __name__ == "__main__":
    main()
