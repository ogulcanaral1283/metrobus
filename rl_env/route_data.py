"""
Route Linearizer — Edge geometrisini metre bazlı çizgiye dönüştürür.
TypeScript route-linearizer.ts'den Python'a taşındı.
Lat/lng render verileri tutulmaz, sadece metre pozisyonları.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import List

from .config import Direction


@dataclass
class LinearStop:
    """Linearize edilmiş rota üzerindeki durak."""

    index: int
    name: str
    meter_position: float       # hat üzerindeki metre pozisyonu
    passenger_load: float = 0.0
    slot_count: int = 1
    platform_length_meters: float = 0.0


@dataclass
class LinearSegment:
    """Rota segment'i (noktadan noktaya)."""

    start_meter: float
    end_meter: float
    length: float
    # lat/lng sadece linearization sırasında kullanılır, saklanmaz


@dataclass
class LinearRoute:
    """Linearize edilmiş rota."""

    total_length: float
    stops: List[LinearStop]
    direction: Direction
    # segments saklanmaz — sadece linearization sırasında geçici kullanılır


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine mesafe (metre)."""
    R = 6_371_000
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _project_point_on_segment(
    lat: float, lng: float,
    lat1: float, lng1: float,
    lat2: float, lng2: float,
) -> float:
    """Noktayı segment üzerine project et (0-1 arası t değeri)."""
    dx = lat2 - lat1
    dy = lng2 - lng1
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-12:
        return 0.0
    t = ((lat - lat1) * dx + (lng - lng1) * dy) / len_sq
    return max(0.0, min(1.0, t))


def _find_closest_meter(
    segments: list[dict], lat: float, lng: float,
) -> float:
    """Lat/lng'den en yakın metre pozisyonunu bul (full search)."""
    best_dist = float("inf")
    best_meter = 0.0

    for seg in segments:
        t = _project_point_on_segment(
            lat, lng,
            seg["start_lat"], seg["start_lng"],
            seg["end_lat"], seg["end_lng"],
        )
        proj_lat = seg["start_lat"] + t * (seg["end_lat"] - seg["start_lat"])
        proj_lng = seg["start_lng"] + t * (seg["end_lng"] - seg["start_lng"])
        d = _haversine(lat, lng, proj_lat, proj_lng)

        if d < best_dist:
            best_dist = d
            best_meter = seg["start_meter"] + t * seg["length"]

    return best_meter


def linearize_route(
    edges: list[dict],
    stops: list[dict],
    direction: Direction,
) -> LinearRoute:
    """
    Edge dizisini linearize eder.
    TypeScript linearizeRoute fonksiyonunun Python karşılığı.
    """
    segments: list[dict] = []
    cumulative_meter = 0.0

    for edge in edges:
        geom = edge["geometry"]
        for pi in range(len(geom) - 1):
            lat1, lng1 = geom[pi]
            lat2, lng2 = geom[pi + 1]
            dist = _haversine(lat1, lng1, lat2, lng2)
            if dist < 0.1:
                continue

            segments.append({
                "start_meter": cumulative_meter,
                "end_meter": cumulative_meter + dist,
                "start_lat": lat1,
                "start_lng": lng1,
                "end_lat": lat2,
                "end_lng": lng2,
                "length": dist,
            })
            cumulative_meter += dist

    # Durakları metre pozisyonuna eşle
    linear_stops: list[LinearStop] = []
    for si, stop in enumerate(stops):
        meter_pos = _find_closest_meter(segments, stop["latitude"], stop["longitude"])
        linear_stops.append(LinearStop(
            index=si,
            name=stop["name"],
            meter_position=meter_pos,
            slot_count=1,  # varsayılan
        ))

    # Metre pozisyonuna göre sırala
    linear_stops.sort(key=lambda s: s.meter_position)
    # İndeksleri güncelle
    for i, s in enumerate(linear_stops):
        s.index = i

    return LinearRoute(
        total_length=cumulative_meter,
        stops=linear_stops,
        direction=direction,
    )


