"""OSMnx road type enrichment with disk cache."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from config import DEFAULT_HIGHWAY_WEIGHT, HIGHWAY_WEIGHTS, OSM_CACHE_PATH

logger = logging.getLogger(__name__)

# Set to True to attempt live OSM fetches (requires internet)
ENABLE_OSM_FETCH = False


def _get_road_weight(highway_tag: Any) -> float:
    """Map OSM highway tag to criticality weight."""
    if highway_tag is None:
        return DEFAULT_HIGHWAY_WEIGHT
    if isinstance(highway_tag, list):
        highway_tag = highway_tag[0] if highway_tag else None
    if highway_tag is None:
        return DEFAULT_HIGHWAY_WEIGHT
    return HIGHWAY_WEIGHTS.get(str(highway_tag).lower(), DEFAULT_HIGHWAY_WEIGHT)


def _heuristic_road_weight(row: pd.Series) -> float:
    """Infer road criticality without OSM when offline."""
    if row.get("is_junction_cell") or row.get("has_junction"):
        return 0.9
    if row.get("violation_count", 0) > 500:
        return 0.8
    if row.get("violation_count", 0) > 200:
        return 0.6
    return DEFAULT_HIGHWAY_WEIGHT


def fetch_road_weight(lat: float, lon: float, dist: int = 100) -> float:
    """Fetch road type from OSMnx for a point. Returns cached weight."""
    if not ENABLE_OSM_FETCH:
        return DEFAULT_HIGHWAY_WEIGHT

    try:
        import osmnx as ox

        ox.settings.timeout = 30
        gdf = ox.features_from_point((lat, lon), tags={"highway": True}, dist=dist)
        if gdf.empty:
            return DEFAULT_HIGHWAY_WEIGHT

        best_weight = DEFAULT_HIGHWAY_WEIGHT
        for _, row in gdf.iterrows():
            w = _get_road_weight(row.get("highway"))
            best_weight = max(best_weight, w)
        return best_weight
    except Exception as e:
        logger.warning("OSM fetch failed for (%.4f, %.4f): %s", lat, lon, e)
        return DEFAULT_HIGHWAY_WEIGHT


def enrich_clusters_with_road_weights(
    clusters_df: pd.DataFrame,
    cache_path: Path | None = None,
) -> dict[int, float]:
    """Assign road weights to cluster centroids."""
    weights: dict[int, float] = {}
    for _, row in clusters_df.iterrows():
        cid = int(row["cluster_id"])
        if row.get("has_junction"):
            weights[cid] = 0.9
        elif row["total_violations"] > 300:
            weights[cid] = 0.8
        else:
            weights[cid] = DEFAULT_HIGHWAY_WEIGHT
    logger.info("Road weights assigned for %d clusters", len(weights))
    return weights


def enrich_h3_with_road_weights(
    h3_df: pd.DataFrame,
    cache_path: Path | None = None,
    max_fetch: int = 50,
) -> dict[str, float]:
    """Assign road weights to H3 cells using heuristics (offline-safe)."""
    weights: dict[str, float] = {}
    for _, row in h3_df.iterrows():
        weights[row["h3_cell"]] = _heuristic_road_weight(row)
    logger.info("Road weights assigned for %d H3 cells", len(weights))
    return weights
