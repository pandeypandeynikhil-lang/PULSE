"""Live ambulance tracking — real road routes, simulated in real time.

Mirrors `simulation.py`'s central idea, applied to geography instead of
physiology: author real waypoints once, let `Engine.tick()` interpolate and
report on them every second on its own. The waypoints here are a real
road-network polyline fetched from OSRM (https://project-osrm.org — free,
no API key) rather than a vitals curve, and fetched exactly once, at
`python -m backend.ambulance` time — cached to `data/ambulance_routes.json`
and committed with the project. That means a fresh clone works completely
offline: `Engine.reset()` only ever reads the cached file, never calls out
to OSRM, so a live demo's Reset button can never depend on the venue's wifi
or a third-party routing service being up. If a route was never fetched (no
internet the one time the prefetch ran), building the fleet falls back to a
straight line between the same two points — less road-accurate, never
broken.

The frontend radar view never needs a raw lat/lng — only bearing and
distance from the hospital, which is all `position_at()` returns.
"""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE_PATH = os.path.join(_HERE, "..", "data", "ambulance_routes.json")

# A real point in a real city (Bengaluru) so OSRM has an actual road network
# to route against — not a specific hospital, just a fixed map location the
# scenario's ambulances converge on.
HOSPITAL = {"name": "PULSE Emergency Department", "lat": 12.9716, "lng": 77.5946}

# Departure times and speeds are staggered the same way simulation.py stages
# patient arrivals — spread across the shift, not all inbound at once.
# Vehicle number / crew are dispatch-record detail for the click-through
# panel — invented, plausible, and deliberately NOT personal contact info
# (a radio callsign, not a phone number) for the same reason nothing else
# in this project fabricates data that could pass for something real.
_FLEET = [
    {"name": "Whitefield", "lat": 12.9698, "lng": 77.7500, "depart_min": -6.0,
     "speed_kmh": 38, "note": "RTA, two casualties, one unresponsive",
     "vehicle_number": "KA-01-AB-4521", "driver": "R. Kumar", "paramedic": "S. Iyer",
     "vehicle_type": "Advanced Life Support (ALS)", "callsign": "Unit 12"},
    {"name": "Electronic City", "lat": 12.8452, "lng": 77.6602, "depart_min": 4.0,
     "speed_kmh": 40, "note": "chest pain, 62yo male, diaphoretic",
     "vehicle_number": "KA-01-AC-1187", "driver": "M. Shetty", "paramedic": "A. Fernandes",
     "vehicle_type": "Advanced Life Support (ALS)", "callsign": "Unit 07"},
    {"name": "Yeshwanthpur", "lat": 13.0284, "lng": 77.5540, "depart_min": 14.0,
     "speed_kmh": 35, "note": "fall from height, suspected fracture",
     "vehicle_number": "KA-01-AD-6642", "driver": "P. Reddy", "paramedic": "N. Joseph",
     "vehicle_type": "Basic Life Support (BLS)", "callsign": "Unit 19"},
    {"name": "Koramangala", "lat": 12.9352, "lng": 77.6245, "depart_min": 24.0,
     "speed_kmh": 32, "note": "breathless, known COPD",
     "vehicle_number": "KA-01-AE-3309", "driver": "D. Prakash", "paramedic": "K. Menon",
     "vehicle_type": "Advanced Life Support (ALS)", "callsign": "Unit 03"},
    {"name": "Hebbal", "lat": 13.0358, "lng": 77.5970, "depart_min": 34.0,
     "speed_kmh": 36, "note": "seizure, first episode",
     "vehicle_number": "KA-01-AF-7715", "driver": "V. Rao", "paramedic": "T. Pillai",
     "vehicle_type": "Basic Life Support (BLS)", "callsign": "Unit 15"},
]


@dataclass
class Ambulance:
    id: str
    display_id: str
    origin_name: str
    note: str
    route: list[tuple[float, float]]
    distance_km: float
    depart_min: float
    duration_min: float
    vehicle_number: str
    driver: str
    paramedic: str
    vehicle_type: str
    callsign: str


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = *a, *b
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _straight_line(a: tuple[float, float], b: tuple[float, float], n: int = 24) -> list[tuple[float, float]]:
    return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1)]


def _fetch_osrm_route(origin: tuple[float, float], destination: tuple[float, float]
                      ) -> tuple[list[tuple[float, float]], float] | None:
    """One-time call to OSRM's free public routing server. Returns None on
    any failure — no internet, timeout, service down, unexpected response
    shape — so the caller falls back to a straight line instead of the
    whole prefetch step failing."""
    lat1, lng1 = origin
    lat2, lng2 = destination
    url = (f"https://router.project-osrm.org/route/v1/driving/"
          f"{lng1},{lat1};{lng2},{lat2}?overview=full&geometries=geojson")
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            data = json.loads(resp.read())
        route = data["routes"][0]
        polyline = [(lat, lng) for lng, lat in route["geometry"]["coordinates"]]
        return polyline, route["distance"] / 1000.0
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError, OSError):
        return None


