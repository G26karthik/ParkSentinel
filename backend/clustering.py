"""HDBSCAN clustering and H3 hexagonal aggregation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import h3
import hdbscan
import joblib
import numpy as np
import pandas as pd
from scipy import stats

from config import (
    CACHE_DIR,
    H3_PARENT_RESOLUTION,
    H3_RESOLUTION,
    HDBSCAN_MIN_CLUSTER_SIZE,
    HDBSCAN_MIN_SAMPLES,
    USE_GPU,
)

logger = logging.getLogger(__name__)

CLUSTER_CACHE = CACHE_DIR / "clusters_cache.pkl"
H3_CACHE = CACHE_DIR / "h3_cache.pkl"


def _latlon_to_unit_sphere(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Convert lat/lon (degrees) to 3D unit-sphere coords for GPU euclidean clustering."""
    lat_r = np.radians(lat)
    lon_r = np.radians(lon)
    return np.column_stack(
        [
            np.cos(lat_r) * np.cos(lon_r),
            np.cos(lat_r) * np.sin(lon_r),
            np.sin(lat_r),
        ]
    )


def _gpu_hdbscan_available() -> bool:
    """Check if RAPIDS cuML is installed and CUDA is reachable."""
    if not USE_GPU:
        return False
    try:
        import cupy as cp
        from cuml.cluster import HDBSCAN as cuHDBSCAN  # noqa: F401

        cp.cuda.Device(0).compute_capability
        return True
    except Exception:
        return False


def _run_hdbscan_labels(coords_rad: np.ndarray) -> np.ndarray:
    """
    Run HDBSCAN and return cluster labels.
    Uses GPU (cuML) when USE_GPU=true and RAPIDS is installed; otherwise CPU hdbscan.
    """
    if _gpu_hdbscan_available():
        import cupy as cp
        from cuml.cluster import HDBSCAN as cuHDBSCAN

        # Recover degrees from radians for unit-sphere projection
        lat = np.degrees(coords_rad[:, 0])
        lon = np.degrees(coords_rad[:, 1])
        xyz = _latlon_to_unit_sphere(lat, lon).astype(np.float32)

        logger.info("Running GPU HDBSCAN via cuML on %d points (CUDA)...", len(xyz))
        clusterer = cuHDBSCAN(
            min_cluster_size=HDBSCAN_MIN_CLUSTER_SIZE,
            min_samples=HDBSCAN_MIN_SAMPLES,
            metric="euclidean",
            cluster_selection_method="eom",
        )
        labels = clusterer.fit_predict(cp.asarray(xyz))
        if hasattr(labels, "get"):
            labels = labels.get()
        logger.info("GPU HDBSCAN complete")
        return np.asarray(labels, dtype=np.int32)

    logger.info("Running CPU HDBSCAN on %d points...", len(coords_rad))
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=HDBSCAN_MIN_CLUSTER_SIZE,
        min_samples=HDBSCAN_MIN_SAMPLES,
        metric="haversine",
        cluster_selection_method="eom",
        core_dist_n_jobs=-1,
    )
    return clusterer.fit_predict(coords_rad)


def _haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Approximate distance in meters between two lat/lon points."""
    r = 6371000
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def _nearest_junction(
    centroid_lat: float,
    centroid_lon: float,
    junction_df: pd.DataFrame,
    max_dist_m: float = 200,
) -> tuple[str | None, bool]:
    """Find nearest named BTP junction within max_dist_m."""
    if junction_df.empty:
        return None, False

    dists = junction_df.apply(
        lambda r: _haversine_distance_m(centroid_lat, centroid_lon, r["lat"], r["lon"]),
        axis=1,
    )
    idx = dists.idxmin()
    if dists[idx] <= max_dist_m:
        return junction_df.loc[idx, "junction_name"], True
    return None, False


def run_hdbscan_clustering(
    df: pd.DataFrame, use_cache: bool = True
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run HDBSCAN on violation coordinates.
    Returns (df with cluster labels, cluster summary DataFrame).
    """
    if use_cache and CLUSTER_CACHE.exists():
        cached = joblib.load(CLUSTER_CACHE)
        logger.info("Loaded HDBSCAN results from cache (%d clusters)", len(cached["clusters_df"]))
        df = df.copy()
        df["cluster_id"] = cached["labels"]
        return df, cached["clusters_df"]

    logger.info("Running HDBSCAN on %d records...", len(df))

    coords_rad = np.radians(df[["latitude", "longitude"]].values)
    labels = _run_hdbscan_labels(coords_rad)
    df = df.copy()
    df["cluster_id"] = labels

    clustered = df[df["cluster_id"] >= 0].copy()
    n_clusters = clustered["cluster_id"].nunique()
    logger.info("HDBSCAN found %d clusters (%d noise points)", n_clusters, (labels == -1).sum())

    if clustered.empty:
        return df, pd.DataFrame()

    total_days = (df["violation_date"].max() - df["violation_date"].min()).days + 1

    # Junction reference points
    junction_df = (
        df[df["is_junction"]]
        .groupby("junction_name")
        .agg(lat=("latitude", "mean"), lon=("longitude", "mean"), cnt=("id", "count"))
        .reset_index()
        .sort_values("cnt", ascending=False)
    )

    cluster_rows: list[dict[str, Any]] = []
    for cid, grp in clustered.groupby("cluster_id"):
        centroid_lat = grp["latitude"].mean()
        centroid_lon = grp["longitude"].mean()
        junction_name, has_junction = _nearest_junction(centroid_lat, centroid_lon, junction_df)

        vehicle_mix = grp["vehicle_type"].value_counts().to_dict()
        violation_mix = (
            grp.merge(
                grp[["id"]].drop_duplicates(),
                on="id",
            )
        )
        # Get dominant violation from tags if available
        dom_vehicle = grp["vehicle_type"].mode().iloc[0] if len(grp) else None
        peak_hour = int(stats.mode(grp["hour_of_day"], keepdims=False).mode)
        peak_day = int(stats.mode(grp["day_of_week"], keepdims=False).mode)
        unique_days = grp["violation_date"].nunique()

        cluster_rows.append(
            {
                "cluster_id": int(cid),
                "centroid_lat": centroid_lat,
                "centroid_lon": centroid_lon,
                "total_violations": len(grp),
                "weighted_violations": grp["combined_severity"].sum(),
                "unique_days_active": unique_days,
                "persistence_score": unique_days / max(total_days, 1),
                "peak_hour": peak_hour,
                "peak_day": peak_day,
                "has_junction": has_junction or grp["is_junction"].any(),
                "junction_proximity": junction_name,
                "dominant_vehicle_type": dom_vehicle,
                "vehicle_mix": vehicle_mix,
                "police_station": grp["police_station"].mode().iloc[0] if len(grp) else None,
            }
        )

    clusters_df = pd.DataFrame(cluster_rows)

    CLUSTER_CACHE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"labels": labels, "clusters_df": clusters_df}, CLUSTER_CACHE)
    logger.info("Cached HDBSCAN results to %s", CLUSTER_CACHE)

    return df, clusters_df


