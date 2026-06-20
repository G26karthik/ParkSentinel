"""Enforcement recommendation engine."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import pandas as pd

from config import PEAK_HOURS

logger = logging.getLogger(__name__)


def _shift_from_peak_hour(hour: int) -> str:
    if 7 <= hour <= 11:
        return "morning (7-11am)"
    if 12 <= hour <= 16:
        return "afternoon (12-4pm)"
    return "evening (5-9pm)"


def _officers_from_classification(classification: str) -> int:
    return {"CRITICAL": 3, "HIGH": 2, "MODERATE": 1}.get(classification, 1)


def _compute_trend(df: pd.DataFrame, h3_cell: str | None, cluster_id: int | None) -> str:
    """Compare last 2 weeks vs prior 2 weeks."""
    if h3_cell and "h3_cell" in df.columns:
        cell_df = df[df["h3_cell"] == h3_cell]
    elif cluster_id is not None and "cluster_id" in df.columns:
        cell_df = df[df["cluster_id"] == cluster_id]
    else:
        return "stable"

    if cell_df.empty:
        return "stable"

    max_date = cell_df["violation_date"].max()
    if pd.isna(max_date):
        return "stable"

    recent_start = max_date - pd.Timedelta(days=14)
    prior_start = max_date - pd.Timedelta(days=28)

    recent = len(cell_df[cell_df["violation_date"] > recent_start])
    prior = len(
        cell_df[
            (cell_df["violation_date"] > prior_start)
            & (cell_df["violation_date"] <= recent_start)
        ]
    )

    if prior == 0:
        return "worsening" if recent > 0 else "stable"
    ratio = recent / prior
    if ratio > 1.15:
        return "worsening"
    if ratio < 0.85:
        return "improving"
    return "stable"


def generate_enforcement_plan(
    h3_df: pd.DataFrame,
    df: pd.DataFrame,
    target_date: str | None = None,
    police_station: str | None = None,
    top_n: int = 10,
    current_hour: int | None = None,
) -> dict[str, Any]:
    """Generate ranked enforcement plan."""
    filtered = h3_df.copy()
    if police_station:
        filtered = filtered[filtered["police_station"] == police_station]

    if current_hour is None:
        current_hour = datetime.now().hour

    # Peak hour boost
    def boosted_cis(row: pd.Series) -> float:
        cis = row["cis"]
        if current_hour in PEAK_HOURS:
            cis *= 1.3
        return cis

    filtered = filtered.copy()
    filtered["boosted_cis"] = filtered.apply(boosted_cis, axis=1)
    top = filtered.nlargest(top_n, "boosted_cis")

    items: list[dict[str, Any]] = []
    for rank, (_, row) in enumerate(top.iterrows(), 1):
        zone_name = row.get("junction_proximity") or row.get("police_station") or row["h3_cell"]
        if row.get("is_junction_cell"):
            zone_name = f"H3 Zone near {row.get('police_station', 'Bengaluru')}"

        trend = _compute_trend(df, row["h3_cell"], None)
        items.append(
            {
                "rank": rank,
                "zone_name": str(zone_name),
                "cis": round(row["cis"], 2),
                "classification": row["classification"],
                "total_violations": int(row["violation_count"]),
                "recommended_officers": _officers_from_classification(row["classification"]),
                "recommended_shift": _shift_from_peak_hour(int(row.get("peak_hour", 8))),
                "dominant_violation": row.get("dominant_violation_type", "WRONG PARKING"),
                "dominant_vehicle": row.get("dominant_vehicle_type", "CAR"),
                "trend": trend,
                "centroid_lat": row["centroid_lat"],
                "centroid_lon": row["centroid_lon"],
                "police_station": row.get("police_station"),
                "h3_cell": row["h3_cell"],
            }
        )

    total_officers = sum(i["recommended_officers"] for i in items)
    plan_date = target_date or date.today().isoformat()

    return {
        "date": plan_date,
        "total_officers": total_officers,
        "zones_count": len(items),
        "items": items,
    }
