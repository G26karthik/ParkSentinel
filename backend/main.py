"""ParkSentinel FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import duckdb
import h3
import joblib
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from anomaly_detector import detect_anomalies
from clustering import (
    add_dominant_violations,
    compute_h3_aggregation,
    h3_cell_to_geojson,
    run_hdbscan_clustering,
)
from config import CACHE_DIR, CORS_ORIGINS, H3_RESOLUTION, PRODUCT_NAME
from data_loader import get_clean_violations_df, get_data_stats, load_csv_to_duckdb
from enforcement import generate_enforcement_plan
from forecaster import fit_prophet_forecasts, get_forecast, get_top_forecasts
from models import (
    AnomaliesResponse,
    EnforcementPlanResponse,
    ForecastResponse,
    HealthResponse,
    HeatmapResponse,
    HotspotsResponse,
    H3GridResponse,
    QueryRequest,
    QueryResponse,
    SummaryStats,
    TopForecastResponse,
)
from osm_enricher import enrich_h3_with_road_weights
from query_engine import run_nl_query
from scoring import score_clusters, score_h3_cells

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Global state populated at startup
_state: dict[str, Any] = {}


PIPELINE_CACHE = CACHE_DIR / "pipeline_state.pkl"


def load_offline_state():
    """Load pre-computed offline pipeline state into memory."""
    if not PIPELINE_CACHE.exists():
        logger.error("CRITICAL: pipeline_state.pkl not found in %s", CACHE_DIR)
        logger.error("You MUST run 'python offline_pipeline.py' before starting the server.")
        raise RuntimeError("Missing offline pipeline cache.")
        
    logger.info("Loading offline pipeline state from cache...")
    cached = joblib.load(PIPELINE_CACHE)
    _state.update(cached)
    
    n_clusters = len(_state.get("clusters_df", pd.DataFrame()))
    logger.info(
        "System ready (read-only mode). %d clusters. %d critical zones.",
        n_clusters,
        _state.get("critical_count", 0),
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connect to read-only duckdb database created by offline pipeline
    from config import DUCKDB_PATH
    if not DUCKDB_PATH.exists():
        logger.error("CRITICAL: DuckDB database not found at %s", DUCKDB_PATH)
        raise RuntimeError("Missing DuckDB database.")
        
    conn = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    _state["conn"] = conn
    
    load_offline_state()
    yield
    conn.close()


app = FastAPI(
    title=PRODUCT_NAME,
    description="AI-powered parking enforcement intelligence for Bengaluru",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_product_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Product"] = PRODUCT_NAME
    return response


@app.get("/health", response_model=HealthResponse)
async def health():
    from clustering import _gpu_hdbscan_available

    stats = _state.get("stats", {})
    clusters = _state.get("clusters_df", pd.DataFrame())
    response = HealthResponse(
        status="ok",
        records_loaded=stats.get("total_approved", 0),
        clusters_computed=len(clusters) if not clusters.empty else 0,
    )
    # Expose GPU status for debugging (not in pydantic model — use headers)
    return JSONResponse(
        content=response.model_dump(),
        headers={
            "X-Product": PRODUCT_NAME,
            "X-GPU-Enabled": str(_gpu_hdbscan_available()).lower(),
        },
    )


@app.get("/hotspots", response_model=HotspotsResponse)
async def get_hotspots(
    limit: int = Query(20, ge=1, le=100),
    min_cis: float = Query(0, ge=0, le=100),
    police_station: str | None = None,
    month: str | None = None,
    vehicle_type: str | None = None,
):
    clusters_df = _state.get("clusters_df", pd.DataFrame())
    df = _state.get("df", pd.DataFrame())

    if clusters_df.empty:
        return HotspotsResponse(features=[])

    filtered = clusters_df[clusters_df["cis"] >= min_cis].copy()

    if police_station:
        filtered = filtered[filtered["police_station"] == police_station]

    if month and not df.empty:
        month_ids = set(df[df["month_year"] == month]["id"].tolist())
        cluster_ids = (
            df[df["id"].isin(month_ids) & (df["cluster_id"] >= 0)]
            .groupby("cluster_id")
            .size()
            .index.tolist()
        )
        filtered = filtered[filtered["cluster_id"].isin(cluster_ids)]

    if vehicle_type and not df.empty:
        vt_ids = set(df[df["vehicle_type"] == vehicle_type]["id"].tolist())
        cluster_ids = (
            df[df["id"].isin(vt_ids) & (df["cluster_id"] >= 0)]
            .groupby("cluster_id")
            .size()
            .index.tolist()
        )
        filtered = filtered[filtered["cluster_id"].isin(cluster_ids)]

    top = filtered.nlargest(limit, "cis")
    features = []
    for _, row in top.iterrows():
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [row["centroid_lon"], row["centroid_lat"]],
                },
                "properties": {
                    "cluster_id": int(row["cluster_id"]),
                    "cis": row["cis"],
                    "classification": row["classification"],
                    "total_violations": int(row["total_violations"]),
                    "weighted_violations": float(row.get("weighted_violations", 0)),
                    "centroid_lat": row["centroid_lat"],
                    "centroid_lon": row["centroid_lon"],
                    "unique_days_active": int(row["unique_days_active"]),
                    "persistence_score": float(row["persistence_score"]),
                    "peak_hour": int(row["peak_hour"]),
                    "peak_day": int(row["peak_day"]),
                    "has_junction": bool(row["has_junction"]),
                    "junction_proximity": row.get("junction_proximity"),
                    "dominant_vehicle_type": row.get("dominant_vehicle_type"),
                    "dominant_violation_type": row.get("dominant_violation_type"),
                    "frequency_score": float(row.get("frequency_score", 0)),
                    "severity_score": float(row.get("severity_score", 0)),
                    "road_criticality_score": float(row.get("road_criticality_score", 0)),
                    "temporal_score": float(row.get("temporal_score", 0)),
                    "police_station": row.get("police_station"),
                },
            }
        )

    return HotspotsResponse(features=features)


@app.get("/h3-grid", response_model=H3GridResponse)
async def get_h3_grid(
    resolution: int = Query(8, ge=7, le=9),
    month: str | None = None,
    min_count: int = Query(5, ge=1),
):
    h3_df = _state.get("h3_df", pd.DataFrame())
    df = _state.get("df", pd.DataFrame())

    if h3_df.empty:
        return H3GridResponse(features=[])

    if month and not df.empty:
        month_cells = set(
            df[df["month_year"] == month]
            .apply(lambda r: h3.latlng_to_cell(r["latitude"], r["longitude"], resolution), axis=1)
        )
        filtered = h3_df[h3_df["h3_cell"].isin(month_cells)]
    else:
        filtered = h3_df

    filtered = filtered[filtered["violation_count"] >= min_count]

    features = []
    for _, row in filtered.iterrows():
        try:
            geom = h3_cell_to_geojson(row["h3_cell"])
        except Exception:
            continue
        monthly = row.get("monthly_counts", {})
        if isinstance(monthly, str):
            import json

            monthly = json.loads(monthly)

        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "h3_cell": row["h3_cell"],
                    "violation_count": int(row["violation_count"]),
                    "weighted_count": float(row["weighted_count"]),
                    "cis": float(row["cis"]),
                    "classification": row["classification"],
                    "dominant_vehicle_type": row.get("dominant_vehicle_type"),
                    "dominant_violation_type": row.get("dominant_violation_type"),
                    "peak_hour": int(row.get("peak_hour", 0)),
                    "is_junction_cell": bool(row.get("is_junction_cell", False)),
                    "monthly_counts": monthly if isinstance(monthly, dict) else {},
                    "unique_vehicles": int(row.get("unique_vehicles", 0)),
                    "centroid_lat": row["centroid_lat"],
                    "centroid_lon": row["centroid_lon"],
                },
            }
        )

    return H3GridResponse(features=features)


def _resolve_zone_name(h3_cell: str, h3_df: pd.DataFrame) -> str:
    if h3_df.empty:
        return h3_cell
    match = h3_df[h3_df["h3_cell"] == h3_cell]
    if match.empty:
        return h3_cell
    row = match.iloc[0]
    zone_name = row.get("junction_proximity") or row.get("police_station") or h3_cell
    if row.get("is_junction_cell") or (isinstance(zone_name, str) and zone_name == 'No Junction'):
        zone_name = f"H3 Zone near {row.get('police_station', 'Bengaluru')}"
    return str(zone_name)


# NOTE: the static /forecast/top route MUST be declared before the dynamic
# /forecast/{h3_cell} route, otherwise "top" is captured as an h3_cell and 404s.
@app.get("/forecast/top", response_model=TopForecastResponse)
async def get_top_cell_forecasts():
    forecasts = _state.get("forecasts", {})
    h3_df = _state.get("h3_df", pd.DataFrame())
    top = get_top_forecasts(forecasts, h3_df, top_n=10)
    return TopForecastResponse(
        forecasts=[
            ForecastResponse(
                h3_cell=f["h3_cell"],
                forecast=f.get("forecast", []),
                historical=f.get("historical", []),
                zone_name=_resolve_zone_name(f["h3_cell"], h3_df),
            )
            for f in top
        ]
    )


@app.get("/forecast/{h3_cell}", response_model=ForecastResponse)
async def get_cell_forecast(h3_cell: str):
    forecasts = _state.get("forecasts", {})
    h3_df = _state.get("h3_df", pd.DataFrame())
    data = get_forecast(forecasts, h3_cell)
    if not data:
        raise HTTPException(status_code=404, detail=f"No forecast for cell {h3_cell}")
    return ForecastResponse(
        h3_cell=h3_cell,
        forecast=data.get("forecast", []),
        historical=data.get("historical", []),
        zone_name=_resolve_zone_name(h3_cell, h3_df),
    )


@app.get("/enforcement-plan", response_model=EnforcementPlanResponse)
async def get_enforcement_plan(
    target_date: str | None = Query(None, alias="date"),
    police_station: str | None = None,
    top_n: int = Query(10, ge=1, le=50),
):
    h3_df = _state.get("h3_df", pd.DataFrame())
    df = _state.get("df", pd.DataFrame())
    plan = generate_enforcement_plan(h3_df, df, target_date, police_station, top_n)
    return EnforcementPlanResponse(**plan)


@app.get("/anomalies", response_model=AnomaliesResponse)
async def get_anomalies():
    return AnomaliesResponse(anomalies=_state.get("anomalies", []))


@app.get("/summary/stats", response_model=SummaryStats)
async def get_summary_stats():
    stats = _state.get("stats", {})
    conn = _state.get("conn")
    total = 0
    if conn:
        total = conn.execute("SELECT COUNT(*) FROM violations_raw").fetchone()[0]

    return SummaryStats(
        total_violations=total,
        total_approved=stats.get("total_approved", 0),
        unique_junctions=stats.get("unique_junctions", 0),
        critical_zones_count=_state.get("critical_count", 0),
        peak_hour_citywide=stats.get("peak_hour_citywide"),
        most_active_station=stats.get("most_active_station"),
        date_range={
            "start": stats.get("date_min"),
            "end": stats.get("date_max"),
        },
    )


@app.get("/summary/by-station")
async def get_summary_by_station():
    h3_df = _state.get("h3_df", pd.DataFrame())
    if h3_df.empty:
        return []

    result = (
        h3_df.groupby("police_station")
        .agg(
            violation_count=("violation_count", "sum"),
            avg_cis=("cis", "mean"),
            critical_count=("classification", lambda x: (x == "CRITICAL").sum()),
        )
        .reset_index()
        .sort_values("violation_count", ascending=False)
    )
    return result.to_dict(orient="records")


@app.get("/summary/by-vehicle")
async def get_summary_by_vehicle():
    df = _state.get("df", pd.DataFrame())
    h3_df = _state.get("h3_df", pd.DataFrame())
    if df.empty:
        return []

    avg_cis = h3_df["cis"].mean() if not h3_df.empty else 50.0
    result = (
        df.groupby("vehicle_type")
        .size()
        .reset_index(name="violation_count")
        .sort_values("violation_count", ascending=False)
    )
    result["avg_cis"] = avg_cis
    return result.to_dict(orient="records")


@app.get("/summary/by-hour")
async def get_summary_by_hour():
    df = _state.get("df", pd.DataFrame())
    if df.empty:
        return []

    result = (
        df.groupby("hour_of_day")
        .size()
        .reset_index(name="count")
        .rename(columns={"hour_of_day": "hour"})
        .sort_values("hour")
    )
    return result.to_dict(orient="records")


@app.post("/query", response_model=QueryResponse)
async def nl_query(body: QueryRequest):
    conn = _state.get("conn")
    if not conn:
        raise HTTPException(status_code=503, detail="Database not ready")
    try:
        result = run_nl_query(conn, body.question)
        return QueryResponse(**result)
    except RuntimeError as e:
        return QueryResponse(
            sql="",
            answer=str(e),
            data=[],
            row_count=0,
        )


@app.get("/heatmap-data", response_model=HeatmapResponse)
async def get_heatmap_data(
    month: str | None = None,
    police_station: str | None = None,
):
    df = _state.get("df", pd.DataFrame())
    if df.empty:
        return HeatmapResponse(points=[], total_sampled=0)

    filtered = df.copy()
    if month:
        filtered = filtered[filtered["month_year"] == month]
    if police_station:
        filtered = filtered[filtered["police_station"] == police_station]

    max_points = 50000
    if len(filtered) > max_points:
        filtered = filtered.sample(n=max_points, random_state=42)

    points = [
        {"lat": row["latitude"], "lon": row["longitude"], "weight": 1.0}
        for _, row in filtered.iterrows()
    ]
    return HeatmapResponse(points=points, total_sampled=len(points))


@app.get("/summary/junctions")
async def get_top_junctions(limit: int = Query(20, ge=1, le=50)):
    conn = _state.get("conn")
    if not conn:
        return []
    rows = conn.execute(
        """
        SELECT junction_name, COUNT(*) AS violation_count,
               AVG(latitude) AS lat, AVG(longitude) AS lon
        FROM violations_clean
        WHERE is_junction = true
        GROUP BY junction_name
        ORDER BY violation_count DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    return [
        {
            "junction_name": r[0],
            "violation_count": r[1],
            "lat": r[2],
            "lon": r[3],
        }
        for r in rows
    ]


