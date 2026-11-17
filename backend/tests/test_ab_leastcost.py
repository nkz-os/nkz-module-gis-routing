import math
import pytest
from app.services.pathfinding.least_cost_path import (
    compute_ab_routes, _cell_dist_m,
)


def test_metric_uses_cos_lat_for_longitude():
    # One pixel east at 60N spans cos(60)=0.5 of a pixel at the equator.
    pixel = 0.001
    d_eq = _cell_dist_m(1, 0, lat=0.0, pixel_size_deg=pixel)
    d_60 = _cell_dist_m(1, 0, lat=60.0, pixel_size_deg=pixel)
    assert d_60 == pytest.approx(d_eq * math.cos(math.radians(60.0)), rel=1e-6)
    # Latitude distance is independent of longitude scaling.
    d_lat = _cell_dist_m(0, 1, lat=60.0, pixel_size_deg=pixel)
    assert d_lat == pytest.approx(pixel * 111320.0, rel=1e-6)


def _ridge_grid(n=21):
    # A gaussian ridge centered on the middle column, tallest at the middle row
    # and tapering to flat at the top/bottom rows -> a low "pass" near the edges.
    grid = []
    for r in range(n):
        peak = 40.0 * max(0.0, 1.0 - abs(r - n // 2) / (n // 2))
        row = [peak * math.exp(-(((c - n // 2) / 3.0) ** 2)) for c in range(n)]
        grid.append(row)
    return grid


def test_two_objectives_diverge_on_a_ridge():
    n = 21
    grid = _ridge_grid(n)
    routes = compute_ab_routes(
        grid, origin_lon=-2.0, origin_lat=43.0, pixel_size_deg=0.001,
        start_col=0, start_row=n // 2, end_col=n - 1, end_row=n // 2,
        max_slope_deg=20.0,
    )
    by_id = {r["id"]: r for r in routes}
    assert set(by_id) == {"least_slope", "fastest"}

    least, fast = by_id["least_slope"], by_id["fastest"]
    # Metrics describe the served (smoothed) line; a least-slope shortcut may not
    # cost more than the path piece it replaces, so it keeps its detour.
    # Least-slope climbs less; fastest is shorter.
    assert least["cumulative_climb_m"] < fast["cumulative_climb_m"]
    assert fast["distance_m"] <= least["distance_m"] + 1e-6
    assert least["blocked_cells_hit"] == 0 and least["max_slope_deg_found"] >= 0
    # Both carry an elevation profile: one point per crossed cell, so at least one per vertex.
    assert len(least["elevation_profile"]) >= len(least["geometry"]["coordinates"])


def test_row_height_used_for_distance_and_coordinates():
    grid = [[0.0] * 5 for _ in range(5)]
    routes = compute_ab_routes(
        grid, origin_lon=-2.0, origin_lat=43.0, pixel_size_deg=0.001,
        start_col=0, start_row=0, end_col=0, end_row=4, pixel_height_deg=0.0005)
    fast = {r["id"]: r for r in routes}["fastest"]
    assert fast["distance_m"] == pytest.approx(4 * 0.0005 * 111320.0, abs=0.1)
    assert fast["geometry"]["coordinates"][-1][1] == pytest.approx(43.0 + 4 * 0.0005)


def test_cell_dist_uses_row_height():
    assert _cell_dist_m(0, 1, lat=43.0, pixel_size_deg=0.001, pixel_height_deg=0.0005) == \
        pytest.approx(0.0005 * 111320.0)


def test_none_cells_are_impassable():
    n = 7
    grid = [[0.0] * n for _ in range(n)]
    for r in range(n - 1):
        grid[r][3] = None  # wall of no-data, gap at the top row
    routes = compute_ab_routes(
        grid, origin_lon=-2.0, origin_lat=43.0, pixel_size_deg=0.001,
        start_col=0, start_row=0, end_col=6, end_row=0)
    assert routes, "a route exists through the gap"
    for r in routes:
        assert all(z is not None for _, _, z in r["elevation_profile"])


def test_all_none_wall_blocks_route():
    n = 5
    grid = [[0.0] * n for _ in range(n)]
    for r in range(n):
        grid[r][2] = None
    assert compute_ab_routes(
        grid, origin_lon=-2.0, origin_lat=43.0, pixel_size_deg=0.001,
        start_col=0, start_row=0, end_col=4, end_row=0) == []
