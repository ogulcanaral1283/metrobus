"""
Analitik Motor — WebSocket Simülasyon Sunucusu
===============================================

Dashboard ile baglantı noktası. Analitik kontrol motorunu
real-time calistirip araç durumlarini WebSocket uzerinden
dashboard'a gonderir.

Kullanim:
    python sim_server.py

Dashboard'da "Analitik Motor" butonuna basildiginda
ws://localhost:8765 adresine baglanır.

Veri formati: SimState uyumlu JSON + kontrol metrikleri.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import time

# rl_env'i import edebilmek icin path ayarla
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np

from rl_env.config import SimConfig, SimVehicle, TrafficZone, DEFAULT_CONFIG, VEHICLE_LENGTH, DT
from rl_env.route_data import load_route, LinearStop
from rl_env.physics import compute_target_speed, update_vehicle_physics
from rl_env.station_fsm import update_station_fsm, compute_rear_free_slots, is_inside_platform_zone
from rl_env.traffic import update_traffic_zones
from rl_env.controller.headway_model import HeadwayModel
from rl_env.controller.pid_controller import PIDController
from rl_env.controller.control_merger import ControlMerger, ControlCommand

try:
    import websockets
except ImportError:
    print("[HATA] websockets paketi gerekli: pip install websockets")
    sys.exit(1)


# ============================================
# Metre -> Lat/Lng Donusumu
# ============================================

def _haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing(lat1, lon1, lat2, lon2):
    d_lon = math.radians(lon2 - lon1)
    y = math.sin(d_lon) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - \
        math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(d_lon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


class RouteGeometry:
    """Metre -> lat/lng cevirici. route_network.json segmentlerini kullanir."""

    def __init__(self, direction: str = "gidis"):
        data_path = os.path.join(os.path.dirname(__file__), "rl_env", "data", "route_network.json")
        with open(data_path, "r", encoding="utf-8") as f:
            rn = json.load(f)

        edges = rn["edges"][direction]
        self.segments = []
        cum = 0.0

        for edge in edges:
            geom = edge["geometry"]
            for pi in range(len(geom) - 1):
                lat1, lng1 = geom[pi]
                lat2, lng2 = geom[pi + 1]
                dist = _haversine(lat1, lng1, lat2, lng2)
                if dist < 0.1:
                    continue
                self.segments.append({
                    "start_meter": cum,
                    "end_meter": cum + dist,
                    "start_lat": lat1, "start_lng": lng1,
                    "end_lat": lat2, "end_lng": lng2,
                    "length": dist,
                    "bearing": _bearing(lat1, lng1, lat2, lng2),
                })
                cum += dist

        self.total_length = cum

    def meter_to_position(self, meter: float) -> dict:
        """Metre pozisyonundan lat/lng/heading hesapla (binary search)."""
        m = max(0.0, min(meter, self.total_length))
        if not self.segments:
            return {"latitude": 0.0, "longitude": 0.0, "heading": 0.0}

        # Binary search
        lo, hi = 0, len(self.segments) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self.segments[mid]["end_meter"] < m:
                lo = mid + 1
            else:
                hi = mid

        seg = self.segments[lo]
        t = (m - seg["start_meter"]) / max(seg["length"], 0.01)

        # Heading: mevcut ve sonraki segment arası yumuşak geçiş
        # Segment sonuna yaklaştıkça sonraki segment'in bearing'ine karış
        heading = seg["bearing"]
        if t > 0.5 and lo + 1 < len(self.segments):
            next_bearing = self.segments[lo + 1]["bearing"]
            # Açı farkını en kısa yoldan hesapla (0-360 wrap)
            diff = (next_bearing - heading + 540) % 360 - 180
            blend = (t - 0.5) * 2.0  # 0.5→1.0 arasında 0→1
            heading = (heading + diff * blend) % 360

        return {
            "latitude": seg["start_lat"] + t * (seg["end_lat"] - seg["start_lat"]),
            "longitude": seg["start_lng"] + t * (seg["end_lng"] - seg["start_lng"]),
            "heading": heading,
        }


# ============================================
# Simulasyon Yoneticisi
# ============================================

_VEHICLE_TYPE_JSON = {"brand": "Analitik", "model": "Motor", "lengthMeters": 20, "code": "AM"}


class SimManager:
    """Analitik motor simulasyonunu yonetir ve dashboard verisini uretir."""

    def __init__(
        self,
        vehicle_count: int = 15,
        direction: str = "gidis",
        start_hour: float = 7.0,
        seed: int = 42,
        time_scale: float = 5.0,
        pid_kp: float = 0.15,
        pid_ki: float = 0.005,
        pid_kd: float = 0.08,
    ):
        self.config = DEFAULT_CONFIG
        self.config.vehicle_count = vehicle_count
        self.direction = direction
        self.start_hour = start_hour
        self.time_scale = time_scale
        self.rng = np.random.default_rng(seed)
        self.dt = DT

        # Rota yukle
        self.route = load_route(direction)
        self.stops = self.route.stops
        self.route_length = self.route.total_length

        # Geometri cevirici
        self.geometry = RouteGeometry(direction)

        # Platform giris noktalarindan durak metre pozisyonlarini kalibre et
        self._calibrate_stops_to_platforms(direction)

        # Segment: sadece spawn ve wrap noktası değişir, fizik/durak listesi dokunulmaz
        self._seg_start_pos: float = 0.0          # Wrap sonrası spawn pozisyonu
        self._seg_end_threshold: float = float("inf")  # Bu pozisyonu geçince wrap
        self._seg_start_stop_idx: int = 0          # Wrap sonrası next_stop_index

        # Araclar
        self.vehicles = self._create_vehicles(vehicle_count)

        # Trafik
        self.traffic_zones = []

        # Zaman
        self.sim_time = 0.0
        self.step_count = 0
        self._last_commands: dict[int, ControlCommand] = {}

        # Kontrolcu
        cruise_speed = self.config.max_speed * 0.7
        self.headway_model = HeadwayModel(
            route_length=self.route_length,
            num_vehicles=vehicle_count,
            cruise_speed=cruise_speed,
            perturbation_alpha=0.3,
            vehicle_length=VEHICLE_LENGTH,
        )

        self.pid = PIDController(kp=pid_kp, ki=pid_ki, kd=pid_kd, dt=self.dt, u_max=60.0)

        # SmartStop tabanlı kontrol sistemi
        self.controller = ControlMerger(
            headway_model=self.headway_model,
            pid=self.pid,
            min_gap=25.0,
            vehicle_length=VEHICLE_LENGTH,
        )

    def _calibrate_stops_to_platforms(self, direction: str):
        """Platform giris noktalarini kullanarak durak metre pozisyonlarini kalibre et."""
        pe_path = os.path.join(
            os.path.dirname(__file__),
            "packages", "shared", "src", "constants", "platform-entries.ts",
        )
        if not os.path.exists(pe_path):
            print("[SIM] Platform entries bulunamadi, kalibrasyon atlanıyor")
            return

        # TS dosyasindan platform giris koordinatlarini parse et
        platform_entries = []
        with open(pe_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Basit regex ile parse
        import re
        blocks = re.findall(
            r'"name":\s*"([^"]+)".*?"length":\s*(\d+).*?'
            r'"gidis_lat":\s*([\d.]+).*?"gidis_lon":\s*([\d.]+).*?'
            r'"donus_lat":\s*([\d.]+).*?"donus_lon":\s*([\d.]+)',
            content, re.DOTALL,
        )
        for b in blocks:
            platform_entries.append({
                "name": b[0],
                "length": int(b[1]),
                "gidis_lat": float(b[2]),
                "gidis_lon": float(b[3]),
                "donus_lat": float(b[4]),
                "donus_lon": float(b[5]),
            })

        if not platform_entries:
            return

        # Her durak icin en yakin platform entry'yi bul ve metre pozisyonunu kalibre et
        def _normalize(name):
            replacements = {
                "ç": "c", "Ç": "C", "ğ": "g", "Ğ": "G",
                "ı": "i", "İ": "I", "ö": "o", "Ö": "O",
                "ş": "s", "Ş": "S", "ü": "u", "Ü": "U",
            }
            n = name.lower().strip()
            for old, new in replacements.items():
                n = n.replace(old, new)
            return n

        calibrated = 0
        for stop in self.stops:
            stop_norm = _normalize(stop.name)

            # Fuzzy match: platform entry isminin ilk kelimesi durak isminde geciyorsa
            best_pe = None
            best_score = 0
            for pe in platform_entries:
                pe_norm = _normalize(pe["name"])
                # Tam eslesme
                if pe_norm == stop_norm:
                    best_pe = pe
                    break
                # Ilk kelime eslesmesi
                pe_first = pe_norm.split()[0] if pe_norm else ""
                stop_first = stop_norm.split()[0] if stop_norm else ""
                if pe_first and stop_first and pe_first == stop_first and len(pe_first) > 3:
                    score = len(pe_first)
                    if score > best_score:
                        best_score = score
                        best_pe = pe

            if best_pe:
                # Gidis yonu -> TURUNCU top (donus giris noktasi)
                # Donus yonu -> MAVI top (gidis giris noktasi)
                if direction == "gidis":
                    lat, lng = best_pe["donus_lat"], best_pe["donus_lon"]
                else:
                    lat, lng = best_pe["gidis_lat"], best_pe["gidis_lon"]

                # Bu koordinati rota segmentine project et -> metre pozisyonu
                new_meter = self._project_to_route(lat, lng)
                if new_meter > 0:
                    stop.meter_position = new_meter
                    calibrated += 1

        # Siralamayı yeniden yap
        self.stops.sort(key=lambda s: s.meter_position)
        for i, s in enumerate(self.stops):
            s.index = i

        print(f"[SIM] Durak kalibrasyonu: {calibrated}/{len(self.stops)} durak platform'a hizalandi")

    def _project_to_route(self, lat: float, lng: float) -> float:
        """Bir lat/lng'yi rota segmentine project ederek metre pozisyonu bul."""
        best_dist = float("inf")
        best_meter = 0.0

        for seg in self.geometry.segments:
            # Segment üzerine projeksiyon
            dx = seg["end_lat"] - seg["start_lat"]
            dy = seg["end_lng"] - seg["start_lng"]
            len_sq = dx * dx + dy * dy
            if len_sq < 1e-12:
                continue

            t = ((lat - seg["start_lat"]) * dx + (lng - seg["start_lng"]) * dy) / len_sq
            t = max(0.0, min(1.0, t))

            proj_lat = seg["start_lat"] + t * (seg["end_lat"] - seg["start_lat"])
            proj_lng = seg["start_lng"] + t * (seg["end_lng"] - seg["start_lng"])
            d = _haversine(lat, lng, proj_lat, proj_lng)

            if d < best_dist:
                best_dist = d
                best_meter = seg["start_meter"] + t * seg["length"]

        return best_meter

    def _create_vehicles(self, count: int):
        gap = self.route_length / count
        vehicles = []
        for i in range(count):
            pos = i * gap
            vehicles.append(SimVehicle(
                id=i,
                position_meters=pos,
                speed=self.config.max_speed * 0.5,
                direction=self.direction,
            ))
        return vehicles

    def tick(self, dt_real: float):
        """Bir gercek-zaman tick. time_scale ile hizlandirilir."""
        steps = max(1, int(self.time_scale * dt_real / self.dt))
        for _ in range(min(steps, 20)):  # max 20 step/tick (yavaslama onlemi)
            self._step()

    def _step(self):
        dt = self.dt
        current_hour = self.start_hour + self.sim_time / 3600.0
        is_rush = 7.0 <= current_hour <= 9.5 or 17.0 <= current_hour <= 19.5

        # 1. Kontrolcu
        commands = {}
        cmd_list = self.controller.compute(
            self.vehicles, self.stops,
            dt=dt, is_rush_hour=is_rush, current_hour=current_hour,
        )
        for cmd in cmd_list:
            commands[cmd.vehicle_id] = cmd

        # Son komutlari sakla (dashboard icin)
        self._last_commands = commands

        # 2. Trafik
        self.traffic_zones = update_traffic_zones(
            self.traffic_zones, dt, self.route_length,
            self.config, is_rush, self.rng,
        )

        # 3. Fizik + FSM
        sorted_v = sorted(self.vehicles, key=lambda v: v.position_meters)
        last_stop_pos = self.stops[-1].meter_position if self.stops else self.route_length * 0.95
        # Segment aktifse segment sonunda, değilse rota sonunda wrap
        wrap_threshold = min(last_stop_pos + 100, self._seg_end_threshold)
        for veh in self.vehicles:
            cmd = commands.get(veh.id)
            if cmd:
                if cmd.hold_time > 0 and veh.phase in ("stopped", "doorsClosed"):
                    veh.holding_extra = max(veh.holding_extra, cmd.hold_time)
                if cmd.skip_stop:
                    veh.skip_next_stop = True

            target_speed = compute_target_speed(
                veh, self.config, self.stops,
                self.traffic_zones, self.route_length,
            )

            if cmd and cmd.speed_factor != 1.0:
                target_speed *= cmd.speed_factor

            leader = self._find_leader(veh, sorted_v)
            update_vehicle_physics(veh, dt, target_speed, leader, self.config, self.route_length)

            update_station_fsm(
                veh, dt, self.stops, self.config,
                is_rush_hour=is_rush,
                all_vehicles=self.vehicles,
                rng=self.rng,
                current_hour=current_hour,
            )

            # === Uçtan uca süre takibi ===
            # Kuyrukta bekleme süresi biriktir
            if veh.phase == "queued":
                veh.trip_total_queue_time += dt
            # Durakta durma süresi biriktir
            if veh.phase in ("stopped", "doorsClosed"):
                veh.trip_total_dwell_time += dt

            # Son duraga ulasan araci basa al (yeni sefer)
            if veh.position_meters >= wrap_threshold:
                # Sefer tamamlandı — metrikleri kaydet
                trip_duration = self.sim_time - veh.trip_start_time
                if trip_duration > 0:
                    veh.trip_last_duration = trip_duration
                    veh.trip_completed_count += 1

                veh.position_meters = self._seg_start_pos
                veh.speed = self.config.max_speed * 0.5
                veh.acceleration = 0.0
                veh.phase = "cruising"
                veh.next_stop_index = self._seg_start_stop_idx
                veh.dwell_remaining = 0.0
                veh.holding_extra = 0.0
                veh.skip_next_stop = False
                veh.is_queuing = False
                veh.queue_wait_time = 0.0
                # Yeni sefer başlat
                veh.trip_start_time = self.sim_time
                veh.trip_total_queue_time = 0.0
                veh.trip_total_dwell_time = 0.0

        self.sim_time += dt
        self.step_count += 1

    def _find_leader(self, vehicle, sorted_vehicles):
        best = None
        best_dist = float("inf")
        for v in sorted_vehicles:
            if v.id == vehicle.id:
                continue
            dist = v.position_meters - vehicle.position_meters
            if dist < 0:
                dist += self.route_length
            if 0 < dist < best_dist:
                best_dist = dist
                best = v
        return best

    def _compute_trip_metrics(self) -> dict:
        """Filo genelinde uçtan uca sefer metrikleri."""
        completed = [v for v in self.vehicles if v.trip_completed_count > 0]
        if not completed:
            return {
                "tripCount": 0,
                "tripAvgDuration": 0,
                "tripAvgQueueTime": 0,
                "tripAvgDwellTime": 0,
                "tripMinDuration": 0,
                "tripMaxDuration": 0,
            }

        durations = [v.trip_last_duration for v in completed]
        # Aktif seferlerin anlık kuyruk/dwell ortalaması
        all_queue = [v.trip_total_queue_time for v in self.vehicles]
        all_dwell = [v.trip_total_dwell_time for v in self.vehicles]

        return {
            "tripCount": sum(v.trip_completed_count for v in completed),
            "tripAvgDuration": round(sum(durations) / len(durations), 1),
            "tripAvgQueueTime": round(sum(all_queue) / len(all_queue), 1),
            "tripAvgDwellTime": round(sum(all_dwell) / len(all_dwell), 1),
            "tripMinDuration": round(min(durations), 1),
            "tripMaxDuration": round(max(durations), 1),
        }

    def add_vehicle(self):
        """Hatta yeni arac ekle — aktif segment/rota icindeki en buyuk bosa eklenir."""
        seg_active = self._seg_end_threshold < float("inf")
        seg_start = self._seg_start_pos
        seg_end = self._seg_end_threshold - 100  # buffer cikart
        effective_len = (seg_end - seg_start) if seg_active else self.route_length

        sorted_v = sorted(self.vehicles, key=lambda v: v.position_meters)
        # Segment aktifse sadece segment icindeki araclari kullan
        if seg_active:
            sorted_v = [v for v in sorted_v if seg_start <= v.position_meters <= seg_end]
        if not sorted_v:
            best_pos = seg_start + effective_len / 2
        else:
            best_pos = seg_start
            best_gap = 0.0
            for i in range(len(sorted_v)):
                nxt = sorted_v[(i + 1) % len(sorted_v)]
                gap = nxt.position_meters - sorted_v[i].position_meters
                if gap < 0:
                    gap += effective_len
                if gap > best_gap:
                    best_gap = gap
                    offset = (sorted_v[i].position_meters - seg_start + gap / 2) % effective_len
                    best_pos = seg_start + offset

        new_id = max(v.id for v in self.vehicles) + 1
        new_veh = SimVehicle(
            id=new_id,
            position_meters=best_pos,
            speed=self.config.max_speed * 0.3,
            direction=self.direction,
        )
        new_veh.next_stop_index = self._next_stop_idx_for_pos(best_pos)
        self.vehicles.append(new_veh)

        # Kontrolcu hedef guncelle
        self.headway_model.update_target(num_vehicles=len(self.vehicles))
        print(f"[SIM] Arac eklendi: #{new_id}, toplam: {len(self.vehicles)}")

    def remove_vehicle(self):
        """Hattan arac cikar — en sondaki cikarilir."""
        if len(self.vehicles) <= 3:
            return  # min 3 arac
        removed = self.vehicles.pop()
        # Dead state temizle (bellek sızıntısı önleme)
        self.pid.reset_vehicle(removed.id)
        self.headway_model._prev_headways.pop(removed.id, None)
        self.headway_model.update_target(num_vehicles=len(self.vehicles))
        print(f"[SIM] Arac cikarildi: #{removed.id}, kalan: {len(self.vehicles)}")

    def set_time_scale(self, scale: float):
        """Simulasyon hiz carpanini degistir."""
        self.time_scale = max(1.0, min(scale, 20.0))

    def set_vehicle_count(self, count: int):
        """Arac sayisini tam olarak ayarla (3-50 arasi)."""
        count = max(1, count)
        current = len(self.vehicles)
        if count == current:
            return

        if count > current:
            # Arac ekle
            for _ in range(count - current):
                self.add_vehicle()
        else:
            # Arac cikar — en sondakilerden
            while len(self.vehicles) > count and len(self.vehicles) > 3:
                removed = self.vehicles.pop()
                self.pid.reset_vehicle(removed.id)
                self.headway_model._prev_headways.pop(removed.id, None)
            self.headway_model.update_target(num_vehicles=len(self.vehicles))

        # Kontrolcuyu sifirla (yeni denge noktasi)
        self.controller.reset()
        print(f"[SIM] Arac sayisi ayarlandi: {len(self.vehicles)}")

    def _next_stop_idx_for_pos(self, position: float) -> int:
        """Verilen pozisyon için doğru next_stop_index'i bul."""
        for i, stop in enumerate(self.stops):
            if stop.meter_position > position:
                return i
        return 0

    def set_route_segment(self, start_idx: int, end_idx: int):
        """Araçları seçili duraklar arasına dağıt ve orada döngüye al.
        Fizik/durak listesi değişmez — sadece spawn ve wrap noktası ayarlanır."""
        n = len(self.stops)
        start_idx = max(0, min(start_idx, n - 2))
        end_idx = max(start_idx + 1, min(end_idx, n - 1))

        seg_start_pos = self.stops[start_idx].meter_position
        seg_end_pos = self.stops[end_idx].meter_position
        seg_length = max(seg_end_pos - seg_start_pos, 100.0)

        self._seg_start_pos = seg_start_pos
        self._seg_end_threshold = seg_end_pos + 100
        self._seg_start_stop_idx = start_idx

        # Araçları segment içinde eşit dağıt, doğru next_stop_index ile
        count = len(self.vehicles)
        gap = seg_length / count
        for i, veh in enumerate(self.vehicles):
            pos = seg_start_pos + (i + 0.3) * gap  # durağın tam üstüne değil
            veh.position_meters = pos
            veh.speed = self.config.max_speed * 0.5
            veh.acceleration = 0.0
            veh.phase = "cruising"
            veh.next_stop_index = self._next_stop_idx_for_pos(pos)
            veh.dwell_remaining = 0.0
            veh.holding_extra = 0.0
            veh.skip_next_stop = False
            veh.is_queuing = False
            veh.queue_wait_time = 0.0
            veh.trip_start_time = self.sim_time
            veh.trip_total_queue_time = 0.0
            veh.trip_total_dwell_time = 0.0

        self.controller.reset()
        self.pid.reset()
        print(f"[SIM] Segment: {self.stops[start_idx].name} -> {self.stops[end_idx].name} ({end_idx - start_idx + 1} durak, {seg_length:.0f}m)")

    def reset_route_segment(self):
        """Segment sıfırla — araçlar tam rotaya yeniden dağıtılır."""
        self._seg_start_pos = 0.0
        self._seg_end_threshold = float("inf")
        self._seg_start_stop_idx = 0

        count = len(self.vehicles)
        gap = self.route_length / count
        for i, veh in enumerate(self.vehicles):
            pos = i * gap
            veh.position_meters = pos
            veh.speed = self.config.max_speed * 0.5
            veh.acceleration = 0.0
            veh.phase = "cruising"
            veh.next_stop_index = self._next_stop_idx_for_pos(pos)
            veh.dwell_remaining = 0.0
            veh.holding_extra = 0.0
            veh.skip_next_stop = False
            veh.is_queuing = False
            veh.queue_wait_time = 0.0
            veh.trip_start_time = self.sim_time
            veh.trip_total_queue_time = 0.0
            veh.trip_total_dwell_time = 0.0

        self.controller.reset()
        self.pid.reset()
        print(f"[SIM] Segment sifirlandi — tüm rota aktif ({len(self.stops)} durak)")

    def get_dashboard_state(self) -> dict:
        """Dashboard'a gonderilecek JSON state."""
        current_hour = self.start_hour + self.sim_time / 3600.0
        is_rush = 7.0 <= current_hour <= 9.5 or 17.0 <= current_hour <= 19.5

        # Headway metrikleri
        hs = self.headway_model.compute(self.vehicles, self.dt)
        metrics = self.headway_model.compute_fleet_metrics(hs)

        # Kontrol komutlari (son step'ten)
        cmd_cache = self._last_commands

        # Bunching tespit — O(N) sorted scan
        bunching_threshold = self.headway_model.target_headway / 3.0
        bunched_ids = set()
        bunching_pairs_list = []
        hs_map = {h.vehicle_id: h for h in hs}
        sorted_v = sorted(self.vehicles, key=lambda v: v.position_meters)
        id_to_leader = {}
        for idx, veh in enumerate(sorted_v):
            nxt = sorted_v[(idx + 1) % len(sorted_v)]
            id_to_leader[veh.id] = nxt
        for h in hs:
            if h.time_headway < bunching_threshold and h.time_headway > 0:
                bunched_ids.add(h.vehicle_id)
                leader = id_to_leader.get(h.vehicle_id)
                if leader:
                    bunched_ids.add(leader.id)
                    bunching_pairs_list.append({
                        "id1": h.vehicle_id,
                        "id2": leader.id,
                        "headway": round(h.time_headway, 1),
                        "gap": round(h.distance_headway, 0),
                    })

        # Araclari SimVehicle formatina cevir
        vehicles_json = []
        for i, veh in enumerate(self.vehicles):
            pos = self.geometry.meter_to_position(veh.position_meters)

            # Kontrolcu komutu
            cmd = cmd_cache.get(veh.id)
            hs_state = hs_map.get(veh.id)
            is_bunched = veh.id in bunched_ids

            v_json = {
                "id": veh.id,
                "code": f"AM-{veh.id:02d}",
                "vehicleType": _VEHICLE_TYPE_JSON,
                "positionMeters": round(veh.position_meters, 1),
                "speed": round(veh.speed, 2),
                "acceleration": round(veh.acceleration, 2),
                "phase": veh.phase,
                "heading": round(pos["heading"], 1),
                "latitude": round(pos["latitude"], 6),
                "longitude": round(pos["longitude"], 6),
                "direction": veh.direction,
                "dwellRemaining": round(veh.dwell_remaining, 1),
                "nextStopIndex": veh.next_stop_index,
                "totalStops": veh.total_stops,
                "manualOverride": None,
                "isQueuing": veh.is_queuing,
                "queueWaitTime": round(veh.queue_wait_time, 1),
                "lastDwellTime": round(veh.last_dwell_time, 1),
                "isBunched": is_bunched,
                "_analytic": {
                    "headway": round(hs_state.time_headway, 1) if hs_state else 0,
                    "headwayError": round(hs_state.headway_error, 1) if hs_state else 0,
                    "speedFactor": round(cmd.speed_factor, 2) if cmd else 1.0,
                    "source": cmd.source if cmd else "none",
                    "overflowRisk": round(cmd.overflow_risk, 2) if cmd else 0,
                    "isInsidePlatform": is_inside_platform_zone(veh.position_meters, 20.0, self.stops[veh.next_stop_index]) if veh.next_stop_index < len(self.stops) else False,
                    "reason": cmd.reason if cmd else "",
                    "etaToStop": round(cmd.eta_to_stop, 1) if cmd else 0.0,
                    "idealArrival": round(cmd.ideal_arrival, 1) if cmd else 0.0,
                    "queueTimeSaved": round(cmd.queue_time_avoided, 1) if cmd else 0.0,
                    "netBenefit": round(cmd.net_benefit, 2) if cmd else 0.0,
                },
                "_trip": {
                    "elapsed": round(self.sim_time - veh.trip_start_time, 1),
                    "queueTime": round(veh.trip_total_queue_time, 1),
                    "dwellTime": round(veh.trip_total_dwell_time, 1),
                    "completedTrips": veh.trip_completed_count,
                    "lastDuration": round(veh.trip_last_duration, 1),
                },
            }
            vehicles_json.append(v_json)

        # Trafik bolgeleri
        traffic_json = [
            {
                "startMeter": round(tz.start_meter, 0),
                "endMeter": round(tz.end_meter, 0),
                "maxSpeedMs": round(tz.max_speed_ms, 1),
                "remainingSeconds": round(tz.remaining_seconds, 0),
                "severity": tz.severity,
            }
            for tz in self.traffic_zones
        ]

        # Her durak için dolu slot, yaklaşan ve kuyrukta sayısını hesapla
        occupied_by_stop: dict[int, int] = {}
        approaching_by_stop: dict[int, int] = {}
        queued_by_stop: dict[int, int] = {}
        for v in self.vehicles:
            si = v.next_stop_index
            if v.phase in ("stopped", "doorsClosed", "blocked", "docking"):
                occupied_by_stop[si] = occupied_by_stop.get(si, 0) + 1
            elif v.phase == "queued":
                queued_by_stop[si] = queued_by_stop.get(si, 0) + 1
            elif v.phase == "approaching":
                approaching_by_stop[si] = approaching_by_stop.get(si, 0) + 1

        stops_json = [
            {
                "index": s.index,
                "name": s.name,
                "meterPosition": round(s.meter_position, 1),
                "platformLengthMeters": round(s.platform_length_meters, 0),
                "slotCount": s.slot_count,
                "occupiedSlots": occupied_by_stop.get(s.index, 0),
                "approachingCount": approaching_by_stop.get(s.index, 0),
                "queuedCount": queued_by_stop.get(s.index, 0),
                "rearFreeSlots": compute_rear_free_slots(s, self.vehicles),
            }
            for s in self.stops
        ]

        # Aktif segment bilgisi
        seg_active = self._seg_end_threshold < float("inf")
        active_segment = None
        if seg_active:
            start_s = self.stops[self._seg_start_stop_idx]
            # end stop: son stop <= seg_end_threshold
            end_s = next(
                (s for s in reversed(self.stops) if s.meter_position <= self._seg_end_threshold - 100),
                self.stops[-1],
            )
            active_segment = {
                "startName": start_s.name,
                "endName": end_s.name,
                "startIdx": self._seg_start_stop_idx,
                "endIdx": end_s.index,
                "stopCount": end_s.index - self._seg_start_stop_idx + 1,
                "totalStops": len(self.stops),
            }

        return {
            "time": round(self.sim_time, 1),
            "vehicles": vehicles_json,
            "stops": stops_json,
            "allStops": [{"index": s.index, "name": s.name} for s in self.stops],
            "trafficZones": traffic_json,
            "isRushHour": is_rush,
            "running": True,
            "timeScale": self.time_scale,
            "activeSegment": active_segment,
            # Analitik motor metrikleri
            "analytics": {
                "headwayCV": round(metrics["cv"], 3),
                "bunchingPairs": metrics["bunching_pairs"],
                "meanHeadway": round(metrics["mean_headway"], 1),
                "targetHeadway": round(self.headway_model.target_headway, 1),
                "pidGains": self.pid.get_gains(),
                "activeHolds": sum(1 for c in cmd_cache.values() if c.hold_time > 0),
                "activeFilters": sum(1 for c in cmd_cache.values() if c.speed_factor < 0.95),
                # Yeni: durak-slot metrikleri
                **self.controller.get_state_summary(),
                # SmartStop bölge durumları (her durak için congestion, araç sayısı vb.)
                "smartStopStates": self.controller.get_stop_interface_states(),
                # Uçtan uca sefer metrikleri
                **self._compute_trip_metrics(),
            },
        }


