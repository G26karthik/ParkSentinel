"""Smoke test: VRP solver produces a shorter route than naive input order."""
import sys
sys.path.insert(0, ".")

from enforcement import solve_patrol_route, _haversine_km

# 5 points roughly forming a star around central Bengaluru
ZONES = [
    {"centroid_lat": 12.9716, "centroid_lon": 77.5946},  # MG Road
    {"centroid_lat": 12.9352, "centroid_lon": 77.6245},  # Koramangala
    {"centroid_lat": 13.0070, "centroid_lon": 77.5670},  # Yeshwantpur
    {"centroid_lat": 12.9698, "centroid_lon": 77.7500},  # Whitefield
    {"centroid_lat": 12.9141, "centroid_lon": 77.6411},  # Jayanagar
]


def test_vrp_basic():
    result = solve_patrol_route(ZONES)
    assert "ordered_indices" in result
    assert "total_distance_km" in result
    assert "naive_distance_km" in result
    assert "time_saved_pct" in result
    assert "route_optimized" in result

    assert len(result["ordered_indices"]) == len(ZONES)
    assert set(result["ordered_indices"]) == set(range(len(ZONES)))
    assert result["total_distance_km"] <= result["naive_distance_km"]
    assert result["time_saved_pct"] >= 0.0
    print(f"  Naive:     {result['naive_distance_km']} km")
    print(f"  Optimized: {result['total_distance_km']} km")
    print(f"  Saved:     {result['time_saved_pct']}%")
    print(f"  OR-Tools:  {result['route_optimized']}")


def test_vrp_single_zone():
    result = solve_patrol_route([ZONES[0]])
    assert result["ordered_indices"] == [0]
    assert result["total_distance_km"] == 0.0


def test_vrp_empty():
    result = solve_patrol_route([])
    assert result["ordered_indices"] == []
    assert result["total_distance_km"] == 0.0


def test_haversine_sanity():
    # MG Road to Koramangala ~ 4-5 km
    d = _haversine_km(12.9716, 77.5946, 12.9352, 77.6245)
    assert 3.0 < d < 6.0, f"Expected 3-6 km, got {d}"


if __name__ == "__main__":
    print("test_haversine_sanity...")
    test_haversine_sanity()
    print("  PASS")

    print("test_vrp_empty...")
    test_vrp_empty()
    print("  PASS")

    print("test_vrp_single_zone...")
    test_vrp_single_zone()
    print("  PASS")

    print("test_vrp_basic (5 zones)...")
    test_vrp_basic()
    print("  PASS")

    print("\nAll VRP smoke tests passed.")
