"""
PID Kazanç Türetme — Ziegler-Nichols + Pole Placement
=========================================================

Headway ODE'nin step response'unu simüle ederek PID kazançlarını
otomatik olarak türetir.

Ziegler-Nichols Yöntemi:
    1. Ki = Kd = 0, sadece Kp ile sistemi çalıştır
    2. Kp'yi artır → sürekli osilasyon elde et
    3. Bu noktada: K_u = kritik kazanç, T_u = osilasyon periyodu
    4. PID kazançları:
        Kp = 0.6 · K_u
        Ki = Kp / (0.5 · T_u)
        Kd = Kp · 0.125 · T_u

Pole Placement Yöntemi:
    Transfer fonksiyonu G(s) = 1/(s + α) biliniyor.
    İstenilen kutup konumlarına göre PID kazançları hesaplanır.

    Kapalı döngü:
        T(s) = C(s)·G(s) / [1 + C(s)·G(s)]
        C(s) = Kp + Ki/s + Kd·s  (PID transfer fonksiyonu)

    İstenilen kapalı döngü bandwidth ω_n ve sönüm oranı ζ ile:
        s² + 2ζω_n·s + ω_n² = 0

Bu modül her iki yöntemi de uygular ve karşılaştırır.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple, Optional


@dataclass
class TuningResult:
    """Kazanç türetme sonucu."""
    kp: float
    ki: float
    kd: float
    method: str                     # "ziegler_nichols" | "pole_placement"
    critical_gain: float = 0.0      # K_u (ZN için)
    oscillation_period: float = 0.0 # T_u (ZN için)
    bandwidth: float = 0.0         # ω_n (PP için)
    damping_ratio: float = 0.0    # ζ (PP için)
    notes: str = ""


def ziegler_nichols(
    alpha: float,
    target_headway: float,
    dt: float = 0.1,
    sim_steps: int = 5000,
) -> TuningResult:
    """
    Ziegler-Nichols kritik kazanç yöntemiyle PID kazançlarını türet.

    Headway ODE:  ḣ = -v_error + α·w
    Kapalı döngü: e = h_target - h, u = Kp·e (P-only)

    Simülasyon ile K_u ve T_u bulunur.

    Args:
        alpha:          Pertürbasyon katsayısı
        target_headway: Hedef headway (sn)
        dt:             Zaman adımı (sn)
        sim_steps:      Simülasyon adım sayısı

    Returns:
        TuningResult — ZN kazançları
    """
    # ─── K_u arama: binary search ───
    # P-only kontrolcüyle osilasyon noktasını bul
    kp_low, kp_high = 0.01, 10.0
    k_u = 0.0
    t_u = 0.0

    for _ in range(30):  # binary search iterasyonları
        kp_test = (kp_low + kp_high) / 2.0
        oscillates, period = _simulate_p_only(
            kp_test, alpha, target_headway, dt, sim_steps,
        )

        if oscillates:
            k_u = kp_test
            t_u = period
            kp_high = kp_test  # daha düşük Kp dene
        else:
            kp_low = kp_test  # daha yüksek Kp dene

    if k_u < 0.01:
        # Osilasyon bulunamadı — varsayılan değerler
        return TuningResult(
            kp=0.4, ki=0.02, kd=0.15,
            method="ziegler_nichols",
            notes="Osilasyon noktası bulunamadı, varsayılan değerler kullanıldı.",
        )

    # ─── ZN formülleri ───
    kp = 0.6 * k_u
    ki = kp / (0.5 * t_u) if t_u > 0 else 0.0
    kd = kp * 0.125 * t_u

    return TuningResult(
        kp=kp, ki=ki, kd=kd,
        method="ziegler_nichols",
        critical_gain=k_u,
        oscillation_period=t_u,
        notes=f"K_u={k_u:.4f}, T_u={t_u:.2f}s",
    )


def pole_placement(
    alpha: float,
    target_headway: float,
    bandwidth: float = 0.05,
    damping_ratio: float = 0.7,
) -> TuningResult:
    """
    Pole placement ile PID kazançlarını türet.

    Açık döngü: G(s) = 1 / (s + α)
    PID: C(s) = Kp + Ki/s + Kd·s
    Kapalı döngü: T(s) = C(s)G(s) / [1 + C(s)G(s)]

    İstenilen kapalı döngü kutupları:
        s = -ζω_n ± jω_n√(1-ζ²)

    Karakteristik polinom eşleştirmesi:
        s² + (α + Kp + Kd·α)·s + (α·Kp + Ki) = ω_n²
        Karşılaştırma ile:
            2ζω_n = α + Kp + Kd·α
            ω_n²  = α·Kp + Ki

    İki denklem, üç bilinmeyen (Kp, Ki, Kd).
    Kd'yi serbest parametre olarak seçeriz:
        Kd = (2ζω_n - α) / (α + 1) — heuristik paylaştırma

    Args:
        alpha:        Pertürbasyon katsayısı
        target_headway: Hedef headway (referans, normalize için)
        bandwidth:    İstenilen kapalı döngü bandwidth ω_n (rad/s)
        damping_ratio: İstenilen sönüm oranı ζ (0.7 = kritik altı, iyi sönüm)

    Returns:
        TuningResult — pole placement kazançları
    """
    omega_n = bandwidth
    zeta = damping_ratio

    # Kd türetme (heuristik: toplam sönümün %25'i derivative'den)
    total_damping = 2.0 * zeta * omega_n
    kd = max(0.0, (total_damping - alpha) * 0.25)

    # Kp türetme
    # 2ζω_n = α + Kp + Kd·α → Kp = 2ζω_n - α - Kd·α
    kp = max(0.01, total_damping - alpha - kd * alpha)

    # Ki türetme
    # ω_n² = α·Kp + Ki → Ki = ω_n² - α·Kp
    ki = max(0.0, omega_n ** 2 - alpha * kp)

    return TuningResult(
        kp=kp, ki=ki, kd=kd,
        method="pole_placement",
        bandwidth=omega_n,
        damping_ratio=zeta,
        notes=f"ω_n={omega_n:.4f} rad/s, ζ={zeta:.2f}",
    )


def auto_tune(
    alpha: float,
    target_headway: float,
    dt: float = 0.1,
) -> TuningResult:
    """
    Otomatik kazanç seçimi — iki yöntemi karşılaştır, daha stabil olanı seç.

    Bandwidth seçimi:
        ω_n ≈ 2π / (10 · h_target)
        Gerekçe: Kapalı döngü hedef headway'in 1/10'u kadar hızlı tepki vermeli.
        Çok hızlı → agresif, çok yavaş → bunching'e geç tepki.
    """
    # ZN
    zn_result = ziegler_nichols(alpha, target_headway, dt)

    # Pole Placement
    omega_n = 2.0 * math.pi / (10.0 * max(target_headway, 10.0))
    pp_result = pole_placement(alpha, target_headway, omega_n, 0.7)

    # Karşılaştırma: ZN genelde agresif, PP daha yumuşak.
    # Metrobüs sistemi için PP tercih edilir (konfor + stabilite).
    # Ama ZN geçerliyse kontrol et.
    if zn_result.critical_gain > 0 and zn_result.kp > 0:
        # İkisini karşılaştır — daha düşük Kp olanı seç (konservatif)
        if pp_result.kp < zn_result.kp:
            pp_result.notes += f" | ZN alt: Kp={zn_result.kp:.4f}"
            return pp_result
        else:
            zn_result.notes += f" | PP alt: Kp={pp_result.kp:.4f}"
            return zn_result

    return pp_result


def _simulate_p_only(
    kp: float,
    alpha: float,
    target_headway: float,
    dt: float,
    steps: int,
) -> Tuple[bool, float]:
    """
    P-only kontrolcü ile headway simülasyonu.

    Returns:
        (oscillates, period)
        oscillates: Son %50'de sürekli osilasyon var mı
        period: Osilasyon periyodu (sn)
    """
    h = target_headway * 1.2  # başlangıç: hedefin %20 üstü
    errors = []

    for step in range(steps):
        error = target_headway - h
        u = kp * (-error)  # u > 0 → headway'i artır (yavaşla)

        # ODE: ḣ = -u_effect + α·perturbation
        # u: hold time → headway'i artırır (u/target_headway normalize)
        dh = -u * 0.1 + alpha * 0.0  # pertürbasyon yok (clean test)
        h += dh * dt
        h = max(1.0, h)  # headway negatif olamaz

        errors.append(error)

    # Son yarıdaki osilasyonu kontrol et
    second_half = errors[len(errors) // 2:]
    if len(second_half) < 10:
        return False, 0.0

    # İşaret değişikliği say
    sign_changes = 0
    for i in range(1, len(second_half)):
        if second_half[i] * second_half[i - 1] < 0:
            sign_changes += 1

    # En az 4 işaret değişikliği = osilasyon
    oscillates = sign_changes >= 4

    # Periyot tahmini
    period = 0.0
    if sign_changes > 1:
        total_time = len(second_half) * dt
        period = 2.0 * total_time / sign_changes  # yarım periyot × 2

    return oscillates, period
