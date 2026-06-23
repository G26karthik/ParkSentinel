"""Thin Mappls (MapMyIndia) API client for real road distances in patrol routing.

All public functions return None on any failure — callers must fall back to
haversine/heuristic. Never raises. Credentials loaded from env at call time.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_token_cache: dict = {"token": None, "expires_at": 0.0}

_TOKEN_URL = "https://outpost.mappls.com/api/security/oauth/token"
_DISTANCE_MATRIX_URL = (
    "https://apis.mappls.com/advancedmaps/v1/{key}/distance_matrix/driving/{coords}"
)
_REV_GEOCODE_URL = "https://apis.mappls.com/advancedmaps/v1/{key}/rev_geocode"

_ROAD_TYPE_WEIGHTS = {
    "NH": 1.0, "NATIONAL": 1.0,
    "SH": 0.85, "STATE": 0.85,
    "ARTERIAL": 0.75, "MAJOR": 0.75,
    "COLLECTOR": 0.6, "MINOR": 0.6,
}


def get_token() -> Optional[str]:
    """Return cached OAuth2 token, refreshing when expired. Returns None on failure."""
    client_id = os.getenv("MAPPLS_CLIENT_ID")
    client_secret = os.getenv("MAPPLS_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    try:
        resp = requests.post(
            _TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        _token_cache["token"] = data["access_token"]
        _token_cache["expires_at"] = now + data.get("expires_in", 86400)
        logger.info("Mappls token refreshed (expires in %ss)", data.get("expires_in"))
        return _token_cache["token"]
    except Exception as exc:
        logger.warning("Mappls token fetch failed: %s", exc)
        return None


def distance_matrix(
    coords: list[tuple[float, float]],
) -> Optional[list[list[float]]]:
    """
    Real road distance matrix (km) for a list of (lat, lon) pairs.
    Returns NxN list[list[float]] or None on any failure.
    Mappls Distance Matrix API expects lon,lat order, semicolon-separated.
    """
    rest_key = os.getenv("MAPPLS_REST_KEY")
    if not rest_key or len(coords) < 2:
        return None

    coord_str = ";".join(f"{lon},{lat}" for lat, lon in coords)
    url = _DISTANCE_MATRIX_URL.format(key=rest_key, coords=coord_str)

    try:
        resp = requests.get(url, params={"rtype": "0", "region": "IND"}, timeout=25)
        resp.raise_for_status()
        data = resp.json()
        raw_distances = data.get("results", {}).get("distances")
        if not raw_distances:
            logger.warning("Mappls distance_matrix: empty distances in response")
            return None
        n = len(coords)
        matrix = [[0.0] * n for _ in range(n)]
        for i in range(min(n, len(raw_distances))):
            row = raw_distances[i]
            for j in range(min(n, len(row))):
                matrix[i][j] = (row[j] or 0) / 1000.0  # metres -> km
        return matrix
    except Exception as exc:
        logger.warning("Mappls distance_matrix failed: %s", exc)
        return None


def road_class_weight(lat: float, lon: float) -> Optional[float]:
    """
    Road criticality weight (0.0-1.0) for a location via Mappls reverse geocode.
    Returns None on failure; caller uses OSM betweenness / heuristic fallback.
    """
    rest_key = os.getenv("MAPPLS_REST_KEY")
    if not rest_key:
        return None

    try:
        resp = requests.get(
            _REV_GEOCODE_URL.format(key=rest_key),
            params={"lat": lat, "lng": lon, "region": "IND"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return None
        road_type = str(results[0].get("roadType") or results[0].get("subType") or "").upper()
        for keyword, weight in _ROAD_TYPE_WEIGHTS.items():
            if keyword in road_type:
                return weight
        return 0.5
    except Exception as exc:
        logger.warning("Mappls road_class_weight failed (%s,%s): %s", lat, lon, exc)
        return None