def _normalize_name(name: str) -> str:
    """Durak adi karsilastirmasi icin normalize et (Turkce karakter farklari)."""
    replacements = {
        "\u00e7": "c", "\u00c7": "C", "\u011f": "g", "\u011e": "G",
        "\u0131": "i", "\u0130": "I", "\u00f6": "o", "\u00d6": "O",
        "\u015f": "s", "\u015e": "S", "\u00fc": "u", "\u00dc": "U",
    }
    result = name.lower().strip()
    for old, new in replacements.items():
        result = result.replace(old, new.lower())
    return result


def _load_station_slots() -> dict[str, dict]:
    """station_slots.json'dan slot bilgilerini yukle."""
    slots_path = os.path.join(os.path.dirname(__file__), "data", "station_slots.json")
    if not os.path.exists(slots_path):
        return {}

    with open(slots_path, "r", encoding="utf-8") as f:
        slots_data = json.load(f)

    # Normalize isimle index'le
    result = {}
    for slot in slots_data:
        key = _normalize_name(slot["name"])
        result[key] = {
            "slot_count": slot["slotCount"],
            "platform_length": slot["platformLengthMeters"],
        }
    return result


def load_route(direction: Direction = "gidis", max_stops: int = 0) -> LinearRoute:
    """
    Rota verisini yukle. Oncelik sirasi:
     1. JS tarafindan uretilen route_cache_{direction}.json (JavaScript ile birebir eslesme)
     2. route_network.json'dan Python ile yeniden linearize et (fallback)

    max_stops: 0 = tum duraklar, >0 = ilk N durak (rota kisaltma)
    """
    # --- 1. Cache'den yukle (JS ile senkron) ---
    cache_path = os.path.join(
        os.path.dirname(__file__), "data", f"route_cache_{direction}.json"
    )
    if os.path.exists(cache_path):
        return _load_from_cache(cache_path, direction, max_stops)

    # --- 2. Fallback: Python linearization ---
    data_path = os.path.join(os.path.dirname(__file__), "data", "route_network.json")
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    edges = data["edges"][direction]
    stops = data["stops"][direction]

    route = linearize_route(edges, stops, direction)

    # Slot bilgilerini ekle
    slot_data = _load_station_slots()
    matched = 0
    for stop in route.stops:
        key = _normalize_name(stop.name)
        if key in slot_data:
            stop.slot_count = slot_data[key]["slot_count"]
            stop.platform_length_meters = slot_data[key]["platform_length"]
            matched += 1
        else:
            for slot_key, slot_info in slot_data.items():
                if slot_key in key or key in slot_key:
                    stop.slot_count = slot_info["slot_count"]
                    stop.platform_length_meters = slot_info["platform_length"]
                    matched += 1
                    break

    # Rota kisaltma
    if max_stops > 0 and max_stops < len(route.stops):
        route.stops = route.stops[:max_stops]
        route.total_length = route.stops[-1].meter_position + 500
        for i, s in enumerate(route.stops):
            s.index = i

    return route


def _load_from_cache(
    cache_path: str, direction: Direction, max_stops: int = 0,
) -> LinearRoute:
    """JS tarafindan uretilen route_cache JSON'dan yukle."""
    with open(cache_path, "r", encoding="utf-8") as f:
        cache = json.load(f)

    stops = []
    for s in cache["stops"]:
        stops.append(LinearStop(
            index=s["index"],
            name=s["name"],
            meter_position=s["meter_position"],
            slot_count=s.get("slot_count", 1),
            platform_length_meters=s.get("platform_length_meters", 0.0),
        ))

    route = LinearRoute(
        total_length=cache["total_length"],
        stops=stops,
        direction=direction,
    )

    # Rota kisaltma
    if max_stops > 0 and max_stops < len(route.stops):
        route.stops = route.stops[:max_stops]
        route.total_length = route.stops[-1].meter_position + 500
        for i, s in enumerate(route.stops):
            s.index = i

    return route

