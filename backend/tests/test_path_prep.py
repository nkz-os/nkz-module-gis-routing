"""Attempt preparation (rasterization, fences) off the event loop; cell estimate; unreadable parcels."""
import asyncio
import math
import time

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon

from app.api import pathfinding_router as pr
from app.main import app
from app.services.exclusion import rasterize_blocked_cells

client = TestClient(app)
PIXEL = 0.001


def _parcel(zones=(), polygon=None, geometry=None, gate=None, pid="urn:p"):
    return {"id": pid, "name": "", "polygon": polygon, "geometry": geometry,
            "access_point": gate, "zones": list(zones)}


@pytest.mark.asyncio
async def test_event_loop_answers_while_a_large_prep_runs(monkeypatch):
    zone = Polygon([(0.001, 0.001), (0.003, 0.001), (0.003, 0.003), (0.001, 0.003)])

    async def fake_fetch(tenant_id, bbox):
        return [_parcel([zone])]

    def slow_raster(*a, **k):
        time.sleep(0.4)   # a large prep: blocking CPU
        return set()

    monkeypatch.setattr(pr, "fetch_tenant_parcels_in_bbox", fake_fetch)
    monkeypatch.setattr(pr, "rasterize_blocked_cells", slow_raster)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    t = asyncio.create_task(ticker())
    raster = {"origin_lon": 0.0, "origin_lat": 0.0, "pixel_size_deg": PIXEL}
    await pr._resolve_path_constraints(None, "t1", raster, 10, 10, 2.0, (0, 0, 0.01, 0.01))
    t.cancel()
    assert ticks >= 10, f"event loop was blocked: {ticks} ticks in 0.4 s"


def test_rasterize_two_distant_zones_on_a_big_grid_is_fast_and_exact():
    n = 1000
    z1 = Polygon([(5 * PIXEL, 5 * PIXEL), (7.5 * PIXEL, 5 * PIXEL), (7.5 * PIXEL, 7.5 * PIXEL), (5 * PIXEL, 7.5 * PIXEL)])
    z2 = Polygon([((n - 8) * PIXEL, (n - 8) * PIXEL), ((n - 5.5) * PIXEL, (n - 8) * PIXEL),
                  ((n - 5.5) * PIXEL, (n - 5.5) * PIXEL), ((n - 8) * PIXEL, (n - 5.5) * PIXEL)])
    from shapely.ops import unary_union
    t0 = time.perf_counter()
    cells = rasterize_blocked_cells(unary_union([z1, z2]), 0.0, 0.0, PIXEL, n, n)
    elapsed = time.perf_counter() - t0
    assert cells == {(c, r) for c in (6, 7) for r in (6, 7)} | {(c, r) for c in (n - 7, n - 6) for r in (n - 7, n - 6)}
    assert elapsed < 0.5, elapsed


def test_planned_cells_counts_square_degree_cells_at_any_latitude():
    px_deg = pr.DEM_RESOLUTION_M / pr._M_PER_DEG_LAT
    for lat in (0.0, 42.0, 60.0):
        bbox = (0.0, lat, 99.5 * px_deg, lat + 99.5 * px_deg)
        assert pr._planned_cells(bbox) == 100 * 100   # the DEM grid has square degrees
    # a 1 km x 1 km real-world box at 60 N has twice the columns of the equator figure
    w_deg = 1000 / (pr._M_PER_DEG_LAT * math.cos(math.radians(60)))
    assert pr._planned_cells((0, 60, w_deg, 60 + 1000 / pr._M_PER_DEG_LAT)) == pytest.approx(200 * 100, rel=0.02)


@pytest.mark.asyncio
async def test_unreadable_parcels_are_counted_in_report(monkeypatch):
    async def fake_fetch(tenant_id, bbox):
        return [_parcel(), _parcel(pid="urn:q"),
                _parcel(pid="urn:ok", polygon=Polygon([(0, 0), (1, 0), (1, 1)]), geometry={"type": "Polygon"})]

    monkeypatch.setattr(pr, "fetch_tenant_parcels_in_bbox", fake_fetch)
    rep: dict = {}
    raster = {"origin_lon": 0.0, "origin_lat": 0.0, "pixel_size_deg": PIXEL}
    await pr._resolve_path_constraints(None, "t1", raster, 10, 10, 2.0, (0, 0, 0.01, 0.01), report=rep)
    assert rep["unreadable_parcels"] == 2


def test_job_report_carries_unreadable_parcel_warning(monkeypatch):
    async def fake_fetch(tenant_id, bbox):
        return [_parcel()]

    monkeypatch.setattr(pr, "fetch_tenant_parcels_in_bbox", fake_fetch)
    grid = {"elevations": [[0.0] * 31 for _ in range(31)], "origin_lon": -2.0, "origin_lat": 43.0,
            "pixel_size_deg": PIXEL}
    jid = client.post("/api/routing/path/calculate", json={
        "point_a": [-1.995, 43.015], "point_b": [-1.975, 43.015], "elevation_grid": grid}).json()["job_id"]
    for _ in range(100):
        out = client.get(f"/api/routing/path/{jid}").json()
        if out["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert out["status"] == "completed", out
    assert out["report"]["warnings"] == [{"code": "PARCELS_UNREADABLE", "params": {"count": 1}}]


def test_job_report_records_constraints_used(monkeypatch):
    zone = Polygon([(-1.9945, 43.004), (-1.9935, 43.004), (-1.9935, 43.005), (-1.9945, 43.005)])

    async def fake_fetch(tenant_id, bbox):
        return [_parcel([zone], pid="urn:a"), _parcel(pid="urn:b")]

    monkeypatch.setattr(pr, "fetch_tenant_parcels_in_bbox", fake_fetch)
    grid = {"elevations": [[0.0] * 31 for _ in range(31)], "origin_lon": -2.0, "origin_lat": 43.0,
            "pixel_size_deg": PIXEL}
    jid = client.post("/api/routing/path/calculate", json={
        "point_a": [-1.995, 43.015], "point_b": [-1.975, 43.015], "elevation_grid": grid}).json()["job_id"]
    for _ in range(100):
        out = client.get(f"/api/routing/path/{jid}").json()
        if out["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert out["report"]["constraints_used"] == {"parcels": 2, "gated": 0, "zones": 1}
