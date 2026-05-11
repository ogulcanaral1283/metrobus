"""
Katman 1 — Headway Dinamiği Modeli
===================================

Otobüsler arası zaman headway'ini diferansiyel denklem sistemi olarak modeller.

Temel ODE:
    ḣ_i(t) = v_{i-1}(t) − v_i(t) + α · w_i(t)

burada:
    h_i   : i. araç ile öndeki (i-1). araç arasındaki zaman headway (sn)
    v_i   : i. aracın hızı (m/s)
    w_i   : durak pertürbasyonu — boarding/alighting kaynaklı gecikme etkisi
    α     : pertürbasyon katsayısı (durak yoğunluğuna bağlı, tipik: 0.2–0.5)

Zaman headway (sn) = mesafe_gap / hız formülasyonu kullanılır.
Mesafe bazlı gap'in aksine, zaman headway hıza duyarsızdır ve
doğrudan yolcu bekleme süresiyle ilişkilidir.

Lineerleştirme:
    h eşit dağılım denge noktası civarında lineerleştirme:
    δḣ_i = -δv_i + δv_{i-1}
    Transfer fonksiyonu: G(s) = 1 / (s + α)

Bu modül stabilite analizi (Bode, Nyquist) için transfer fonksiyonu
parametrelerini de sağlar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

try:
    from ..config import SimVehicle
except ImportError:
    from config import SimVehicle


@dataclass
class HeadwayState:
    """Bir aracın headway durumu."""
    vehicle_id: int
    time_headway: float         # öndeki araca zaman headway (sn)
    distance_headway: float     # öndeki araca mesafe gap (m)
    headway_error: float        # h_target - h_i (sn), pozitif = çok uzak
    headway_derivative: float   # ḣ_i — headway değişim hızı (sn/sn)


class HeadwayModel:
    """
    Headway dinamiği ODE sistemi.

    Tüm filoyu gözlemler, her araç çifti için zaman headway,
    hata (error) ve türev (derivative) hesaplar.

    Parametreler:
        route_length:       Hat uzunluğu (m)
        num_vehicles:       Araç sayısı
        cruise_speed:       Ortalama seyir hızı (m/s) — h_target hesabı için
        perturbation_alpha: Durak pertürbasyon katsayısı α
        vehicle_length:     Araç boyu (m) — gap hesabında çıkarılır
    """

    def __init__(
        self,
        route_length: float,
        num_vehicles: int,
        cruise_speed: float = 10.0,
        perturbation_alpha: float = 0.3,
        vehicle_length: float = 20.0,
    ):
        self.route_length = route_length
        self.num_vehicles = num_vehicles
        self.cruise_speed = cruise_speed
        self.alpha = perturbation_alpha
        self.vehicle_length = vehicle_length

        # Hedef zaman headway: eşit dağılım
        # h* = L / (N · v_cruise)
        # Örnek: 25000m / (15 × 10 m/s) = 166.7 sn ≈ 2.8 dk
        self.target_headway = route_length / (num_vehicles * cruise_speed)

        # Önceki headway değerleri (derivative hesabı için)
        self._prev_headways: dict[int, float] = {}

    @property
    def target_headway_minutes(self) -> float:
        """Hedef headway dakika cinsinden."""
        return self.target_headway / 60.0

    def update_target(self, num_vehicles: int | None = None,
                      cruise_speed: float | None = None) -> None:
        """Araç sayısı veya seyir hızı değiştiğinde hedefi güncelle."""
        if num_vehicles is not None:
            self.num_vehicles = num_vehicles
        if cruise_speed is not None:
            self.cruise_speed = cruise_speed
        self.target_headway = self.route_length / (
            self.num_vehicles * self.cruise_speed
        )

    def compute(
        self,
        vehicles: List[SimVehicle],
        dt: float = 0.1,
    ) -> List[HeadwayState]:
        """
        Tüm araçlar için headway durumunu hesapla.

        Araçlar pozisyona göre sıralanır (en küçük → en büyük).
        Her araç i, önündeki araç (i-1) ile arasındaki headway'i ölçer.
        İlk araç (en arkadaki) circular headway hesaplar.

        Args:
            vehicles: Tüm araçlar listesi
            dt:       Zaman adımı (sn) — derivative hesabı için

        Returns:
            Her araç için HeadwayState listesi (orijinal sırada)
        """
        if len(vehicles) < 2:
            return [
                HeadwayState(
                    vehicle_id=v.id,
                    time_headway=self.target_headway,
                    distance_headway=self.route_length,
                    headway_error=0.0,
                    headway_derivative=0.0,
                )
                for v in vehicles
            ]

        # Pozisyona göre sırala (küçükten büyüğe)
        sorted_vehicles = sorted(vehicles, key=lambda v: v.position_meters)

        # Her araç için headway hesapla
        headway_map: dict[int, HeadwayState] = {}

        for i, veh in enumerate(sorted_vehicles):
            n = len(sorted_vehicles)
            if i == n - 1:
                # En öndeki araç — circular headway (en arkadakine bakarak)
                # Forward gap: hat sonuna kalan + ilk aracın pozisyonu
                next_veh = sorted_vehicles[0]
                distance_gap = (
                    (self.route_length - veh.position_meters)
                    + next_veh.position_meters
                    - self.vehicle_length
                )
            else:
                # Normal: öndeki araçla forward gap
                next_veh = sorted_vehicles[i + 1]
                distance_gap = (
                    next_veh.position_meters
                    - veh.position_meters
                    - self.vehicle_length
                )

            distance_gap = max(distance_gap, 1.0)  # sıfır bölme koruması

            # Zaman headway = mesafe / hız
            # Araç durmuşsa, mevcut hız yerine cruise hızını kullan
            # (durmuş araçta h → ∞ olmasını engelle)
            effective_speed = max(veh.speed, 1.0)
            time_headway = distance_gap / effective_speed

            # Headway hatası: pozitif = çok uzak (hızlan), negatif = çok yakın (yavaşla/tut)
            headway_error = self.target_headway - time_headway

            # Headway türevi: ḣ_i = v_{i-1} - v_i + α · w_i
            # v_{i-1} = öndeki aracın hızı
            # w_i: araç duraktaysa pertürbasyon pozitif (headway büyüyor)
            perturbation = 0.0
            if veh.phase in ("stopped", "doorsClosed", "blocked", "queued"):
                perturbation = 1.0  # durakta bekleme → headway artıyor
            elif veh.phase == "departing":
                perturbation = -0.5  # kalkış → headway azalıyor

            leader_speed = next_veh.speed
            headway_dot = (
                leader_speed - veh.speed
                + self.alpha * perturbation
            )

            # Numerik türev ile doğrulama (smoothing)
            prev_h = self._prev_headways.get(veh.id, time_headway)
            numerical_derivative = (time_headway - prev_h) / max(dt, 1e-6)

            # ODE türevi ile numerik türevin ağırlıklı ortalaması
            # (gürültü filtreleme)
            blended_derivative = 0.7 * headway_dot + 0.3 * numerical_derivative

            headway_map[veh.id] = HeadwayState(
                vehicle_id=veh.id,
                time_headway=time_headway,
                distance_headway=distance_gap,
                headway_error=headway_error,
                headway_derivative=blended_derivative,
            )

            # Önceki headway güncelle
            self._prev_headways[veh.id] = time_headway

        # Orijinal sırada döndür
        return [headway_map[v.id] for v in vehicles]

    def compute_fleet_metrics(
        self,
        states: List[HeadwayState],
    ) -> dict:
        """
        Filo genelinde headway metrikleri.

        Returns:
            mean_headway:  Ortalama headway (sn)
            std_headway:   Standart sapma (sn)
            cv:            Varyasyon katsayısı (σ/μ) — 0 = mükemmel, >0.3 = kötü
            max_deviation: En büyük hedeften sapma (sn)
            bunching_pairs: Headway < h_target/3 olan çift sayısı
        """
        if not states:
            return {
                "mean_headway": 0.0,
                "std_headway": 0.0,
                "cv": 0.0,
                "max_deviation": 0.0,
                "bunching_pairs": 0,
            }

        headways = [s.time_headway for s in states]
        n = len(headways)

        mean_h = sum(headways) / n
        variance = sum((h - mean_h) ** 2 for h in headways) / n
        std_h = math.sqrt(variance)
        cv = std_h / max(mean_h, 1e-6)

        max_dev = max(abs(s.headway_error) for s in states)

        # Bunching: headway < h_target/3 (ciddi yığılma)
        bunching_threshold = self.target_headway / 3.0
        bunching_pairs = sum(1 for h in headways if h < bunching_threshold)

        return {
            "mean_headway": mean_h,
            "std_headway": std_h,
            "cv": cv,
            "max_deviation": max_dev,
            "bunching_pairs": bunching_pairs,
        }

    def get_transfer_function_params(self) -> dict:
        """
        Lineerleştirilmiş sistem transfer fonksiyonu parametreleri.

        ODE: δḣ_i = -δv_i + δv_{i-1} + α·w_i
        Denge noktası civarında: G(s) = 1 / (s + α)

        Kutup: s = -α (kararlı, α > 0 olduğu sürece)
        Zaman sabiti: τ = 1/α

        Returns:
            pole:          Kutup konumu (-α)
            time_constant: Zaman sabiti (1/α sn)
            dc_gain:       DC kazanç (1/α)
            stable:        Kararlı mı (α > 0)
        """
        return {
            "pole": -self.alpha,
            "time_constant": 1.0 / max(self.alpha, 1e-6),
            "dc_gain": 1.0 / max(self.alpha, 1e-6),
            "stable": self.alpha > 0,
        }

    def reset(self) -> None:
        """Episode başında türev state'ini sıfırla."""
        self._prev_headways.clear()
