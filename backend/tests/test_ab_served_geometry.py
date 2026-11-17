"""The served (smoothed) A-B line obeys the slope limit and is what gets measured."""
import math
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.pathfinding.least_cost_path import compute_ab_routes, _cell_dist_m

PX = 1e-4
LAT0 = 43.0
M_LAT = 111320.0


def _step_m(p, q):
    lat = math.radians((p[1] + q[1]) / 2.0)
    return math.hypot((q[0] - p[0]) * M_LAT * math.cos(lat), (q[1] - p[1]) * M_LAT)


def _profile_slopes(route):
    prof = route["elevation_profile"]
    return [math.degrees(math.atan2(abs(q[2] - p[2]), _step_m(p, q))) for p, q in zip(prof, prof[1:])]


def _assert_dense(route):
    """One profile point per crossed cell: no two consecutive points more than a cell diagonal apart."""
    diag = math.hypot(PX * M_LAT * math.cos(math.radians(LAT0)), PX * M_LAT)
    prof = route["elevation_profile"]
    assert all(_step_m(p, q) <= diag + 0.05 for p, q in zip(prof, prof[1:]))


def _routes(elev, start, end, max_slope=15.0, blocked=None):
    return {r["id"]: r for r in compute_ab_routes(
        elev, origin_lon=-2.0, origin_lat=LAT0, pixel_size_deg=PX,
        start_col=start[0], start_row=start[1], end_col=end[0], end_row=end[1],
        max_slope_deg=max_slope, blocked=blocked, pixel_height_deg=PX)}


def _tilted(rows, cols, deg):
    """Plane rising to the north at `deg` (row 0 = south)."""
    rise = PX * M_LAT * math.tan(math.radians(deg))
    return [[r * rise for _ in range(cols)] for r in range(rows)]


def test_shortcut_rejected_on_steep_ridge_without_blocks():
    elev = [[0.0] * 21 for _ in range(3)]
    elev[0][10] = elev[1][10] = 10.0  # a bump only row 2 can pass
    routes = _routes(elev, (0, 0), (20, 0))
    assert routes
    for r in routes.values():
        _assert_dense(r)
        assert max(_profile_slopes(r)) <= 15.0 + 0.05
        assert r["max_slope_deg_found"] <= 15.0
        assert all(z != 10.0 for _, _, z in r["elevation_profile"])


def test_served_steps_respect_max_slope():
    rng = np.random.default_rng(7)
    y, x = np.mgrid[0:40, 0:60]
    z = 14 * np.sin(x / 9.0) * np.cos(y / 7.0) + 6 * np.sin(x / 4.0 + y / 5.0) + 0.5 * rng.standard_normal((40, 60))
    routes = _routes(z.tolist(), (2, 20), (57, 37))
    assert set(routes) == {"least_slope", "fastest"}
    for r in routes.values():
        _assert_dense(r)
        assert max(_profile_slopes(r)) <= 15.0 + 0.05
        assert r["max_slope_deg_found"] <= 15.0


def test_distance_is_served_polyline_length():
    rng = np.random.default_rng(3)
    z = (5 * rng.standard_normal((30, 30))).tolist()
    for r in _routes(z, (1, 1), (28, 25), max_slope=30.0).values():
        coords = r["geometry"]["coordinates"]
        length = sum(_step_m(p, q) for p, q in zip(coords, coords[1:]))
        assert r["distance_m"] == pytest.approx(length, abs=0.2)
        prof = r["elevation_profile"]
        assert sum(_step_m(p, q) for p, q in zip(prof, prof[1:])) == pytest.approx(length, abs=0.2)


def test_profile_points_lie_on_segments():
    rng = np.random.default_rng(5)
    z = (5 * rng.standard_normal((30, 30))).tolist()
    for r in _routes(z, (1, 1), (28, 25), max_slope=30.0).values():
        coords, prof = r["geometry"]["coordinates"], r["elevation_profile"]
        assert prof[0][:2] == coords[0] and prof[-1][:2] == coords[-1]
        assert len(prof) >= len(coords)
        _assert_dense(r)
        seg = 0
        for p in prof:
            while seg < len(coords) - 2 and not _on_segment(p, coords[seg], coords[seg + 1]):
                seg += 1
            assert _on_segment(p, coords[seg], coords[seg + 1])


