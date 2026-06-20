"""Congestion Impact Score (CIS) computation."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from config import (
    CIS_CRITICAL,
    CIS_HIGH,
    CIS_MODERATE,
    MAX_POSSIBLE_SEVERITY,
)

logger = logging.getLogger(__name__)


def classify_cis(score: float) -> str:
    """Classify CIS score into severity band."""
    if score >= CIS_CRITICAL:
        return "CRITICAL"
    if score >= CIS_HIGH:
        return "HIGH"
    if score >= CIS_MODERATE:
        return "MODERATE"
    return "LOW"


def compute_cis_for_entity(
    violation_count: int,
    avg_severity: float,
    road_weight: float,
    persistence: float,
    is_peak_hour: bool = False,
    has_junction: bool = False,
    max_count: float = 1.0,
) -> dict[str, float]:
    """Compute CIS components and total score for a single entity."""
    # A. Frequency Score (0-25)
    normalized_count = np.log1p(violation_count) / np.log1p(max(max_count, 1))
    frequency_score = min(normalized_count * 25, 25)

    # B. Severity Score (0-25)
    severity_score = min((avg_severity / MAX_POSSIBLE_SEVERITY) * 25, 25)

    # C. Road Criticality Score (0-25)
    road_criticality_score = min(road_weight * 25, 25)

    # D. Temporal Persistence Score (0-25)
    peak_multiplier = 1.3 if is_peak_hour else 1.0
    junction_multiplier = 1.2 if has_junction else 1.0
    temporal_score = min(persistence * peak_multiplier * junction_multiplier * 25, 25)

    total = frequency_score + severity_score + road_criticality_score + temporal_score

    return {
        "cis": round(total, 2),
        "classification": classify_cis(total),
        "frequency_score": round(frequency_score, 2),
        "severity_score": round(severity_score, 2),
        "road_criticality_score": round(road_criticality_score, 2),
        "temporal_score": round(temporal_score, 2),
    }


def score_clusters(
    clusters_df: pd.DataFrame,
    df: pd.DataFrame,
    road_weights: dict[int, float],
    total_days: int,
) -> pd.DataFrame:
    """Apply CIS scoring to HDBSCAN clusters."""
    if clusters_df.empty:
        return clusters_df

    max_count = clusters_df["total_violations"].max()
    results = []

    for _, row in clusters_df.iterrows():
        cid = row["cluster_id"]
        grp = df[df["cluster_id"] == cid]
        avg_severity = grp["combined_severity"].mean() if len(grp) else 1.0
        road_weight = road_weights.get(cid, 0.5)
        persistence = row["unique_days_active"] / max(total_days, 1)
        is_peak = row["peak_hour"] in (7, 8, 9, 17, 18, 19, 20)

        scores = compute_cis_for_entity(
            violation_count=row["total_violations"],
            avg_severity=avg_severity,
            road_weight=road_weight,
            persistence=persistence,
            is_peak_hour=is_peak,
            has_junction=row["has_junction"],
            max_count=max_count,
        )
        results.append({**row.to_dict(), **scores})

    return pd.DataFrame(results)


def score_h3_cells(
    h3_df: pd.DataFrame,
    df: pd.DataFrame,
    road_weights: dict[str, float],
    total_days: int,
) -> pd.DataFrame:
    """Apply CIS scoring to H3 cells."""
    if h3_df.empty:
        return h3_df

    max_count = h3_df["violation_count"].max()
    results = []

    for _, row in h3_df.iterrows():
        cell = row["h3_cell"]
        cell_records = df[df.get("h3_cell", pd.Series()) == cell] if "h3_cell" in df.columns else pd.DataFrame()
        avg_severity = (
            cell_records["combined_severity"].mean()
            if len(cell_records) > 0
            else row["weighted_count"] / max(row["violation_count"], 1)
        )
        road_weight = road_weights.get(cell, 0.5)
        persistence = row["unique_days_active"] / max(total_days, 1)
        is_peak = row.get("peak_hour", 12) in (7, 8, 9, 17, 18, 19, 20)

        scores = compute_cis_for_entity(
            violation_count=row["violation_count"],
            avg_severity=avg_severity,
            road_weight=road_weight,
            persistence=persistence,
            is_peak_hour=is_peak,
            has_junction=row.get("has_junction", False),
            max_count=max_count,
        )
        results.append({**row.to_dict(), **scores})

    return pd.DataFrame(results)
