"""Enforcement recommendation engine.

Design notes (01-system-design):
  Load: <10 RPS (pre-computed offline, served read-only). VRP runs on 10-20 nodes max.
  Volume: Distance matrix fits in memory (20x20 floats). No paging needed.
  Concurrency: Stateless pure function, safe for concurrent calls.
  Latency: OR-Tools TSP on 20 nodes < 100ms. 5s hard cap via time limit.
  Backpressure: N/A (not queued work).
  Failure blast radius: Falls back to nearest-neighbor heuristic. Never blocks plan generation.
  Next bottleneck: If node count grows past ~200, switch to metaheuristic or chunk into sub-tours.
  Render: Single patrol route returned, not paginated.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from math import atan2, cos, radians, sin, sqrt
from typing import Any

import pandas as pd

from config import PEAK_HOURS
import mappls_client

logger = logging.getLogger(__name__)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def _nearest_neighbor_tsp(dist_matrix: list[list[int]]) -> list[int]:
    """Greedy nearest-neighbor TSP heuristic. O(n^2), good enough for n<50."""
    n = len(dist_matrix)
    if n <= 1:
        return list(range(n))
    visited = [False] * n
    order = [0]
    visited[0] = True
    for _ in range(n - 1):
        last = order[-1]
        best_next = -1
        best_dist = float("inf")
        for j in range(n):
            if not visited[j] and dist_matrix[last][j] < best_dist:
                best_dist = dist_matrix[last][j]
                best_next = j
        order.append(best_next)
        visited[best_next] = True
    return order


def solve_patrol_route(zones: list[dict]) -> dict:
    """Solve TSP for patrol zone visit order using OR-Tools with nearest-neighbor fallback.

    Args:
        zones: list of dicts, each must have 'centroid_lat' and 'centroid_lon'.

    Returns:
        dict with ordered_indices, total_distance_km, naive_distance_km, time_saved_pct,
        and route_optimized (bool indicating whether OR-Tools or fallback was used).
    """
    n = len(zones)
    if n <= 1:
        return {
            "ordered_indices": list(range(n)),
            "total_distance_km": 0.0,
            "naive_distance_km": 0.0,
            "time_saved_pct": 0.0,
            "route_optimized": False,
        }

    # Build distance matrix — try Mappls real road distances first, fall back to haversine
    coords = [(z["centroid_lat"], z["centroid_lon"]) for z in zones]
    mappls_matrix = mappls_client.distance_matrix(coords)
    if mappls_matrix:
        dist_km = mappls_matrix
        distance_source = "mappls_road"
        logger.info("Using Mappls real road distance matrix (%dx%d)", n, n)
    else:
        dist_km = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                d = _haversine_km(
                    zones[i]["centroid_lat"], zones[i]["centroid_lon"],
                    zones[j]["centroid_lat"], zones[j]["centroid_lon"],
                )
                dist_km[i][j] = d
                dist_km[j][i] = d
        distance_source = "haversine"

    dist_matrix_m = [[int(dist_km[i][j] * 1000) for j in range(n)] for i in range(n)]

    # Naive distance: sum of sequential hops in input order
    naive_km = sum(dist_km[i][i + 1] for i in range(n - 1))

    # Try OR-Tools
    ordered = None
    route_optimized = False
    try:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2

        manager = pywrapcp.RoutingIndexManager(n, 1, 0)
        routing = pywrapcp.RoutingModel(manager)

        def distance_callback(from_idx, to_idx):
            from_node = manager.IndexToNode(from_idx)
            to_node = manager.IndexToNode(to_idx)
            return dist_matrix_m[from_node][to_node]

        transit_id = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_id)

        search_params = pywrapcp.DefaultRoutingSearchParameters()
        search_params.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )
        search_params.time_limit.seconds = 5

        solution = routing.SolveWithParameters(search_params)
        if solution:
            ordered = []
            idx = routing.Start(0)
            while not routing.IsEnd(idx):
                ordered.append(manager.IndexToNode(idx))
                idx = solution.Value(routing.NextVar(idx))
            route_optimized = True
    except Exception as e:
        logger.warning("OR-Tools TSP failed (%s), using nearest-neighbor fallback", e)

    if ordered is None:
        ordered = _nearest_neighbor_tsp(dist_matrix_m)

    total_km = sum(dist_km[ordered[i]][ordered[i + 1]] for i in range(len(ordered) - 1))
    saved_pct = ((naive_km - total_km) / naive_km * 100) if naive_km > 0 else 0.0

    return {
        "ordered_indices": ordered,
        "total_distance_km": round(total_km, 2),
        "naive_distance_km": round(naive_km, 2),
        "time_saved_pct": round(max(saved_pct, 0.0), 1),
        "route_optimized": route_optimized,
        "distance_source": distance_source,
    }


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

    # Naive route coords (CIS-ranked order, before VRP reorder) for before/after comparison
    naive_route_coords = [
        [item["centroid_lon"], item["centroid_lat"]]
        for item in items
        if item.get("centroid_lat") and item.get("centroid_lon")
    ]

    # VRP route optimization
    route_result = solve_patrol_route(items)
    reordered = [items[i] for i in route_result["ordered_indices"]]
    for new_rank, item in enumerate(reordered, 1):
        item["rank"] = new_rank
    items = reordered

    total_officers = sum(i["recommended_officers"] for i in items)
    plan_date = target_date or date.today().isoformat()

    return {
        "date": plan_date,
        "total_officers": total_officers,
        "zones_count": len(items),
        "items": items,
        "route_optimized": route_result["route_optimized"],
        "estimated_travel_km": route_result["total_distance_km"],
        "naive_travel_km": route_result["naive_distance_km"],
        "time_saved_pct": route_result["time_saved_pct"],
        "distance_source": route_result.get("distance_source", "haversine"),
        "naive_route_coords": naive_route_coords,
    }
