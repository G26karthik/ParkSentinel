"""Prophet time-series forecasting for top H3 cells."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import h3
import joblib
import pandas as pd

from config import PROPHET_CACHE_PATH

logger = logging.getLogger(__name__)


def apply_spatial_smoothing(forecasts: dict[str, Any]) -> dict[str, Any]:
    """Apply first-order spatial neighbor smoothing to Prophet forecasts.

    For each forecasted zone, blends its own forecast with the mean of its
    H3 neighbors' forecasts: smoothed = 0.7 * own + 0.3 * mean(neighbors).
    Zones without forecasted neighbors keep raw Prophet values.
    """
    forecasted_cells = set(forecasts.keys())
    if len(forecasted_cells) < 2:
        return forecasts

    smoothed = {}
    for cell, data in forecasts.items():
        if hasattr(h3, "grid_disk"):
            neighbors = set(h3.grid_disk(cell, 1)) - {cell}
        else:
            neighbors = set(h3.k_ring(cell, 1)) - {cell}
        neighbor_cells = neighbors & forecasted_cells
        if not neighbor_cells:
            smoothed[cell] = data
            continue

        own_fc = data["forecast"]
        neighbor_forecasts = [forecasts[nc]["forecast"] for nc in neighbor_cells]

        blended_fc = []
        for day_idx, day in enumerate(own_fc):
            neighbor_vals = []
            for nf in neighbor_forecasts:
                if day_idx < len(nf):
                    neighbor_vals.append(nf[day_idx])
            if not neighbor_vals:
                blended_fc.append(day)
                continue

            mean_yhat = sum(nv["yhat"] for nv in neighbor_vals) / len(neighbor_vals)
            mean_lower = sum(nv["yhat_lower"] for nv in neighbor_vals) / len(neighbor_vals)
            mean_upper = sum(nv["yhat_upper"] for nv in neighbor_vals) / len(neighbor_vals)

            blended_fc.append({
                "ds": day["ds"],
                "yhat": round(0.7 * day["yhat"] + 0.3 * mean_yhat, 4),
                "yhat_lower": round(0.7 * day["yhat_lower"] + 0.3 * mean_lower, 4),
                "yhat_upper": round(0.7 * day["yhat_upper"] + 0.3 * mean_upper, 4),
            })

        smoothed[cell] = {"forecast": blended_fc, "historical": data["historical"]}

    logger.info("Spatial smoothing applied to %d cells", len(smoothed))
    return smoothed


def _build_daily_series(df: pd.DataFrame, h3_cell: str) -> pd.DataFrame:
    """Build daily violation count series for an H3 cell."""
    cell_df = df[df["h3_cell"] == h3_cell]
    daily = (
        cell_df.groupby("violation_date")
        .size()
        .reset_index(name="y")
        .rename(columns={"violation_date": "ds"})
    )
    daily["ds"] = pd.to_datetime(daily["ds"])
    return daily


def fit_prophet_forecasts(
    h3_df: pd.DataFrame,
    df: pd.DataFrame,
    top_n: int = 20,
    forecast_days: int = 14,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """
    Fit Prophet models for top N H3 cells by CIS.
    Returns dict of {h3_cell: {forecast: [...], historical: [...]}}.
    """
    cache_path = cache_path or PROPHET_CACHE_PATH

    if cache_path.exists():
        cached = joblib.load(cache_path)
        logger.info("Loaded Prophet forecasts from cache (%d cells)", len(cached))
        return cached

    try:
        from prophet import Prophet
    except ImportError:
        logger.warning("Prophet not installed; returning empty forecasts")
        return {}

    top_cells = h3_df.nlargest(top_n, "cis")["h3_cell"].tolist()
    forecasts: dict[str, Any] = {}

    for cell in top_cells:
        daily = _build_daily_series(df, cell)
        if len(daily) < 14:
            continue

        try:
            model = Prophet(
                weekly_seasonality=True,
                daily_seasonality=False,
                changepoint_prior_scale=0.05,
            )
            model.fit(daily)

            future = model.make_future_dataframe(periods=forecast_days)
            pred = model.predict(future)

            historical = daily.tail(180).copy()
            historical["ds"] = historical["ds"].dt.strftime("%Y-%m-%d")

            forecast_part = pred.tail(forecast_days)[
                ["ds", "yhat", "yhat_lower", "yhat_upper"]
            ].copy()
            forecast_part["ds"] = forecast_part["ds"].dt.strftime("%Y-%m-%d")

            forecasts[cell] = {
                "forecast": forecast_part.to_dict(orient="records"),
                "historical": historical.to_dict(orient="records"),
            }
        except Exception as e:
            logger.warning("Prophet failed for cell %s: %s", cell, e)

    forecasts = apply_spatial_smoothing(forecasts)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(forecasts, cache_path)
    logger.info("Prophet forecasts computed and smoothed for %d cells", len(forecasts))
    return forecasts


def get_forecast(forecasts: dict[str, Any], h3_cell: str) -> dict[str, Any] | None:
    """Get forecast for a specific H3 cell."""
    return forecasts.get(h3_cell)


def get_top_forecasts(
    forecasts: dict[str, Any],
    h3_df: pd.DataFrame,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """Get forecasts for top N critical cells."""
    top_cells = h3_df.nlargest(top_n, "cis")["h3_cell"].tolist()
    result = []
    for cell in top_cells:
        if cell in forecasts:
            result.append({"h3_cell": cell, **forecasts[cell]})
    return result
