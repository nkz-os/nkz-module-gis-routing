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
    return {"id": "urn:ngsi-ld:AgriParcel:p", "name": "", "geometry": None, "zones": [],
            "polygon": poly, "access_point": gate}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    from app.api import pathfinding_router as pr
    from app.services.pathfinding.job_store import JobStore

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
    assert (10, 10) in cells                                              # south edge away from gate


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
        assert all(Point(gate).distance(p) < 5 * PIXEL for p in pts), pts


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


def test_point_on_fence_ring_reports_barrier_with_parcel(monkeypatch):
    poly = _square(10, 10, 20, 20)
    _with_parcels(monkeypatch, [_parcel(poly, tuple(_pt(15, 10)))])
    out = _route((10, 15), (25, 15))   # A on the west edge, away from the gate
    assert out["status"] == "failed" and out["error"]
    assert out["error_code"] == "POINT_ON_BARRIER"
    assert out["error_params"] == {"point": "A", "parcel_id": "urn:ngsi-ld:AgriParcel:p",
                                   "geometry": {"type": "Point", "coordinates": _pt(10, 15)}}


def test_cap_stops_before_any_search(monkeypatch):
    from app.api import pathfinding_router as pr
    assert pr.MAX_SEARCH_CELLS == 1_000_000
    called = []
    monkeypatch.setattr(pr, "compute_ab_routes", lambda *a, **k: called.append(1))
    monkeypatch.setattr(pr, "MAX_SEARCH_CELLS", 100)
    out = _route((5, 15), (25, 15))
    assert out["error_code"] == "AREA_TOO_LARGE" and called == []


# ---- gate opening at production resolution (10 m cells) ---------------------

def _gate_case(width_m, rot_deg):
    """Return (routes_with_gate, routes_with_gate_disc_refenced) on a 10 m grid."""
    import math
    from shapely import affinity
    from app.services.pathfinding.least_cost_path import compute_ab_routes
    px = 10.0 / 111320.0
    n = 100
    raster = {"elevations": [[0.0] * n for _ in range(n)],
              "origin_lon": 0.0, "origin_lat": 0.0, "pixel_size_deg": px}
    sq = Polygon([(30 * px, 30 * px), (70 * px, 30 * px), (70 * px, 70 * px), (30 * px, 70 * px)])
    poly = affinity.rotate(sq, rot_deg, origin=(50 * px, 50 * px))
    c = list(poly.exterior.coords)
    gate = ((c[0][0] + c[1][0]) / 2, (c[0][1] + c[1][1]) / 2)
    fence = parcel_barrier_cells([_parcel(poly, gate)], raster, width_m)
    a, b = (3, 3), (50, 50)
    assert a not in fence and b not in fence
    open_routes = compute_ab_routes(raster["elevations"], 0.0, 0.0, px, *a, *b, blocked=fence)
    # Re-block every cell within the gate opening: nothing else may leak.
    cell_m = 10.0
    from app.services.pathfinding.barriers import band_thickness_m
    reach = band_thickness_m(width_m, cell_m) + max(width_m, 2 * cell_m) / 2 + cell_m
    gx, gy = gate[0] / px, gate[1] / px
    disc = {(cc, rr) for cc in range(n) for rr in range(n)
            if math.hypot(cc - gx, rr - gy) * cell_m <= reach}
    sealed = compute_ab_routes(raster["elevations"], 0.0, 0.0, px, *a, *b, blocked=fence | disc)
    return open_routes, sealed


@pytest.mark.parametrize("width_m", [20.0, 20.01, 12.0, 35.0])
@pytest.mark.parametrize("rot_deg", [0, 45, 20])
def test_gate_is_open_and_fence_elsewhere_is_sealed_at_10m_cells(width_m, rot_deg):
    open_routes, sealed = _gate_case(width_m, rot_deg)
    assert open_routes, "gate unreachable"
    assert sealed == [], "fence leaks away from the gate"


def test_multipolygon_only_the_part_nearest_the_gate_is_opened():
    from shapely.geometry import MultiPolygon
    near, far = _square(2, 2, 10, 10), _square(18, 2, 26, 10)
    gate = tuple(_pt(6, 2))
    cells = parcel_barrier_cells([_parcel(MultiPolygon([near, far]), gate)], _flat(), 3.0)
    assert (6, 2) not in cells                    # gate gap in the near part
    assert (22, 2) in cells and (18, 6) in cells  # far part fully fenced, incl. its closest edge


# ---- the fence never leaves the parcel (C1) ----------------------------------

PX10 = 10.0 / 111320.0


def _grid10(n=100):
    return {"elevations": [[0.0] * n for _ in range(n)],
            "origin_lon": 1.0, "origin_lat": 0.0, "pixel_size_deg": PX10}


def _cellpoly(c0, r0, c1, r1):
    return Polygon([(1.0 + c * PX10, r * PX10) for c, r in ((c0, r0), (c1, r0), (c1, r1), (c0, r1))])


def _cellpt(c, r):
    return (1.0 + c * PX10, r * PX10)


def _two_gated_parcels_with_track():
    # Track centre on column 50, 6 m wide: parcels end 3 m either side of it.
    west = _cellpoly(30, 30, 49.7, 70)
    east = _cellpoly(50.3, 30, 70, 70)
    return west, east, [_parcel(west, _cellpt(49.7, 60)) | {"id": "w"},
                        _parcel(east, _cellpt(50.3, 40)) | {"id": "e"}]