# ============================================
# WebSocket Sunucu
# ============================================

WS_PORT = 8765
SIM_TICK = 0.05       # 50ms — fizik motoru her zaman 20 Hz çalışır
WS_SEND_INTERVAL = 0.1  # 100ms = 10 FPS dashboard güncellemesi


async def simulation_handler(websocket):
    """Tek bir dashboard baglantisi icin simulasyon dongusu."""
    print(f"[WS] Dashboard baglandi: {websocket.remote_address}")

    sim = SimManager(
        vehicle_count=30,
        direction="gidis",
        start_hour=7.0,
        time_scale=5.0,
    )

    async def listen_commands():
        """Dashboard'dan gelen komutlari dinle."""
        try:
            async for message in websocket:
                try:
                    cmd = json.loads(message)
                    action = cmd.get("action")
                    if action == "add_vehicle":
                        sim.add_vehicle()
                    elif action == "remove_vehicle":
                        sim.remove_vehicle()
                    elif action == "set_vehicle_count":
                        sim.set_vehicle_count(int(cmd.get("value", 15)))
                    elif action == "set_time_scale":
                        sim.set_time_scale(cmd.get("value", 5.0))
                    elif action == "set_route_segment":
                        sim.set_route_segment(int(cmd.get("start", 0)), int(cmd.get("end", len(sim.stops) - 1)))
                    elif action == "reset_route_segment":
                        sim.reset_route_segment()
                    if action:
                        print(f"[CMD] {action} islendi")
                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    import traceback
                    print(f"[CMD HATA] {e}")
                    traceback.print_exc()
        except Exception as e:
            print(f"[WS] listen_commands kapandi: {e}")

    async def send_state():
        """Simulasyon state'ini periyodik gonder.
        Fizik motoru SIM_TICK (50ms) hızında çalışır,
        dashboard güncellemesi WS_SEND_INTERVAL (200ms = 5 FPS) hızında gönderilir.
        """
        try:
            send_accumulator = 0.0
            while True:
                sim.tick(SIM_TICK)
                send_accumulator += SIM_TICK
                if send_accumulator >= WS_SEND_INTERVAL:
                    send_accumulator = 0.0
                    state = sim.get_dashboard_state()
                    await websocket.send(json.dumps(state, ensure_ascii=False))
                await asyncio.sleep(SIM_TICK)
        except Exception as e:
            print(f"[WS] Baglanti kapandi: {e}")

    # Iki yonlu: hem gonder hem dinle
    await asyncio.gather(listen_commands(), send_state())


async def main():
    print("=" * 50)
    print("[ANALITIK MOTOR] Simulasyon Sunucusu")
    print(f"  WebSocket: ws://localhost:{WS_PORT}")
    print(f"  Fizik: {1/SIM_TICK:.0f} Hz | Dashboard: {1/WS_SEND_INTERVAL:.0f} FPS")
    print(f"  Durdurmak icin Ctrl+C")
    print("=" * 50)

    async with websockets.serve(simulation_handler, "0.0.0.0", WS_PORT):
        await asyncio.Future()  # sonsuza kadar calis


if __name__ == "__main__":
    asyncio.run(main())
