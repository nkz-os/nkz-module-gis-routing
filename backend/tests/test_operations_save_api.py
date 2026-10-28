import json

import pytest
from fastapi.testclient import TestClient

from app.api.pathfinding_router import JOBS
from app.main import create_app
from app.services.plan_store import PLAN_STORE

PARCEL = "urn:ngsi-ld:AgriParcel:p1"
_POLY = {
    "type": "Polygon",
    "coordinates": [[[-2.0, 43.0], [-1.99754, 43.0],
                     [-1.99754, 43.0009], [-2.0, 43.0009], [-2.0, 43.0]]],
}
URL = "/api/routing/operations"


class _Orion:
    created: list = []
    fail = False

    def __init__(self, *a, **k):
        pass

    async def create_entity(self, entity):
        if _Orion.fail:
            raise RuntimeError("down")
        _Orion.created.append(entity)

    async def get_entity(self, *a, **k):
        return _Orion.stored

    async def close(self):
        pass


@pytest.fixture
def client(monkeypatch):
    _Orion.created = []
    _Orion.fail = False
    monkeypatch.setattr("app.api.routing.OrionClient", _Orion)

    async def fake_fetch(parcel_id, tenant_id):
        return {"access_point": None, "zones": []}
    monkeypatch.setattr("app.api.routing._fetch_parcel_constraints", fake_fetch)
    return TestClient(create_app())


def _alt(aid, offset=0.0):
    coords = [[-2.0 + offset, 43.0, 100.0], [-1.999 + offset, 43.001, 105.0]]
    return {"id": aid, "label": aid, "distance_m": 150.0, "cumulative_climb_m": 5.0,
            "max_slope_deg_found": 3.2, "blocked_cells_hit": 0,
            "geometry": {"type": "LineString", "coordinates": [c[:2] for c in coords]},
            "elevation_profile": coords}


def _job(tenant="tenant-a", status="completed"):
    jid = JOBS.create(tenant)
    if status == "completed":
        JOBS.set(jid, {"status": "completed",
                       "alternatives": [_alt("least_slope"), _alt("fastest", 0.01)],
                       "report": {}})
    return jid


def _plan(client, parcel_id=PARCEL):
    r = client.post("/api/routing/generate", json={
        "parcel_geometry": _POLY, "parcel_id": parcel_id, "pattern": "boustrophedon",
        "pattern_config": {"width_m": 20, "headland_passes": 1, "turning_radius_m": 6.0},
        "persist": False})
    assert r.status_code == 200
    return r.json()["plan_id"]


