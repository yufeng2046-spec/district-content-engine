"""Gaode Map API client for POI search and geocoding."""

import time
from typing import Optional

import requests

from config import GAODE_KEY

BASE_URL = "https://restapi.amap.com/v3"


def _call(endpoint: str, params: dict) -> dict:
    params["key"] = GAODE_KEY
    resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "1":
        raise RuntimeError(f"Gaode API error: {data.get('info', 'unknown')}")
    return data


def geocode(address: str, city: str = "咸阳") -> Optional[tuple[float, float]]:
    """Convert address to (lng, lat)."""
    data = _call("geocode/geo", {"address": address, "city": city})
    geos = data.get("geocodes", [])
    if geos:
        loc = geos[0]["location"]
        lng, lat = loc.split(",")
        return float(lng), float(lat)
    return None


def search_poi(
    lng: float,
    lat: float,
    keywords: str,
    radius: int = 1000,
    types: str = "",
    limit: int = 5,
) -> list[dict]:
    """Search POI around a location. Returns list of {name, lng, lat, distance_m, address}."""
    location = f"{lng},{lat}"
    params = {
        "location": location,
        "keywords": keywords,
        "radius": radius,
        "offset": limit,
        "page": 1,
        "extensions": "all",
    }
    if types:
        params["types"] = types

    data = _call("place/around", params)
    results = []
    for p in data.get("pois", []):
        name = p["name"]
        ploc = p["location"]
        plng, plat = ploc.split(",")
        dist = int(p.get("distance", 0))
        results.append({
            "name": name,
            "lng": float(plng),
            "lat": float(plat),
            "distance_m": dist,
            "address": p.get("address", ""),
        })
    return results


def walking_distance(origin: tuple[float, float], dest: tuple[float, float]) -> Optional[dict]:
    """Calculate walking distance and time between two points."""
    params = {
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{dest[0]},{dest[1]}",
    }
    try:
        data = _call("direction/walking", params)
        route = data.get("route", {})
        paths = route.get("paths", [])
        if paths:
            return {
                "distance_m": int(paths[0]["distance"]),
                "duration_min": int(paths[0]["duration"]) // 60,
            }
    except Exception:
        pass
    return None


def search_communities(city: str, district: str = "", limit: int = 30) -> list[dict]:
    """Search residential communities by city/district using text search."""
    keywords = f"{district} 住宅小区" if district else "住宅小区"
    params = {
        "keywords": keywords,
        "types": "120300",  # 住宅小区
        "region": f"{city}{district}" if district else city,
        "citylimit": "true",
        "offset": limit,
        "page": 1,
        "extensions": "all",
    }
    data = _call("place/text", params)
    results = []
    for p in data.get("pois", []):
        loc = p["location"]
        lng, lat = loc.split(",")
        results.append({
            "name": p["name"],
            "address": p.get("address", ""),
            "lng": float(lng),
            "lat": float(lat),
        })
    return results
