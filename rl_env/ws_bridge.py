"""
WebSocket Bridge — Egitim surecini canli izlemek icin.

Python egitim dongusu → WebSocket server (port 8765) → TS Dashboard

Kullanim:
    from rl_env.ws_bridge import TrainingBridge

    bridge = TrainingBridge(direction="gidis")
    bridge.start()     # Arka plan thread'i baslatir

    # Egitim dongusunde:
    bridge.update(env, step_count, reward, info)

    # Bittiginde:
    bridge.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import threading
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

# websockets loglarini sustur (InvalidMessage traceback'leri kirletiyor)
logging.getLogger("websockets").setLevel(logging.CRITICAL)

# WebSocket kurulu olmayabilir — opsiyonel
try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False


class RouteGeometry:
    """
    Metre pozisyonu -> lat/lng donusturucu.
    route_network.json'daki edge geometrilerini kullanir.
    """

    def __init__(self, direction: str = "gidis"):
        self.segments: List[Dict] = []
        self._load(direction)

    def _haversine(self, lat1: float, lon1: float,
                   lat2: float, lon2: float) -> float:
        R = 6_371_000
        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        a = (math.sin(d_lat / 2) ** 2
             + math.cos(math.radians(lat1))
             * math.cos(math.radians(lat2))
             * math.sin(d_lon / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _bearing(self, lat1: float, lon1: float,
                 lat2: float, lon2: float) -> float:
        """İki nokta arası bearing (derece, 0=kuzey)."""
        d_lon = math.radians(lon2 - lon1)
        lat1_r = math.radians(lat1)
        lat2_r = math.radians(lat2)
        x = math.sin(d_lon) * math.cos(lat2_r)
        y = (math.cos(lat1_r) * math.sin(lat2_r)
             - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(d_lon))
        return (math.degrees(math.atan2(x, y)) + 360) % 360

    def _load(self, direction: str) -> None:
        # Önce JS tarafından üretilen cache'i dene
        cache_path = os.path.join(
            os.path.dirname(__file__), "data", f"route_cache_{direction}.json"
        )
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            for seg in cache["segments"]:
                self.segments.append({
                    "start_meter": seg["start_meter"],
                    "end_meter": seg["end_meter"],
                    "lat1": seg["lat1"], "lng1": seg["lng1"],
                    "lat2": seg["lat2"], "lng2": seg["lng2"],
                    "length": seg["length"],
                })
            return

        # Fallback: route_network.json'dan yeniden hesapla
        data_path = os.path.join(
            os.path.dirname(__file__), "data", "route_network.json"
        )
        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        edges = data["edges"][direction]
        cumulative = 0.0

        for edge in edges:
            geom = edge["geometry"]
            for i in range(len(geom) - 1):
                lat1, lng1 = geom[i]
                lat2, lng2 = geom[i + 1]
                dist = self._haversine(lat1, lng1, lat2, lng2)
                if dist < 0.1:
                    continue
                self.segments.append({
                    "start_meter": cumulative,
                    "end_meter": cumulative + dist,
                    "lat1": lat1, "lng1": lng1,
                    "lat2": lat2, "lng2": lng2,
                    "length": dist,
                })
                cumulative += dist

    def meter_to_latlng(self, meter: float) -> tuple[float, float, float]:
        """
        Metre pozisyonundan lat, lng, heading dondurur.

        Returns: (latitude, longitude, heading_degrees)
        """
        # Sinirla
        meter = max(0, min(meter, self.segments[-1]["end_meter"]))

        # Binary search ile segment bul
        lo, hi = 0, len(self.segments) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self.segments[mid]["end_meter"] < meter:
                lo = mid + 1
            else:
                hi = mid

        seg = self.segments[lo]
        t = (meter - seg["start_meter"]) / max(seg["length"], 0.01)
        t = max(0.0, min(1.0, t))

        lat = seg["lat1"] + t * (seg["lat2"] - seg["lat1"])
        lng = seg["lng1"] + t * (seg["lng2"] - seg["lng1"])
        heading = self._bearing(seg["lat1"], seg["lng1"],
                                seg["lat2"], seg["lng2"])

        return lat, lng, heading


class TrainingBridge:
    """
    Egitim surecini WebSocket uzerinden dashboard'a yayin yapar.

    Usage:
        bridge = TrainingBridge(direction="gidis")
        bridge.start()

        # Her N step'te:
        bridge.update(env, step=1000, reward=0.5, info={...})

        bridge.stop()
    """

    def __init__(
        self,
        direction: str = "gidis",
        host: str = "localhost",
        port: int = 8765,
        broadcast_every: int = 3,
    ):
        if not HAS_WEBSOCKETS:
            print("[WS Bridge] websockets yuklu degil! pip install websockets")
            self.enabled = False
            return

        self.enabled = True
        self.host = host
        self.port = port
        self.broadcast_every = broadcast_every
        self.direction = direction

        self.geo = RouteGeometry(direction)
        self.clients: set = set()
        self._state: Dict[str, Any] = {}
        self._state_json: str = ""  # Thread-safe cached JSON
        self._state_lock = threading.Lock()  # Thread safety
        self._step_counter = 0
        self._last_broadcast_time = 0.0  # wall-clock throttle
        self._broadcast_interval = 0.1  # 100ms (~10fps, kararlı)
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._metrics_history: List[Dict[str, float]] = []

    def start(self) -> None:
        """Arka plan WebSocket server thread'ini baslat."""
        if not self.enabled:
            return
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        print(f"[WS Bridge] ws://{self.host}:{self.port} basladi")

    def stop(self) -> None:
        """Server'i durdur."""
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        print("[WS Bridge] durduruldu")

    def update(self, env, step: int = 0, reward: float = 0.0,
               info: Optional[Dict] = None,
               iteration: int = 0, total_reward: float = 0.0,
               actions: Optional[List[int]] = None) -> None:
        """
        Mevcut environment durumunu WebSocket'e gonder.
        Hem CPU MetrobusEnv hem GPU GpuMetrobusEnv destekler.

        Args:
            env: MetrobusEnv veya GpuMetrobusEnv instance
            step: Mevcut step sayisi
            reward: Son step reward
            info: env.step() info dict'i
            iteration: PPO iterasyon numarasi
            total_reward: Episode toplam reward
        """
        if not self.enabled:
            return

        self._step_counter += 1
        # Zaman bazli throttle — gercek zamana yakin gosterim
        now = time.monotonic()
        if now - self._last_broadcast_time < self._broadcast_interval:
            return
        self._last_broadcast_time = now

        info = info or {}

        # GPU env mi CPU env mi tespit et
        is_gpu_env = hasattr(env, 'positions') and hasattr(env.positions, 'cpu')

        if is_gpu_env:
            vehicles, traffic_zones, bunching_info = self._extract_gpu_state(env, actions)
        else:
            vehicles, traffic_zones = self._extract_cpu_state(env)
            bunching_info = {}

        # Metrikler
        metrics = {
            "step": step,
            "iteration": iteration,
            "reward": round(reward, 4),
            "totalReward": round(total_reward, 2),
            "avgSpeed": round(info.get("avg_speed_kmh", 0), 1),
            "minGap": round(info.get("min_gap_m", 0), 1),
            "maxGap": round(info.get("max_gap_m", 0), 1),
            "headwayStd": round(info.get("headway_std", 0), 2),
            "numStopped": info.get("num_stopped", 0),
            "bunching": info.get("episode_bunching", 0),
        }

        # Reward bileşenleri
        reward_components = info.get("reward_components", {})

        # sim_time — tensor ise [0].item()
        sim_time_val = env.sim_time[0].item() if hasattr(env.sim_time, 'item') or hasattr(env.sim_time, 'shape') else env.sim_time
        if hasattr(env.sim_time, 'shape') and env.sim_time.dim() > 0:
            sim_time_val = env.sim_time[0].item()

        state = {
            # SimState uyumlu
            "time": round(sim_time_val, 1),
            "vehicles": vehicles,
            "trafficZones": traffic_zones,
            "isRushHour": info.get("is_rush_hour", False),
            "running": True,
            "timeScale": 1.0,
            # Eğitim ek verileri
            "mode": "training",
            "metrics": metrics,
            "rewardComponents": {
                k: round(v, 4) for k, v in reward_components.items()
            } if reward_components else {},
            # Bunching detay
            "bunchingPairs": bunching_info.get("pairs", []) if isinstance(bunching_info, dict) else [],
            "bunchingCount": bunching_info.get("count", 0) if isinstance(bunching_info, dict) else 0,
            "avgGap": bunching_info.get("avgGap", 0) if isinstance(bunching_info, dict) else 0,
            # Predictive engine istatistikleri
            "predictiveEngine": info.get("predictive_engine", {}),
        }

        # Thread-safe state güncelleme — JSON'u ana thread'de hazırla
        with self._state_lock:
            self._state = state
            self._state_json = json.dumps(state)

    # ─── GPU env state extraction ───
    _PHASE_NAMES = ["cruising", "approaching", "queued", "docking", "stopped", "doorsClosed", "blocked", "departing"]
    _ACTION_NAMES = ["NORMAL", "SLOW", "FAST", "HOLD"]

    def _extract_gpu_state(self, env, actions=None) -> tuple:
        """
        GpuMetrobusEnv GPU tensörlerinden dashboard state çıkar.
        VecEnv: env[0] verisini kullanır (B, N) → (N,)
        Bunching tespiti ve gap hesaplaması dahil.
        """
        # GPU → CPU (env[0] slice — tek env görselleştirme)
        is_batched = env.positions.dim() == 2
        if is_batched:
            positions = env.positions[0].cpu().numpy()
            speeds = env.speeds[0].cpu().numpy()
            accels = env.accelerations[0].cpu().numpy()
            phases = env.phases[0].cpu().numpy()
            dwell_rem = env.dwell_remaining[0].cpu().numpy()
            next_si = env.next_stop_idx[0].cpu().numpy()
            is_queuing = env.is_queuing[0].cpu().numpy()
            queue_wait = env.queue_wait_time[0].cpu().numpy()
        else:
            positions = env.positions.cpu().numpy()
            speeds = env.speeds.cpu().numpy()
            accels = env.accelerations.cpu().numpy()
            phases = env.phases.cpu().numpy()
            dwell_rem = env.dwell_remaining.cpu().numpy()
            next_si = env.next_stop_idx.cpu().numpy()
            is_queuing = env.is_queuing.cpu().numpy()
            queue_wait = env.queue_wait_time.cpu().numpy()

        # ─── Bunching tespiti: gap hesaplaması ───
        import numpy as np
        N = len(positions)
        sorted_indices = np.argsort(positions)
        sorted_pos = positions[sorted_indices]

        # Forward ve backward gap (sıralı pozisyonlarda)
        forward_gaps = np.full(N, 9999.0)  # metre
        backward_gaps = np.full(N, 9999.0)
        for rank in range(N):
            orig_idx = sorted_indices[rank]
            if rank < N - 1:
                forward_gaps[orig_idx] = sorted_pos[rank + 1] - sorted_pos[rank]
            if rank > 0:
                backward_gaps[orig_idx] = sorted_pos[rank] - sorted_pos[rank - 1]

        # Bunching threshold'ları
        CRITICAL_M = 50.0
        WARNING_M = 100.0

        bunching_pairs = []
        bunching_count = 0

        vehicles = []
        for i in range(N):
            lat, lng, heading = self.geo.meter_to_latlng(float(positions[i]))
            phase_name = self._PHASE_NAMES[int(phases[i])] if int(phases[i]) < 8 else "cruising"

            fgap = float(forward_gaps[i])
            bgap = float(backward_gaps[i])
            min_gap = min(fgap, bgap)
            is_bunched = min_gap < WARNING_M
            warning = None
            if min_gap < CRITICAL_M:
                warning = "critical"
            elif min_gap < WARNING_M:
                warning = "warning"

            if is_bunched:
                bunching_count += 1

            # Actor aksiyonu
            action_name = None
            if actions is not None and i < len(actions):
                a = int(actions[i])
                action_name = self._ACTION_NAMES[a] if a < 4 else "NORMAL"

            vehicles.append({
                "id": i,
                "code": f"M{i:02d}",
                "positionMeters": round(float(positions[i]), 1),
                "speed": round(float(speeds[i]), 3),
                "acceleration": round(float(accels[i]), 3),
                "phase": phase_name,
                "heading": round(heading, 1),
                "latitude": lat,
                "longitude": lng,
                "direction": env.direction,
                "dwellRemaining": round(float(dwell_rem[i]), 1),
                "nextStopIndex": int(next_si[i]),
                "totalStops": 0,
                "totalDistance": 0.0,
                "manualOverride": None,
                "isQueuing": bool(is_queuing[i]),
                "queueWaitTime": round(float(queue_wait[i]), 1),
                "lastDwellTime": 0.0,
                "skipNextStop": False,
                # Bunching bilgisi
                "forwardGap": round(fgap, 1),
                "backwardGap": round(bgap, 1),
                "isBunched": is_bunched,
                "bunchingWarning": warning,
                "action": action_name,
                # Predictive engine bilgisi
                "predictiveDecision": self._get_predictive_vehicle_info(env, i),
            })

        # Bunching çiftleri (haritada çizgi çizmek için)
        for rank in range(N - 1):
            gap = float(sorted_pos[rank + 1] - sorted_pos[rank])
            if gap < WARNING_M:
                i1 = int(sorted_indices[rank])
                i2 = int(sorted_indices[rank + 1])
                bunching_pairs.append({
                    "id1": i1, "id2": i2,
                    "gap": round(gap, 1),
                    "severity": "critical" if gap < CRITICAL_M else "warning",
                })

        all_gaps = sorted_pos[1:] - sorted_pos[:-1] if N > 1 else [0]
        bunching_info = {
            "pairs": bunching_pairs,
            "count": bunching_count,
            "avgGap": round(float(np.mean(all_gaps)), 1) if len(all_gaps) > 0 else 0,
        }

        # Trafik bölgeleri (GPU tensörleri)
        traffic_zones = []
        if len(env.tz_remaining) > 0:
            tz_starts = env.tz_starts.cpu().numpy()
            tz_ends = env.tz_ends.cpu().numpy()
            tz_speeds = env.tz_speeds.cpu().numpy()
            tz_remaining = env.tz_remaining.cpu().numpy()
            for j in range(len(tz_remaining)):
                spd = float(tz_speeds[j])
                severity = "heavy" if spd <= 2.5 else ("moderate" if spd <= 6.0 else "light")
                traffic_zones.append({
                    "startMeter": round(float(tz_starts[j]), 1),
                    "endMeter": round(float(tz_ends[j]), 1),
                    "maxSpeedMs": round(spd, 1),
                    "remainingSeconds": round(float(tz_remaining[j]), 1),
                    "severity": severity,
                })

        return vehicles, traffic_zones, bunching_info

    def _get_predictive_vehicle_info(self, env, bus_id: int) -> dict | None:
        """Predictive engine kararını per-vehicle JSON olarak döndür."""
        decisions = getattr(env, '_predictive_decisions', {})
        dec = decisions.get(bus_id)
        if dec is None or dec.decision.value == "NO_RISK":
            return None

        result = {
            "decision": dec.decision.value,
            "vTarget": round(dec.v_target, 2),
            "scoreA": round(dec.score_a, 2),
            "scoreB": round(dec.score_b, 2),
            "timeSaved": round(dec.time_saved, 2),
        }
        if dec.scenario_a:
            result["scenarioA"] = {
                "totalTime": round(dec.scenario_a.total_time, 1),
                "waitTime": round(dec.scenario_a.wait_time, 1),
            }
        if dec.scenario_b and dec.scenario_b.feasible:
            result["scenarioB"] = {
                "totalTime": round(dec.scenario_b.total_time, 1),
                "vFiltered": round(dec.scenario_b.v_filtered, 2),
                "speedReductionPct": round(
                    (1 - dec.scenario_b.v_filtered / max(0.01, dec.v_target)) * 100
                    if dec.decision.value == "SPEED_FILTER" else 0, 1
                ),
            }
        return result

    def _extract_cpu_state(self, env) -> tuple:
        """Orijinal CPU MetrobusEnv'den state çıkar (eski yöntem)."""
        vehicles = []
        for v in env.vehicles:
            lat, lng, heading = self.geo.meter_to_latlng(v.position_meters)
            vehicles.append({
                "id": v.id,
                "code": f"M{v.id:02d}",
                "positionMeters": round(v.position_meters, 1),
                "speed": round(v.speed, 3),
                "acceleration": round(v.acceleration, 3),
                "phase": v.phase,
                "heading": round(heading, 1),
                "latitude": lat,
                "longitude": lng,
                "direction": self.direction,
                "dwellRemaining": round(v.dwell_remaining, 1),
                "nextStopIndex": v.next_stop_index,
                "totalStops": v.total_stops,
                "totalDistance": round(v.total_distance, 1),
                "manualOverride": None,
                "isQueuing": v.is_queuing,
                "queueWaitTime": round(v.queue_wait_time, 1),
                "lastDwellTime": round(v.last_dwell_time, 1),
                "skipNextStop": v.skip_next_stop,
            })

        traffic_zones = []
        for tz in env.traffic_zones:
            traffic_zones.append({
                "startMeter": round(tz.start_meter, 1),
                "endMeter": round(tz.end_meter, 1),
                "maxSpeedMs": round(tz.max_speed_ms, 1),
                "remainingSeconds": round(tz.remaining_seconds, 1),
                "severity": tz.severity,
            })

        return vehicles, traffic_zones

    async def _handler(self, ws) -> None:
        """Yeni client baglantisi."""
        self.clients.add(ws)
        print(f"[WS Bridge] Client baglandi ({len(self.clients)} toplam)")
        try:
            # İlk bağlantıda mevcut state'i gönder
            with self._state_lock:
                msg = self._state_json
            if msg:
                await ws.send(msg)
            # Bağlantı açık kaldığı sürece bekle (ping/pong ile)
            async for _ in ws:
                pass  # Client mesaj göndermez, sadece alır
        except websockets.exceptions.ConnectionClosedOK:
            pass
        except Exception:
            pass
        finally:
            self.clients.discard(ws)
            print(f"[WS Bridge] Client ayrildi ({len(self.clients)} kaldi)")

    async def _broadcast(self) -> None:
        """Tüm client'lara state gonder."""
        if not self.clients:
            return
        with self._state_lock:
            msg = self._state_json
        if not msg:
            return
        dead = set()
        for ws in list(self.clients):
            try:
                await ws.send(msg)
            except Exception:
                dead.add(ws)
        self.clients -= dead

    async def _periodic_broadcast(self) -> None:
        """Her 300ms'de son bilinen state'i broadcast et — donma olmaz."""
        while True:
            await asyncio.sleep(self._broadcast_interval)
            if self.clients and self._state:
                await self._broadcast()

    def _run_server(self) -> None:
        """Arka plan event loop — WS server + periyodik broadcast."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def _serve() -> None:
            async with websockets.serve(  # type: ignore
                self._handler, self.host, self.port,
                ping_interval=20,
                ping_timeout=60,
                close_timeout=5,
            ):
                # Periyodik broadcast gorevi baslat
                asyncio.ensure_future(self._periodic_broadcast())
                await asyncio.Future()  # run forever

        try:
            self._loop.run_until_complete(_serve())
        except Exception:
            pass