def test_save_plan_persists_stored_plan(client):
    pid = _plan(client)
    r = client.post(URL, json={"kind": "plan", "plan_id": pid,
                               "planned_start_at": "2026-11-01T08:00:00Z"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["success"] is True and b["persisted"] is True and b["operation_id"]
    ent = _Orion.created[0]
    assert ent["id"] == b["operation_id"]
    assert ent["hasAgriParcel"]["object"] == PARCEL
    assert ent["plannedStartAt"]["value"]["@value"] == "2026-11-01T08:00:00Z"
    assert "swaths" in ent


def test_save_plan_unknown_or_other_tenant_410(client):
    pid = _plan(client)
    r = client.post(URL, json={"kind": "plan", "plan_id": "nope"})
    assert r.status_code == 410 and r.json()["code"] == "PLAN_EXPIRED"
    r = client.post(URL, json={"kind": "plan", "plan_id": pid},
                    headers={"X-Tenant-ID": "tenant-b"})
    assert r.status_code == 410 and r.json()["code"] == "PLAN_EXPIRED"
    assert _Orion.created == []


def test_save_plan_expired_410(client):
    pid = _plan(client)
    PLAN_STORE._clock = lambda: 10 ** 9
    try:
        r = client.post(URL, json={"kind": "plan", "plan_id": pid})
    finally:
        import time
        PLAN_STORE._clock = time.monotonic
    assert r.status_code == 410 and r.json()["code"] == "PLAN_EXPIRED"


def test_save_plan_without_parcel_422(client):
    pid = _plan(client, parcel_id=None)
    r = client.post(URL, json={"kind": "plan", "plan_id": pid})
    assert r.status_code == 422 and r.json()["code"] == "PARCEL_REQUIRED"


def test_save_plan_orion_failure_502(client):
    pid = _plan(client)
    _Orion.fail = True
    r = client.post(URL, json={"kind": "plan", "plan_id": pid})
    assert r.status_code == 502 and r.json()["code"] == "PERSIST_FAILED"


def test_save_plan_too_large(client, monkeypatch):
    pid = _plan(client)
    monkeypatch.setattr("app.services.operation_store.MAX_ENTITY_BYTES", 10)
    r = client.post(URL, json={"kind": "plan", "plan_id": pid})
    assert r.status_code == 422 and r.json()["code"] == "PLAN_TOO_LARGE"


def test_extra_fields_forbidden_and_kind_required(client):
    assert client.post(URL, json={"kind": "plan", "plan_id": "x", "zzz": 1}).status_code == 422
    assert client.post(URL, json={"plan_id": "x"}).status_code == 422


def test_save_transit(client):
    jid = _job()
    r = client.post(URL, json={"kind": "transit", "job_id": jid,
                               "alternative_id": "fastest", "parcel_id": PARCEL})
    assert r.status_code == 200, r.text
    ent = _Orion.created[0]
    assert ent["type"] == "AgriParcelOperation"
    assert ent["operationType"]["value"] == "transit"
    assert ent["hasAgriParcel"]["object"] == PARCEL
    assert ent["location"]["value"]["coordinates"][0][0] == pytest.approx(-1.99)
    assert ent["elevationProfile"]["value"][0] == [-1.99, 43.0, 100.0]
    assert ent["transitMetrics"]["value"] == {
        "distance_m": 150.0, "cumulative_climb_m": 5.0, "max_slope_deg_found": 3.2}
    assert ent["plannedStartAt"]["value"]["@value"].endswith("Z")
    assert ent["plannedEndAt"]["value"]["@value"] > ent["plannedStartAt"]["value"]["@value"]
    assert ent["isTemplate"]["value"] is False


def test_transit_requires_parcel(client):
    r = client.post(URL, json={"kind": "transit", "job_id": _job(), "alternative_id": "fastest"})
    assert r.status_code == 422 and r.json()["code"] == "PARCEL_REQUIRED"
    assert _Orion.created == []


def test_transit_job_errors(client):
    base = {"kind": "transit", "alternative_id": "fastest", "parcel_id": PARCEL}
    assert client.post(URL, json={**base, "job_id": "missing"}).status_code == 404
    other = _job(tenant="tenant-b")
    assert client.post(URL, json={**base, "job_id": other}).status_code == 404
    r = client.post(URL, json={**base, "job_id": _job(status="queued")})
    assert r.status_code == 409 and r.json()["code"] == "JOB_NOT_READY"
    r = client.post(URL, json={**base, "job_id": _job(), "alternative_id": "nope"})
    assert r.status_code == 422


def test_transit_orion_failure_502(client):
    _Orion.fail = True
    r = client.post(URL, json={"kind": "transit", "job_id": _job(),
                               "alternative_id": "fastest", "parcel_id": PARCEL})
    assert r.status_code == 502 and r.json()["code"] == "PERSIST_FAILED"


def _stored_transit():
    return {
        "id": "urn:ngsi-ld:AgriParcelOperation:t:tr1",
        "name": {"value": "transit"},
        "operationType": {"value": "transit"},
        "location": {"value": {"type": "LineString",
                               "coordinates": [[-2.0, 43.0], [-1.99, 43.001]]}},
    }


def test_export_transit_geojson_gpx_ok_isoxml_422(client):
    _Orion.stored = _stored_transit()
    r = client.get("/api/routing/export/tr1?format=gpx")
    assert r.status_code == 200 and "<trkpt" in r.text
    r = client.get("/api/routing/export/tr1?format=geojson")
    assert r.status_code == 200 and json.loads(r.text)["features"]
    r = client.get("/api/routing/export/tr1?format=isoxml")
    assert r.status_code == 422 and r.json()["code"] == "EXPORT_NOT_SUPPORTED"
