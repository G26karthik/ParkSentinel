"""Anomaly detection on violation time series."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# City-wide anomaly = day whose total exceeds CITY_ROLL_MULT× the trailing 7-day
# mean while also clearing CITY_MIN_TOTAL, so genuine surges flag but sparse
# ramp-up days (a 20-citation day over a near-empty week) do not.
CITY_ROLL_WINDOW = 7
CITY_ROLL_MULT = 2.0
CITY_MIN_TOTAL = 300


def detect_anomalies(df: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Detect city-wide and per-zone anomalies in daily violation counts.
    City-wide uses a trailing 7-day rolling baseline (total > 2x trailing mean,
    with an absolute floor); per-zone uses 2.5x rolling 7-day mean.
    """
    daily = (
        df.groupby("violation_date")
        .size()
        .reset_index(name="total_violations")
        .sort_values("violation_date")
        .reset_index(drop=True)
    )

    if daily.empty:
        return []

    # Trailing baseline: mean/std of the prior CITY_ROLL_WINDOW days (excludes today).
    daily["rolling_baseline"] = (
        daily["total_violations"].rolling(CITY_ROLL_WINDOW, min_periods=4).mean().shift(1)
    )
    daily["rolling_std"] = (
        daily["total_violations"].rolling(CITY_ROLL_WINDOW, min_periods=4).std().shift(1)
    )

    anomalies: list[dict[str, Any]] = []

    for _, row in daily.iterrows():
        baseline = row["rolling_baseline"]
        is_spike = (
            pd.notna(baseline)
            and row["total_violations"] >= CITY_MIN_TOTAL
            and row["total_violations"] > CITY_ROLL_MULT * baseline
        )
        if is_spike:
            # Deviation measured against the local trailing baseline so a flagged
            # surge always reads as a positive sigma, not a negative global z.
            local_std = row["rolling_std"] if pd.notna(row["rolling_std"]) else baseline
            z_score = (row["total_violations"] - baseline) / max(local_std, 1)
            date_str = str(row["violation_date"])[:10]

            # Per-zone spikes
            df[df["violation_date"] == row["violation_date"]]
            affected_zones: list[str] = []

            for station in df["police_station"].dropna().unique():
                station_daily = (
                    df[df["police_station"] == station]
                    .groupby("violation_date")
                    .size()
                    .reset_index(name="cnt")
                    .sort_values("violation_date")
                )
                if len(station_daily) < 7:
                    continue
                station_daily["rolling_mean"] = (
                    station_daily["cnt"].rolling(7, min_periods=3).mean()
                )
                match = station_daily[station_daily["violation_date"] == row["violation_date"]]
                if not match.empty:
                    cnt = match.iloc[0]["cnt"]
                    rolling = match.iloc[0]["rolling_mean"]
                    if rolling and cnt > 2.5 * rolling:
                        affected_zones.append(station)

            ratio = row["total_violations"] / max(baseline, 1)
            zones_txt = f" concentrated in {', '.join(affected_zones[:3])}" if affected_zones else ""
            anomalies.append(
                {
                    "date": date_str,
                    "total_violations": int(row["total_violations"]),
                    "z_score": round(float(z_score), 2),
                    "affected_zones": affected_zones[:10],
                    "likely_cause": (
                        f"Citywide surge: {ratio:.1f}x the trailing 7-day average"
                        f"{zones_txt} (possible event/drive)"
                    ),
                }
            )

    logger.info("Detected %d anomaly dates", len(anomalies))
    return anomalies