@pytest.mark.parametrize("width_m", [3.0, 6.0, 24.0])
def test_fence_cells_all_lie_inside_the_parcel(width_m):
    from shapely.geometry import Point as P
    west, east, parcels = _two_gated_parcels_with_track()
    raster = _grid10()
    for parcel in parcels:
        cells = parcel_barrier_cells([parcel], raster, width_m)
        assert cells
        assert all(parcel["polygon"].buffer(1e-6).covers(P(*_cellpt(c, r))) for c, r in cells)


def test_track_between_two_gated_parcels_is_not_blocked_and_passable():
    from app.services.pathfinding.least_cost_path import compute_ab_routes
    _w, _e, parcels = _two_gated_parcels_with_track()
    raster = _grid10()
    fence = parcel_barrier_cells(parcels, raster, 3.0)
    assert [(c, r) for c, r in fence if c == 50] == []   # the reviewer reproduction: 160 blocked
    routes = compute_ab_routes(raster["elevations"], 1.0, 0.0, PX10, 50, 5, 50, 95, blocked=fence)
    assert routes, "track closed"


@pytest.mark.parametrize("gate_name,target", [("e", (56, 40)), ("w", (44, 60))])
def test_each_gate_on_the_track_is_reachable_from_it(gate_name, target):
    from app.services.pathfinding.least_cost_path import compute_ab_routes
    _w, _e, parcels = _two_gated_parcels_with_track()
    raster = _grid10()
    fence = parcel_barrier_cells(parcels, raster, 3.0)
    assert target not in fence
    routes = compute_ab_routes(raster["elevations"], 1.0, 0.0, PX10, 50, 5, *target, blocked=fence)
    assert routes, f"gate {gate_name} unreachable from the track"


@pytest.mark.parametrize("rot_deg", [0, 45])
def test_fence_still_has_no_leaks_with_inside_band(rot_deg):
    open_routes, sealed = _gate_case(3.0, rot_deg)
    assert open_routes and sealed == []


# ---- serialization -------------------------------------------------------

@pytest.mark.asyncio
async def test_second_job_waits_for_the_first(monkeypatch):
    import asyncio
    from app.api import pathfinding_router as pr
    gate_open, entered = asyncio.Event(), asyncio.Event()

    class _Reg:
        async def fetch_best(self, bbox, resolution_m):
            entered.set()
            await gate_open.wait()
            return _flat()

    monkeypatch.setattr(pr, "build_dem_registry", lambda: _Reg())
    req = pr.PathRequest(point_a=_pt(5, 15), point_b=_pt(25, 15))
    j1, j2 = pr.JOBS.create("tenant-a"), pr.JOBS.create("tenant-a")
    t1 = asyncio.create_task(pr._run_pathfinding(j1, req, "tenant-a"))
    await entered.wait()
    t2 = asyncio.create_task(pr._run_pathfinding(j2, req, "tenant-a"))
    for _ in range(5):
        await asyncio.sleep(0)
    assert pr.JOBS.get(j1, "tenant-a")["status"] == "running"
    assert pr.JOBS.get(j2, "tenant-a")["status"] == "queued"
    gate_open.set()
    await asyncio.gather(t1, t2)
    assert pr.JOBS.get(j1, "tenant-a")["status"] == "completed"
    assert pr.JOBS.get(j2, "tenant-a")["status"] == "completed"


# ---- retry skipped by the cap ---------------------------------------------

def test_retry_skipped_by_cap_is_no_path_not_area_too_large(monkeypatch):
    from app.api import pathfinding_router as pr
    lat0 = 43.0

    class _Reg:
        async def fetch_best(self, bbox, resolution_m):
            n_lon = int((bbox[2] - bbox[0]) / PIXEL) + 1
            n_lat = int((bbox[3] - bbox[1]) / PIXEL) + 1
            return {"elevations": [[0.0] * n_lon for _ in range(n_lat)],
                    "origin_lon": bbox[0], "origin_lat": bbox[1], "pixel_size_deg": PIXEL}

    a, b = [-1.998, lat0], [-1.991, lat0]
    small = pr._planned_cells(pr._search_bbox(a, b, 500))
    big = pr._planned_cells(pr._search_bbox(a, b, 2000))
    assert small < big
    monkeypatch.setattr(pr, "MAX_SEARCH_CELLS", (small + big) // 2)
    poly = Polygon([(-1.9965, lat0 - 0.0105), (-1.9935, lat0 - 0.0105),
                    (-1.9935, lat0 + 0.0105), (-1.9965, lat0 + 0.0105)])
    _with_parcels(monkeypatch, [_parcel(poly, (-1.9950, lat0 + 0.0105))])
    monkeypatch.setattr(pr, "build_dem_registry", lambda: _Reg())
    jid = client.post("/api/routing/path/calculate", json={"point_a": a, "point_b": b}).json()["job_id"]
    for _ in range(400):
        out = client.get(f"/api/routing/path/{jid}").json()
        if out["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert out["error_code"] == "NO_PATH"
    assert out["error_params"] == {"search_margin_m": 500, "retry": "skipped_area_cap"}