@app.get("/summary/daily")
async def get_daily_trend():
    df = _state.get("df", pd.DataFrame())
    if df.empty:
        return []
    daily = (
        df.groupby("violation_date")
        .size()
        .reset_index(name="count")
        .sort_values("violation_date")
    )
    daily["violation_date"] = daily["violation_date"].astype(str)
    return daily.to_dict(orient="records")


@app.get("/summary/by-dow")
async def get_summary_by_dow():
    df = _state.get("df", pd.DataFrame())
    if df.empty:
        return []
    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    result = (
        df.groupby("day_of_week")
        .size()
        .reset_index(name="count")
        .sort_values("day_of_week")
    )
    result["day_name"] = result["day_of_week"].apply(lambda x: dow_names[x])
    return result.to_dict(orient="records")


@app.get("/summary/by-month")
async def get_summary_by_month():
    df = _state.get("df", pd.DataFrame())
    if df.empty:
        return []
    result = (
        df.groupby("month_year")
        .size()
        .reset_index(name="count")
        .sort_values("month_year")
    )
    return result.to_dict(orient="records")


@app.get("/summary/by-violation-type")
async def get_summary_by_violation_type():
    conn = _state.get("conn")
    if not conn:
        return []
    rows = conn.execute(
        """
        SELECT violation_label, COUNT(*) AS count
        FROM violation_tags
        GROUP BY violation_label
        ORDER BY count DESC
        LIMIT 15
        """
    ).fetchall()
    return [{"violation_type": r[0], "count": r[1]} for r in rows]