def compute_h3_aggregation(df: pd.DataFrame, resolution: int = H3_RESOLUTION) -> pd.DataFrame:
    """Aggregate violations per H3 cell."""
    logger.info("Computing H3 aggregation at resolution %d", resolution)

    df = df.copy()
    df["h3_cell"] = df.apply(
        lambda r: h3.latlng_to_cell(r["latitude"], r["longitude"], resolution),
        axis=1,
    )
    df["h3_parent"] = df["h3_cell"].apply(
        lambda c: h3.cell_to_parent(c, H3_PARENT_RESOLUTION)
    )

    # Dominant violation type per record from tags would need join; use placeholder
    agg_rows: list[dict[str, Any]] = []
    for cell, grp in df.groupby("h3_cell"):
        monthly = grp.groupby("month_year").size().to_dict()
        agg_rows.append(
            {
                "h3_cell": cell,
                "h3_parent": grp["h3_parent"].iloc[0],
                "centroid_lat": grp["latitude"].mean(),
                "centroid_lon": grp["longitude"].mean(),
                "violation_count": len(grp),
                "weighted_count": grp["combined_severity"].sum(),
                "unique_vehicles": grp["vehicle_number"].nunique(),
                "unique_days_active": grp["violation_date"].nunique(),
                "peak_hour": int(stats.mode(grp["hour_of_day"], keepdims=False).mode),
                "is_junction_cell": bool(grp["is_junction"].any()),
                "is_peak_hour": bool(grp["is_peak_hour"].any()),
                "monthly_counts": monthly,
                "dominant_vehicle_type": grp["vehicle_type"].mode().iloc[0],
                "police_station": grp["police_station"].mode().iloc[0] if len(grp) else None,
                "has_junction": bool(grp["is_junction"].any()),
            }
        )

    h3_df = pd.DataFrame(agg_rows)
    logger.info("H3 aggregation: %d cells", len(h3_df))
    return h3_df


def add_dominant_violations(h3_df: pd.DataFrame, conn) -> pd.DataFrame:
    """Enrich H3 cells with dominant violation type from violation_tags."""
    import h3 as h3lib

    tag_df = conn.execute(
        """
        SELECT vt.id, vt.violation_label
        FROM violation_tags vt
        """
    ).df()

    viol_df = conn.execute(
        "SELECT id, latitude, longitude FROM violations_clean"
    ).df()

    if tag_df.empty or viol_df.empty:
        h3_df["dominant_violation_type"] = "WRONG PARKING"
        return h3_df

    viol_df["h3_cell"] = viol_df.apply(
        lambda r: h3lib.latlng_to_cell(r["latitude"], r["longitude"], H3_RESOLUTION),
        axis=1,
    )
    merged = viol_df.merge(tag_df, on="id")
    counts = (
        merged.groupby(["h3_cell", "violation_label"])
        .size()
        .reset_index(name="cnt")
    )
    idx = counts.groupby("h3_cell")["cnt"].idxmax()
    dominant = counts.loc[idx, ["h3_cell", "violation_label"]].rename(
        columns={"violation_label": "dominant_violation_type"}
    )
    return h3_df.merge(dominant, on="h3_cell", how="left")


def h3_cell_to_geojson(h3_cell: str) -> dict:
    """Convert H3 cell to GeoJSON polygon."""
    boundary = h3.cell_to_boundary(h3_cell)
    # h3 returns (lat, lon) tuples; GeoJSON wants [lon, lat]
    coords = [[lon, lat] for lat, lon in boundary]
    coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}
