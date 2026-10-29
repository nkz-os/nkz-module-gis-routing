import time
import pytest
from shapely.geometry import Point, mapping
from fastapi.testclient import TestClient
from app.main import app
from tests.fixtures_parcels import RECT, ZONE_CENTER, GATE, wgs84, wgs84_point

client = TestClient(app)
_RECT_WGS = mapping(wgs84(RECT))


@pytest.fixture(autouse=True)
def _fresh_store(monkeypatch):
    from app.api import routing
    from app.services.pathfinding.job_store import JobStore
    monkeypatch.setattr(routing, "GENERATE_JOBS", JobStore())


def _body(**extra):
    body = {"parcel_geometry": _RECT_WGS, "parcel_id": "urn:ngsi-ld:AgriParcel:p1",
            "pattern": "boustrophedon",
            "pattern_config": {"width_m": 4, "headland_passes": 1, "turning_radius_m": 6.0},
            "persist": False}
    body.update(extra)
    return body


def _constraints(monkeypatch, access=None, zones=()):
    async def fake(parcel_id, tenant_id):
        return {"access_point": access, "zones": list(zones)}
    monkeypatch.setattr("app.api.routing._fetch_parcel_constraints", fake)


def _start(body, tenant="tenant-a"):
    return client.post("/api/routing/generate/jobs", json=body, headers={"X-Tenant-ID": tenant})


def _wait(job_id, tenant="tenant-a", tries=400):
    for _ in range(tries):
        r = client.get(f"/api/routing/generate/jobs/{job_id}", headers={"X-Tenant-ID": tenant})
        assert r.status_code == 200, r.text
        body = r.json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_job_completes_with_same_result_as_generate(monkeypatch):
    _constraints(monkeypatch, access=wgs84_point(GATE))
    r = _start(_body())
    assert r.status_code == 202
    job = _wait(r.json()["job_id"])
    assert job["status"] == "completed", job
    direct = client.post("/api/routing/generate", json=_body()).json()
    assert set(job["result"]) == set(direct) == {"success", "operation_id", "persisted", "alert",
                                                  "plan", "plan_id"}
    assert job["result"]["plan"]["metrics"] == direct["plan"]["metrics"]


def test_coded_failure_carries_error_and_http_status(monkeypatch):
    _constraints(monkeypatch, access=wgs84_point(Point(-50, 50)))
    job = _wait(_start(_body()).json()["job_id"])
    assert job["status"] == "failed"
    assert job["error"]["code"] == "ACCESS_OUTSIDE_PARCEL" and job["http_status"] == 422
    assert "params" in job["error"] and "detail" in job["error"]


def test_unexpected_exception_is_engine_failure(monkeypatch):
    _constraints(monkeypatch)
    from app.api import routing

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(routing, "plan_with_fallbacks", boom)
    job = _wait(_start(_body()).json()["job_id"])
    assert job["status"] == "failed" and job["error"]["code"] == "ENGINE_FAILURE"
    assert job["http_status"] == 500


def test_invalid_body_is_rejected_synchronously():
    r = _start({"parcel_geometry": _RECT_WGS, "bogus": 1})
    assert r.status_code == 422


def test_job_is_tenant_bound(monkeypatch):
    _constraints(monkeypatch)
    job_id = _start(_body()).json()["job_id"]
    r = client.get(f"/api/routing/generate/jobs/{job_id}", headers={"X-Tenant-ID": "tenant-b"})
    assert r.status_code == 404
    assert client.get("/api/routing/generate/jobs/nope").status_code == 404
    _wait(job_id)


def test_per_tenant_cap_of_three_active_jobs(monkeypatch):
    import threading
    _constraints(monkeypatch)
    from app.api import routing
    gate = threading.Event()
    real = routing.plan_with_fallbacks

    def slow(*a, **k):
        gate.wait(10)
        return real(*a, **k)
    monkeypatch.setattr(routing, "plan_with_fallbacks", slow)
    ids = [_start(_body()).json()["job_id"] for _ in range(3)]
    r = _start(_body())
    assert r.status_code == 429 and r.json()["code"] == "JOBS_LIMIT"
    assert _start(_body(), tenant="tenant-b").status_code == 202
    gate.set()
    for i in ids:
        assert _wait(i)["status"] == "completed"


def test_at_most_two_run_at_once(monkeypatch):
    import threading
    _constraints(monkeypatch)
    from app.api import routing
    lock = threading.Lock()
    state = {"now": 0, "max": 0}
    real = routing.plan_with_fallbacks

    def tracked(*a, **k):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.3)
        try:
            return real(*a, **k)
        finally:
            with lock:
                state["now"] -= 1
    monkeypatch.setattr(routing, "plan_with_fallbacks", tracked)
    ids = [_start(_body()).json()["job_id"] for _ in range(3)]
    for i in ids:
        _wait(i)
    assert state["max"] == 2


def test_generate_post_unchanged(monkeypatch):
    _constraints(monkeypatch)
    r = client.post("/api/routing/generate", json=_body())
    assert r.status_code == 200 and r.json()["success"] is True
