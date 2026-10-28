"""Gated parcels are barriers for A-B routes; ungated parcels are freely crossable."""
import time

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point, Polygon

from app.main import app
from app.services.pathfinding.barriers import parcel_barrier_cells

client = TestClient(app)
PIXEL = 0.001
ORIGIN = (-2.0, 43.0)
SIZE = 31


def _flat(size=SIZE):
    return {"elevations": [[0.0] * size for _ in range(size)],
            "origin_lon": ORIGIN[0], "origin_lat": ORIGIN[1], "pixel_size_deg": PIXEL}


def _square(c0, r0, c1, r1):
    x = lambda c: ORIGIN[0] + c * PIXEL
    y = lambda r: ORIGIN[1] + r * PIXEL
    return Polygon([(x(c0), y(r0)), (x(c1), y(r0)), (x(c1), y(r1)), (x(c0), y(r1))])


def _pt(c, r):
    return [round(ORIGIN[0] + c * PIXEL, 6), round(ORIGIN[1] + r * PIXEL, 6)]


def _parcel(poly, gate):
    return {"id": "urn:ngsi-ld:AgriParcel:p", "polygon": poly, "access_point": gate}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    from app.api import pathfinding_router as pr
    from app.services.pathfinding.job_store import JobStore

    async def no_zones(tenant_id, bbox):
        return []

    monkeypatch.setattr(pr, "fetch_tenant_zones_in_bbox", no_zones)
    monkeypatch.setattr(pr, "JOBS", JobStore())


def _with_parcels(monkeypatch, parcels):
    from app.api import pathfinding_router as pr

    async def fake(tenant_id, bbox):
        return parcels

    monkeypatch.setattr(pr, "fetch_tenant_parcels_in_bbox", fake)


def _route(a, b, extra=None, grid=None):
    body = {"point_a": _pt(*a), "point_b": _pt(*b), "elevation_grid": grid or _flat()}
    body.update(extra or {})
    jid = client.post("/api/routing/path/calculate", json=body).json()["job_id"]
    for _ in range(200):
        out = client.get(f"/api/routing/path/{jid}").json()
        if out["status"] in ("completed", "failed"):
            return out
        time.sleep(0.05)
    return out


def _line(alt):
    return LineString(alt["geometry"]["coordinates"])


# ---- unit: parcel_barrier_cells ------------------------------------------

def test_ungated_parcel_contributes_nothing():
    cells = parcel_barrier_cells([_parcel(_square(10, 10, 20, 20), None)], _flat(), 3.0)
    assert cells == set()


def test_gated_parcel_blocks_ring_but_not_interior_or_gate():
    gate = tuple(_pt(15, 10))  # middle of the south edge
    cells = parcel_barrier_cells([_parcel(_square(10, 10, 20, 20), gate)], _flat(), 3.0)
    assert (10, 15) in cells and (20, 15) in cells and (15, 20) in cells  # west/east/north edge
    assert (15, 15) not in cells                                          # interior
    assert (15, 10) not in cells and (14, 10) not in cells                # gate gap
    assert (12, 10) in cells                                              # south edge away from gate


# ---- end to end ----------------------------------------------------------

def test_b_inside_gated_parcel_enters_by_the_gate(monkeypatch):
    poly = _square(10, 10, 20, 20)
    gate = _pt(15, 10)
    _with_parcels(monkeypatch, [_parcel(poly, tuple(gate))])
    out = _route((5, 15), (15, 15))
    assert out["status"] == "completed", out
    for alt in out["alternatives"]:
        crossings = _line(alt).intersection(poly.exterior)
        pts = [crossings] if isinstance(crossings, Point) else list(crossings.geoms)
        assert pts, "route never crossed the boundary"
        assert all(Point(gate).distance(p) < 2 * PIXEL for p in pts), pts


def test_gated_parcel_between_a_and_b_is_avoided(monkeypatch):
    poly = _square(10, 10, 20, 20)
    _with_parcels(monkeypatch, [_parcel(poly, tuple(_pt(15, 10)))])
    out = _route((5, 15), (25, 15))
    assert out["status"] == "completed", out
    assert all(not _line(a).intersects(poly) for a in out["alternatives"])


def test_ungated_parcel_between_a_and_b_is_crossed(monkeypatch):
    poly = _square(10, 10, 20, 20)
    _with_parcels(monkeypatch, [_parcel(poly, None)])
    out = _route((5, 15), (25, 15))
    assert out["status"] == "completed", out
    assert all(_line(a).intersection(poly).length > 0.008 for a in out["alternatives"])


def test_a_and_b_inside_same_gated_parcel_never_leave(monkeypatch):
    poly = _square(8, 8, 22, 22)
    _with_parcels(monkeypatch, [_parcel(poly, tuple(_pt(15, 8)))])
    out = _route((12, 15), (18, 15))
    assert out["status"] == "completed", out
    assert all(poly.covers(_line(a)) for a in out["alternatives"])


def test_search_area_retries_wider_when_no_path_in_500m(monkeypatch):
    """A gated parcel wider than the +500 m search area walls A from B: the +2 km retry goes round it."""
    from app.api import pathfinding_router as pr
    lat0 = 43.0
    seen = []

    class _Reg:
        async def fetch_best(self, bbox, resolution_m):
            seen.append(bbox)
            n_lon = int((bbox[2] - bbox[0]) / PIXEL) + 1
            n_lat = int((bbox[3] - bbox[1]) / PIXEL) + 1
            return {"elevations": [[0.0] * n_lon for _ in range(n_lat)],
                    "origin_lon": bbox[0], "origin_lat": bbox[1], "pixel_size_deg": PIXEL}

    # long thin gated parcel, 0.02 deg tall (> 500 m margin), between A (west) and B (east)
    poly = Polygon([(-1.9965, lat0 - 0.0105), (-1.9935, lat0 - 0.0105),
                    (-1.9935, lat0 + 0.0105), (-1.9965, lat0 + 0.0105)])
    gate = (-1.9950, lat0 + 0.0105)
    _with_parcels(monkeypatch, [_parcel(poly, gate)])
    monkeypatch.setattr(pr, "build_dem_registry", lambda: _Reg())
    body = {"point_a": [-1.998, lat0], "point_b": [-1.991, lat0]}
    jid = client.post("/api/routing/path/calculate", json=body).json()["job_id"]
    for _ in range(400):
        out = client.get(f"/api/routing/path/{jid}").json()
        if out["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert out["status"] == "completed", out
    assert out["report"]["search_margin_m"] == 2000
    assert len(seen) == 2 and seen[1][1] < seen[0][1]


def test_search_margin_is_500_when_first_attempt_succeeds():
    out = _route((5, 15), (25, 15))
    assert out["status"] == "completed" and out["report"]["search_margin_m"] == 500


def test_area_too_large_when_cell_cap_exceeded(monkeypatch):
    from app.api import pathfinding_router as pr
    monkeypatch.setattr(pr, "MAX_SEARCH_CELLS", 100)
    out = _route((5, 15), (25, 15), grid=None)
    # explicit grid overrides the fetch, but the planned search area is still capped
    assert out["status"] == "failed" and out["error_code"] == "AREA_TOO_LARGE"
