"""ParkSentinel FastAPI application."""

from __future__ import annotations

import logging
import os
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import duckdb
import h3
import joblib
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from clustering import (
    h3_cell_to_geojson,
)
from config import CACHE_DIR, CORS_ORIGINS, HEATMAP_MAX_POINTS, PRODUCT_NAME
from enforcement import generate_enforcement_plan
from forecaster import get_forecast, get_top_forecasts
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
from pdf_generator import generate_patrol_pdf
from query_engine import run_nl_query

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Global state populated at startup
_state: dict[str, Any] = {}


PIPELINE_CACHE = CACHE_DIR / "pipeline_state.pkl"

# ── Artifact bootstrapper (for Render free tier / no persistent disk) ────────
# Set ARTIFACTS_RELEASE_URL in your Render env vars to the GitHub Release
# download URL of your artifact zip, e.g.:
#   https://github.com/G26karthik/ParkSentinel/releases/download/v1.0/artifacts.zip

ARTIFACTS_RELEASE_URL = os.getenv("ARTIFACTS_RELEASE_URL", "")


def _download_file(url: str, dest: Path, label: str) -> bool:
    """Download a single file with progress logging. Returns True on success."""
    try:
        logger.info("Downloading %s from %s ...", label, url)
        tmp = dest.with_suffix(".tmp")

        def _report(block, bsize, total):
            if block % 50 == 0:
                mb = block * bsize / 1e6
                logger.info("  %s: %.1f MB downloaded...", label, mb)

        req = urllib.request.Request(url, headers={"User-Agent": "ParkSentinel/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            logger.info("  %s size: %.1f MB", label, total / 1e6)
            chunk_size = 1024 * 1024  # 1MB
            downloaded = 0
            with open(tmp, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded % (10 * 1024 * 1024) < chunk_size:
                        logger.info("  %s: %.0f / %.0f MB", label, downloaded / 1e6, total / 1e6)
        tmp.rename(dest)
        logger.info("  %s: download complete (%.1f MB)", label, dest.stat().st_size / 1e6)
        return True
    except Exception as e:
        logger.error("Failed to download %s: %s", label, e)
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return False


def download_artifacts():
    """Download pre-built pipeline artifacts from GitHub Releases if not present.
    
    This is the Render free-tier deployment strategy:
    - No persistent disk → artifacts download fresh on each cold start (~15s)
    - ARTIFACTS_RELEASE_URL env var points to GitHub Release download base URL
    - Format: https://github.com/<user>/<repo>/releases/download/<tag>
    """
    if not ARTIFACTS_RELEASE_URL:
        logger.info("ARTIFACTS_RELEASE_URL not set — assuming artifacts are on local disk.")
        return

    base = ARTIFACTS_RELEASE_URL.rstrip("/")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    ARTIFACTS = [
        ("pipeline_state.pkl",   CACHE_DIR / "pipeline_state.pkl"),
        ("parksentinel.duckdb",  CACHE_DIR / "parksentinel.duckdb"),
        ("clusters_cache.pkl",   CACHE_DIR / "clusters_cache.pkl"),
        ("prophet_forecasts.pkl",CACHE_DIR / "prophet_forecasts.pkl"),
    ]

    any_downloaded = False
    for filename, dest in ARTIFACTS:
        if dest.exists():
            logger.info("Artifact %s already present — skipping download.", filename)
            continue
        url = f"{base}/{filename}"
        ok = _download_file(url, dest, filename)
        if ok:
            any_downloaded = True
        else:
            logger.error("CRITICAL: Could not fetch artifact %s — server may fail to start.", filename)

    if any_downloaded:
        logger.info("All artifacts downloaded from GitHub Releases.")


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
    # Step 0: Download artifacts from GitHub Releases if not on local disk
    # (Required for Render free tier which has no persistent disk)
    download_artifacts()

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


_CACHED_PREFIXES = (
    "/hotspots", "/h3-grid", "/summary/", "/enforcement-plan",
    "/forecast/", "/anomalies", "/heatmap-data",
)


@app.middleware("http")
async def add_cache_and_product_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Product"] = PRODUCT_NAME
    path = request.url.path
    if any(path == p or path.startswith(p) for p in _CACHED_PREFIXES):
        response.headers["Cache-Control"] = (
            "public, max-age=3600, stale-while-revalidate=86400"
        )
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
                    "police_station": row.get("police_station"),
                    "zone_name": _resolve_zone_name(row["h3_cell"], filtered),
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
        # Append short h3 suffix so multiple cells in the same station area get unique names
        station = row.get('police_station', 'Bengaluru')
        zone_name = f"{station} ({h3_cell[-8:-5]})"
    return str(zone_name)


# NOTE: the static /forecast/top route MUST be declared before the dynamic
# /forecast/{h3_cell} route, otherwise "top" is captured as an h3_cell and 404s.
@app.get("/forecast/top", response_model=TopForecastResponse)
async def get_top_cell_forecasts():
    forecasts = _state.get("forecasts", {})
    h3_df = _state.get("h3_df", pd.DataFrame())
    top = get_top_forecasts(forecasts, h3_df, top_n=20)
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


@app.get("/enforcement-plan/pdf")
async def get_enforcement_plan_pdf(
    target_date: str | None = Query(None, alias="date"),
    police_station: str | None = None,
    top_n: int = Query(10, ge=1, le=50),
):
    """Download patrol enforcement brief as a PDF."""
    h3_df = _state.get("h3_df", pd.DataFrame())
    df = _state.get("df", pd.DataFrame())
    plan = generate_enforcement_plan(h3_df, df, target_date, police_station, top_n)
    pdf_bytes = generate_patrol_pdf(plan)
    filename = f"patrol_brief_{plan.get('date', 'today')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/export/astram")
async def export_astram(
    target_date: str | None = Query(None, alias="date"),
    police_station: str | None = None,
    top_n: int = Query(10, ge=1, le=50),
):
    """
    Export enforcement plan as GeoJSON FeatureCollection for ASTraM ingestion.
    ASTraM is BTP's own AI traffic platform (Actionable Intelligence for
    Sustainable Traffic Management). This endpoint provides the parking-enforcement
    layer that ASTraM can overlay on its real-time situational awareness picture.
    The dataset's data_sent_to_scita field is the existing BTP integration seam.
    """
    h3_df = _state.get("h3_df", pd.DataFrame())
    df = _state.get("df", pd.DataFrame())
    plan = generate_enforcement_plan(h3_df, df, target_date, police_station, top_n)

    features = []
    for item in plan.get("items", []):
        lat = item.get("centroid_lat")
        lon = item.get("centroid_lon")
        if lat is None or lon is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "zone_name": item.get("zone_name"),
                "h3_cell": item.get("h3_cell"),
                "cis": item.get("cis"),
                "classification": item.get("classification"),
                "rank": item.get("rank"),
                "recommended_officers": item.get("recommended_officers"),
                "recommended_shift": item.get("recommended_shift"),
                "dominant_violation": item.get("dominant_violation"),
                "dominant_vehicle": item.get("dominant_vehicle"),
                "trend": item.get("trend"),
                "police_station": item.get("police_station"),
                "source": "ParkSentinel",
                "astram_layer": "parking_enforcement",
            },
        })

    # Route line if VRP was solved
    route_items = plan.get("items", [])
    route_coords = [
        [item["centroid_lon"], item["centroid_lat"]]
        for item in route_items
        if item.get("centroid_lat") and item.get("centroid_lon")
    ]
    if len(route_coords) >= 2:
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": route_coords},
            "properties": {
                "type": "patrol_route",
                "estimated_travel_km": plan.get("estimated_travel_km"),
                "naive_travel_km": plan.get("naive_travel_km"),
                "time_saved_pct": plan.get("time_saved_pct"),
                "route_optimized": plan.get("route_optimized"),
                "distance_source": plan.get("distance_source", "haversine"),
                "source": "ParkSentinel",
                "astram_layer": "parking_enforcement_route",
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "date": plan.get("date"),
            "total_officers": plan.get("total_officers"),
            "zones_count": plan.get("zones_count"),
            "generated_by": "ParkSentinel",
            "integration_note": (
                "Parking enforcement intelligence for ASTraM overlay. "
                "data_sent_to_scita field in source dataset is the existing BTP integration seam."
            ),
        },
    }


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

    if len(filtered) > HEATMAP_MAX_POINTS:
        filtered = filtered.sample(n=HEATMAP_MAX_POINTS, random_state=42)

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
