"""Pydantic response models for ParkSentinel API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    records_loaded: int
    clusters_computed: int
    product: str = "ParkSentinel"


class HotspotProperties(BaseModel):
    cluster_id: int
    cis: float
    classification: str
    total_violations: int
    weighted_violations: float
    centroid_lat: float
    centroid_lon: float
    unique_days_active: int
    persistence_score: float
    peak_hour: int
    peak_day: int
    has_junction: bool
    junction_proximity: str | None = None
    dominant_vehicle_type: str | None = None
    dominant_violation_type: str | None = None
    frequency_score: float = 0
    severity_score: float = 0
    road_criticality_score: float = 0
    temporal_score: float = 0
    recommended_officers: int = 1
    recommended_shift: str = "morning"
    trend: str = "stable"
    police_station: str | None = None
    h3_cell: str | None = None


class HotspotFeature(BaseModel):
    type: str = "Feature"
    geometry: dict[str, Any]
    properties: HotspotProperties


class HotspotsResponse(BaseModel):
    type: str = "FeatureCollection"
    features: list[HotspotFeature]


class H3CellProperties(BaseModel):
    h3_cell: str
    violation_count: int
    weighted_count: float
    cis: float
    classification: str
    dominant_vehicle_type: str | None = None
    dominant_violation_type: str | None = None
    peak_hour: int | None = None
    is_junction_cell: bool = False
    monthly_counts: dict[str, int] = Field(default_factory=dict)
    unique_vehicles: int = 0


class H3GridResponse(BaseModel):
    type: str = "FeatureCollection"
    features: list[dict[str, Any]]


class ForecastPoint(BaseModel):
    ds: str
    yhat: float
    yhat_lower: float
    yhat_upper: float


class ForecastResponse(BaseModel):
    h3_cell: str
    forecast: list[ForecastPoint]
    historical: list[dict[str, Any]] = Field(default_factory=list)
    zone_name: str | None = None


class TopForecastResponse(BaseModel):
    forecasts: list[ForecastResponse]


class EnforcementItem(BaseModel):
    rank: int
    zone_name: str
    cis: float
    classification: str
    total_violations: int
    recommended_officers: int
    recommended_shift: str
    dominant_violation: str | None = None
    dominant_vehicle: str | None = None
    trend: str = "stable"
    centroid_lat: float
    centroid_lon: float
    police_station: str | None = None
    h3_cell: str | None = None


class EnforcementPlanResponse(BaseModel):
    date: str
    total_officers: int
    zones_count: int
    items: list[EnforcementItem]


class AnomalyRecord(BaseModel):
    date: str
    total_violations: int
    z_score: float
    affected_zones: list[str]
    likely_cause: str


class AnomaliesResponse(BaseModel):
    anomalies: list[AnomalyRecord]


class SummaryStats(BaseModel):
    total_violations: int
    total_approved: int
    unique_junctions: int
    critical_zones_count: int
    peak_hour_citywide: int | None
    most_active_station: str | None
    date_range: dict[str, str | None]


class StationSummary(BaseModel):
    police_station: str
    violation_count: int
    avg_cis: float
    critical_count: int


class VehicleSummary(BaseModel):
    vehicle_type: str
    violation_count: int
    avg_cis: float


class HourSummary(BaseModel):
    hour: int
    count: int


class QueryRequest(BaseModel):
    question: str
    # Optional: enables per-session conversation memory for follow-up questions.
    # Existing clients that send only {"question": ...} keep working unchanged.
    session_id: str | None = None


class QueryResponse(BaseModel):
    sql: str
    answer: str
    data: list[dict[str, Any]]
    row_count: int


class HeatmapPoint(BaseModel):
    lat: float
    lon: float
    weight: float = 1.0


class HeatmapResponse(BaseModel):
    points: list[HeatmapPoint]
    total_sampled: int