def prefetch_routes() -> dict[str, Any]:
    """Builds the committed cache file. Run this once —
    `python -m backend.ambulance` — not at server startup, and never from
    inside Engine.reset(); see the module docstring for why."""
    destination = (HOSPITAL["lat"], HOSPITAL["lng"])
    cache: dict[str, Any] = {}
    for entry in _FLEET:
        name = entry["name"]
        origin = (entry["lat"], entry["lng"])
        fetched = _fetch_osrm_route(origin, destination)
        if fetched:
            polyline, distance_km = fetched
            source = "osrm"
        else:
            polyline = _straight_line(origin, destination)
            distance_km = _haversine_km(origin, destination)
            source = "straight_line"
        cache[name] = {"route": polyline, "distance_km": round(distance_km, 2), "source": source}
        print(f"{name}: {source}, {distance_km:.1f} km, {len(polyline)} route points")
    os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
    with open(_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)
    return cache


def _load_cache() -> dict[str, Any]:
    if not os.path.exists(_CACHE_PATH):
        return {}
    with open(_CACHE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_fleet() -> list[Ambulance]:
    """Reads the committed cache only — no network call, ever, in the live-
    serving path. Falls back to a straight line per-ambulance if the cache
    doesn't have that entry (never prefetched, or a new origin added since)."""
    cache = _load_cache()
    destination = (HOSPITAL["lat"], HOSPITAL["lng"])
    fleet = []
    for i, entry in enumerate(_FLEET):
        name, lat, lng = entry["name"], entry["lat"], entry["lng"]
        cached = cache.get(name)
        if cached:
            route = [tuple(p) for p in cached["route"]]
            distance_km = cached["distance_km"]
        else:
            route = _straight_line((lat, lng), destination)
            distance_km = _haversine_km((lat, lng), destination)
        duration_min = (distance_km / entry["speed_kmh"]) * 60
        fleet.append(Ambulance(
            id=f"amb{i + 1:02d}", display_id=f"AMB {i + 1}", origin_name=name,
            note=entry["note"], route=route, distance_km=round(distance_km, 2),
            depart_min=entry["depart_min"], duration_min=round(duration_min, 1),
            vehicle_number=entry["vehicle_number"], driver=entry["driver"],
            paramedic=entry["paramedic"], vehicle_type=entry["vehicle_type"],
            callsign=entry["callsign"]))
    return fleet


def _bearing(origin: tuple[float, float], point: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(origin[0]), math.radians(origin[1])
    lat2, lon2 = math.radians(point[0]), math.radians(point[1])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def position_at(amb: Ambulance, t: float) -> dict[str, Any]:
    """Interpolates along the pre-fetched polyline by elapsed fraction of
    the trip — same idea as SimPatient.vitals_at(t), over geography rather
    than physiology. Returns bearing + distance from the hospital, never a
    raw lat/lng: the radar view is built to need nothing else."""
    elapsed = t - amb.depart_min
    if elapsed <= 0:
        lat, lng = amb.route[0]
        remaining_km, eta_min, status = amb.distance_km, amb.duration_min, "dispatched"
    elif elapsed >= amb.duration_min:
        lat, lng = amb.route[-1]
        remaining_km, eta_min, status = 0.0, 0.0, "arrived"
    else:
        frac = elapsed / amb.duration_min
        idx = frac * (len(amb.route) - 1)
        lo = int(idx)
        hi = min(lo + 1, len(amb.route) - 1)
        seg_frac = idx - lo
        lat = amb.route[lo][0] + (amb.route[hi][0] - amb.route[lo][0]) * seg_frac
        lng = amb.route[lo][1] + (amb.route[hi][1] - amb.route[lo][1]) * seg_frac
        remaining_km = amb.distance_km * (1 - frac)
        eta_min = amb.duration_min * (1 - frac)
        status = "en_route"

    hospital = (HOSPITAL["lat"], HOSPITAL["lng"])
    return {
        "id": amb.id, "display_id": amb.display_id, "origin": amb.origin_name,
        "note": amb.note, "status": status,
        "distance_km": round(remaining_km, 2), "eta_min": round(max(eta_min, 0.0), 1),
        "bearing": round(_bearing(hospital, (lat, lng)), 1),
        "total_distance_km": amb.distance_km,
        "progress": round(1 - (remaining_km / amb.distance_km if amb.distance_km else 0.0), 3),
        # Dispatch-record detail for the click-through panel — static per
        # ambulance, sent alongside the live fields so the frontend needs
        # no second request to show it.
        "vehicle_number": amb.vehicle_number, "driver": amb.driver,
        "paramedic": amb.paramedic, "vehicle_type": amb.vehicle_type,
        "callsign": amb.callsign,
    }


if __name__ == "__main__":
    prefetch_routes()