def _on_segment(p, a, b):
    cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    inside = min(a[0], b[0]) - 1e-7 <= p[0] <= max(a[0], b[0]) + 1e-7 and \
        min(a[1], b[1]) - 1e-7 <= p[1] <= max(a[1], b[1]) + 1e-7
    # coordinates are rounded to 1e-7 degrees: allow that much off the line
    return abs(cross) <= 2e-7 * math.hypot(b[0] - a[0], b[1] - a[1]) and inside


def test_cross_slope_traverse_vs_climb():
    elev = _tilted(7, 15, 20.0)
    traverse = _routes(elev, (0, 3), (14, 3))["fastest"]
    assert traverse["max_cross_slope_deg_found"] == pytest.approx(20.0, abs=0.5)
    assert traverse["max_slope_deg_found"] == pytest.approx(0.0, abs=0.1)
    climb = _routes(elev, (7, 0), (7, 6), max_slope=25.0)["fastest"]
    assert climb["max_cross_slope_deg_found"] == pytest.approx(0.0, abs=0.5)
    assert climb["max_slope_deg_found"] == pytest.approx(20.0, abs=0.5)


def test_cross_slope_no_nan_at_nodata_edge():
    elev = _tilted(5, 12, 20.0)
    elev[4] = [None] * 12  # no data just north of the route row
    r = _routes(elev, (0, 3), (11, 3))["fastest"]
    assert math.isfinite(r["max_cross_slope_deg_found"])
    assert r["max_cross_slope_deg_found"] == pytest.approx(20.0, abs=0.5)


def test_single_cell_route_metrics():
    r = _routes(_tilted(5, 5, 20.0), (2, 2), (2, 2))["fastest"]
    assert r["distance_m"] == 0.0
    assert len(r["elevation_profile"]) == 1
    assert r["max_cross_slope_deg_found"] == 0.0


# --- router report -------------------------------------------------------------

client = TestClient(app)


@pytest.fixture
def _fresh_jobs(monkeypatch):
    from app.api import pathfinding_router as pr
    from app.services.pathfinding.job_store import JobStore
    monkeypatch.setattr(pr, "JOBS", JobStore())


def _run(grid, a, b, max_slope):
    job = client.post("/api/routing/path/calculate", json={
        "point_a": a, "point_b": b, "max_slope_deg": max_slope, "elevation_grid": grid}).json()["job_id"]
    for _ in range(100):
        body = client.get(f"/api/routing/path/{job}").json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def _grid(elev):
    return {"elevations": elev, "origin_lon": -2.0, "origin_lat": LAT0, "pixel_size_deg": PX}


def test_report_warns_cross_slope_above_limit(_fresh_jobs):
    body = _run(_grid(_tilted(7, 15, 20.0)), [-2.0, LAT0 + 3.5 * PX], [-2.0 + 14.5 * PX, LAT0 + 3.5 * PX], 15.0)
    assert body["status"] == "completed", body
    rep = body["report"]
    assert rep["max_cross_slope_deg_found"] > 15.0
    warn = [w for w in rep["warnings"] if w["code"] == "CROSS_SLOPE_HIGH"]
    assert len(warn) == 1 and warn[0]["params"]["limit"] == 15.0
    assert warn[0]["params"]["deg"] == rep["max_cross_slope_deg_found"]


def test_report_no_cross_slope_warning_on_flat(_fresh_jobs):
    flat = [[0.0] * 15 for _ in range(7)]
    body = _run(_grid(flat), [-2.0, LAT0 + 3.5 * PX], [-2.0 + 14.5 * PX, LAT0 + 3.5 * PX], 15.0)
    assert body["status"] == "completed", body
    assert body["report"]["max_cross_slope_deg_found"] == 0.0
    assert not [w for w in body["report"]["warnings"] if w["code"] == "CROSS_SLOPE_HIGH"]
