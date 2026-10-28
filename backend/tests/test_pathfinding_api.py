import asyncio
import time
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_tenant_zones(monkeypatch):
    """Fresh job store per test (tenant parcels are stubbed in conftest)."""
    from app.api import pathfinding_router as pr

    from app.services.pathfinding.job_store import JobStore
    monkeypatch.setattr(pr, "JOBS", JobStore())


def _grid():
    # Flat 11x11 grid -> both objectives reach B; routes well-defined.
    return {
        "elevations": [[0.0] * 11 for _ in range(11)],
        "origin_lon": -2.0,
        "origin_lat": 43.0,
        "pixel_size_deg": 0.001,
    }


def test_calculate_returns_two_objectives():
    resp = client.post("/api/routing/path/calculate", json={
        "point_a": [-2.0, 43.0],
        "point_b": [-1.99, 43.0],
        "elevation_grid": _grid(),
    })
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    for _ in range(50):
        r = client.get(f"/api/routing/path/{job_id}")
        body = r.json()
        if body["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)

    assert body["status"] == "completed", body
    ids = {a["id"] for a in body["alternatives"]}
    assert ids == {"least_slope", "fastest"}


def test_build_dem_registry_uses_settings_eu_url(monkeypatch):
    from app.api import pathfinding_router as pr

    class _S:
        eu_elevation_url = "http://eu-elev:8000"

    monkeypatch.setattr(pr, "get_settings", lambda: _S())
    reg = pr.build_dem_registry()
    assert asyncio.iscoroutinefunction(reg.fetch_best)
    assert any(p.name == "eu-elevation" and p.covers((-1.7, 42.7, -1.6, 42.9))
               for p in reg._providers)


def test_calculate_requires_auth():
    resp = client.post("/api/routing/path/calculate", json={"point_a": [-2.0, 43.0], "point_b": [-1.99, 43.0],
                                                           "elevation_grid": _grid()}, headers={"X-Tenant-ID": ""})
    assert resp.status_code == 401


def test_get_job_requires_auth_and_tenant():
    job_id = client.post("/api/routing/path/calculate", json={"point_a": [-2.0, 43.0], "point_b": [-1.99, 43.0],
                                                             "elevation_grid": _grid()}).json()["job_id"]
    assert client.get(f"/api/routing/path/{job_id}", headers={"X-Tenant-ID": ""}).status_code == 401
    assert client.get(f"/api/routing/path/{job_id}", headers={"X-Tenant-ID": "tenant-b"}).status_code == 404


def test_get_job_other_tenant_404(monkeypatch):
    from app.api import pathfinding_router as pr
    jid = pr.JOBS.create("tenant-z")
    pr.JOBS.set(jid, {"status": "completed", "alternatives": []})
    assert client.get(f"/api/routing/path/{jid}").status_code == 404   # client = tenant-a


def test_completed_job_has_report_and_slope_fields():
    resp = client.post("/api/routing/path/calculate", json={"point_a": [-2.0, 43.0], "point_b": [-1.99, 43.0],
                                                           "elevation_grid": _grid()})
    job_id = resp.json()["job_id"]
    for _ in range(50):
        body = client.get(f"/api/routing/path/{job_id}").json()
        if body["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert body["status"] == "completed"
    assert body["report"]["blocked_cells_hit"] == 0
    assert all("max_slope_deg_found" in a and a["blocked_cells_hit"] == 0 for a in body["alternatives"])


def test_min_turn_radius_is_deprecated(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="app.api.pathfinding_router"):
        resp = client.post("/api/routing/path/calculate", json={"point_a": [-2.0, 43.0], "point_b": [-1.99, 43.0],
                                                               "elevation_grid": _grid(), "min_turn_radius_m": 8.0})
    assert resp.status_code == 200 and "min_turn_radius_m" in caplog.text


def test_machine_id_sets_width(monkeypatch):
    seen = {}

    async def fake_machine(machine_id, tenant_id):
        return {"implementWidth": 5.5}

    async def fake_constraints(parcel_id, tenant_id, raster, cols, rows, machine_width_m, bbox):
        seen["w"] = machine_width_m
        return None, set(), {}

    from app.api import pathfinding_router as pr
    monkeypatch.setattr(pr, "fetch_machine_kinematics", fake_machine)
    monkeypatch.setattr(pr, "_resolve_path_constraints", fake_constraints)
    job_id = client.post("/api/routing/path/calculate", json={"point_a": [-2.0, 43.0], "point_b": [-1.99, 43.0],
                                                             "elevation_grid": _grid(), "machine_id": "urn:m1"}).json()["job_id"]
    for _ in range(50):
        if client.get(f"/api/routing/path/{job_id}").json()["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert seen["w"] == 5.5


@pytest.mark.asyncio
async def test_without_parcel_uses_tenant_zones_in_bbox(monkeypatch):
    from app.api import pathfinding_router as pr
    from shapely.geometry import Polygon
    called = {}

    async def fake_bbox(tenant_id, bbox):
        called["bbox"] = bbox
        return [_pz([Polygon([(0.001, 0.001), (0.003, 0.001), (0.003, 0.003), (0.001, 0.003)])])]

    monkeypatch.setattr(pr, "fetch_tenant_parcels_in_bbox", fake_bbox)
    raster = {"origin_lon": 0.0, "origin_lat": 0.0, "pixel_size_deg": 0.001}
    origin, blocked, fences = await pr._resolve_path_constraints(None, "tenant-a", raster, 10, 10, 2.0, (0, 0, 0.01, 0.01))
    assert origin is None and blocked and fences == {} and called["bbox"] == (0, 0, 0.01, 0.01)


def _pz(zones):
    return {"id": "urn:p", "name": "", "polygon": None, "geometry": None, "access_point": None, "zones": zones}


def _wait(job_id):
    for _ in range(50):
        body = client.get(f"/api/routing/path/{job_id}").json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.05)
    return body


def test_unknown_machine_fails_job(monkeypatch):
    from app.api import pathfinding_router as pr

    async def no_machine(machine_id, tenant_id):
        return {}

    monkeypatch.setattr(pr, "fetch_machine_kinematics", no_machine)
    job_id = client.post("/api/routing/path/calculate", json={
        "point_a": [-2.0, 43.0], "point_b": [-1.99, 43.0],
        "elevation_grid": _grid(), "machine_id": "urn:missing"}).json()["job_id"]
    body = _wait(job_id)
    assert body["status"] == "failed"
    assert body["error"] == "machine not found or has no implementWidth"
    assert body["error_code"] == "MACHINE_WIDTH_MISSING"
    assert body["error_params"] == {"machine_id": "urn:missing"}


def test_job_limit_returns_429():
    from app.api import pathfinding_router as pr
    for _ in range(pr.JOBS._max_per_tenant):
        pr.JOBS.create("tenant-a")
    resp = client.post("/api/routing/path/calculate", json={
        "point_a": [-2.0, 43.0], "point_b": [-1.99, 43.0], "elevation_grid": _grid()})
    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "JOB_LIMIT"


def _post(extra=None, grid=None):
    body = {"point_a": [-2.0, 43.0], "point_b": [-1.99, 43.0], "elevation_grid": grid or _grid()}
    body.update(extra or {})
    return _wait(client.post("/api/routing/path/calculate", json=body).json()["job_id"])


def _zone(lon0, lat0, lon1, lat1):
    from shapely.geometry import Polygon
    return Polygon([(lon0, lat0), (lon1, lat0), (lon1, lat1), (lon0, lat1)])


def test_dem_unavailable_code(monkeypatch):
    from app.api import pathfinding_router as pr

    class _Reg:
        async def fetch_best(self, bbox, resolution_m):
            return None

    monkeypatch.setattr(pr, "build_dem_registry", lambda: _Reg())
    body = _post({"elevation_grid": None})
    assert body["status"] == "failed"
    assert body["error_code"] == "DEM_UNAVAILABLE" and body["error"]


@pytest.mark.parametrize("which,pt", [("A", [-2.0, 43.0]), ("B", [-1.99, 43.0])])
def test_point_in_zone_code_names_the_point(monkeypatch, which, pt):
    from app.api import pathfinding_router as pr

    async def zones(tenant_id, bbox):
        return [_pz([_zone(pt[0] - 0.0004, pt[1] - 0.0004, pt[0] + 0.0004, pt[1] + 0.0004)])]

    monkeypatch.setattr(pr, "fetch_tenant_parcels_in_bbox", zones)
    body = _post()
    assert body["status"] == "failed" and body["error"]
    assert body["error_code"] == "POINT_IN_ZONE"
    assert body["error_params"] == {"point": which, "geometry": {"type": "Point", "coordinates": pt}}


def test_no_path_code(monkeypatch):
    from app.api import pathfinding_router as pr

    async def zones(tenant_id, bbox):
        return [_pz([_zone(-1.9955, 42.9, -1.9945, 43.2)])]  # wall between A and B

    monkeypatch.setattr(pr, "fetch_tenant_parcels_in_bbox", zones)
    body = _post()
    assert body["status"] == "failed" and body["error"]
    assert body["error_code"] == "NO_PATH" and body["error_params"] == {}


def test_engine_failure_code_hides_internals(monkeypatch):
    from app.api import pathfinding_router as pr

    def boom(*a, **k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(pr, "compute_ab_routes", boom)
    body = _post()
    assert body["status"] == "failed"
    assert body["error_code"] == "ENGINE_FAILURE"
    assert "secret internal detail" not in body["error"]


def test_report_has_max_slope_of_alternatives():
    body = _post()
    assert body["status"] == "completed"
    assert body["report"]["max_slope_deg_found"] == max(a["max_slope_deg_found"] for a in body["alternatives"])
