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
    alerts: list = []   # Alerts are kept apart so operation counts stay exact
    fail = False

    def __init__(self, *a, **k):
        pass

    async def create_entity(self, entity):
        if _Orion.fail:
            raise RuntimeError("down")
        (_Orion.alerts if entity["type"] == "Alert" else _Orion.created).append(entity)

    async def get_entity(self, *a, **k):
        if _Orion.stored is None:
            # The real client raises on 404 (raise_for_status); it never returns None.
            import httpx
            req = httpx.Request("GET", "http://orion/ngsi-ld/v1/entities/x")
            raise httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, request=req))
        return _Orion.stored

    async def close(self):
        pass


@pytest.fixture
def client(monkeypatch):
    _Orion.created = []
    _Orion.alerts = []
    _Orion.fail = False
    _Orion.stored = {"id": PARCEL}
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
    for jid in ("missing", _job(tenant="tenant-b")):
        r = client.post(URL, json={**base, "job_id": jid})
        assert r.status_code == 404 and r.json()["code"] == "JOB_NOT_FOUND"
    r = client.post(URL, json={**base, "job_id": _job(status="queued")})
    assert r.status_code == 409 and r.json()["code"] == "JOB_NOT_READY"
    r = client.post(URL, json={**base, "job_id": _job(), "alternative_id": "nope"})
    assert r.status_code == 422 and r.json()["code"] == "ALTERNATIVE_NOT_FOUND"
    assert r.json()["params"] == {"alternative_id": "nope"}


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


def test_save_plan_is_idempotent_sequential(client):
    pid = _plan(client)
    a = client.post(URL, json={"kind": "plan", "plan_id": pid}).json()
    b = client.post(URL, json={"kind": "plan", "plan_id": pid})
    assert b.status_code == 200 and b.json() == a
    assert len(_Orion.created) == 1


def test_generate_persist_true_then_save_does_not_duplicate(client):
    r = client.post("/api/routing/generate", json={
        "parcel_geometry": _POLY, "parcel_id": PARCEL, "pattern": "boustrophedon",
        "pattern_config": {"width_m": 20, "headland_passes": 1, "turning_radius_m": 6.0}})
    b = r.json()
    s = client.post(URL, json={"kind": "plan", "plan_id": b["plan_id"]}).json()
    assert s["operation_id"] == b["operation_id"] and len(_Orion.created) == 1


def test_save_transit_is_idempotent(client):
    jid = _job()
    body = {"kind": "transit", "job_id": jid, "alternative_id": "fastest", "parcel_id": PARCEL}
    a = client.post(URL, json=body).json()
    b = client.post(URL, json=body).json()
    assert a == b and len(_Orion.created) == 1
    c = client.post(URL, json={**body, "alternative_id": "least_slope"}).json()
    assert c["operation_id"] != a["operation_id"] and len(_Orion.created) == 2


def test_concurrent_saves_create_one_entity(client, monkeypatch):
    import asyncio
    import httpx

    pid = _plan(client)
    jid = _job()
    orig = _Orion.create_entity

    async def slow(self, entity):
        await asyncio.sleep(0.05)
        await orig(self, entity)
    monkeypatch.setattr(_Orion, "create_entity", slow)

    async def go():
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                     headers={"X-Tenant-ID": "tenant-a", "X-User-ID": "u"}) as c:
            plan = {"kind": "plan", "plan_id": pid}
            tr = {"kind": "transit", "job_id": jid, "alternative_id": "fastest", "parcel_id": PARCEL}
            return await asyncio.gather(*(c.post(URL, json=j) for j in (plan, plan, tr, tr)))

    rs = asyncio.run(go())
    assert all(r.status_code == 200 for r in rs), [r.text for r in rs]
    assert rs[0].json() == rs[1].json() and rs[2].json() == rs[3].json()
    assert len(_Orion.created) == 2


def test_default_end_is_start_plus_one_day(client):
    pid = _plan(client)
    client.post(URL, json={"kind": "plan", "plan_id": pid,
                           "planned_start_at": "2026-11-01T08:00:00Z"})
    ent = _Orion.created[0]
    assert ent["plannedEndAt"]["value"]["@value"] == "2026-11-02T08:00:00Z"
    client.post(URL, json={"kind": "transit", "job_id": _job(), "alternative_id": "fastest",
                           "parcel_id": PARCEL, "planned_start_at": "2026-11-01T08:00:00Z"})
    assert _Orion.created[1]["plannedEndAt"]["value"]["@value"] == "2026-11-02T08:00:00Z"


def test_end_before_start_422(client):
    pid = _plan(client)
    r = client.post(URL, json={"kind": "plan", "plan_id": pid,
                               "planned_start_at": "2026-11-02T08:00:00Z",
                               "planned_end_at": "2026-11-01T08:00:00Z"})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_DATES"
    r = client.post(URL, json={"kind": "transit", "job_id": _job(), "alternative_id": "fastest",
                               "parcel_id": PARCEL, "planned_start_at": "2026-11-02T08:00:00Z",
                               "planned_end_at": "2026-11-01T08:00:00Z"})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_DATES"
    assert _Orion.created == []


def test_transit_unknown_parcel_404(client):
    _Orion.stored = None
    r = client.post(URL, json={"kind": "transit", "job_id": _job(), "alternative_id": "fastest",
                               "parcel_id": PARCEL})
    assert r.status_code == 404 and r.json()["code"] == "PARCEL_NOT_FOUND"
    assert _Orion.created == []


def test_stored_body_drops_external_features(client):
    from app.services.plan_store import PLAN_STORE
    r = client.post("/api/routing/generate", json={
        "parcel_geometry": _POLY, "pattern": "boustrophedon", "persist": False,
        "pattern_config": {"width_m": 20, "headland_passes": 1, "turning_radius_m": 6.0},
        "vra": {"enabled": False, "external_features": {"features": [{"x": 1}]}}})
    assert r.status_code == 200, r.text
    rec = PLAN_STORE.get("tenant-a", r.json()["plan_id"])
    assert "external_features" not in (rec["body"].get("vra") or {})


def test_generate_too_large_to_save_is_not_stored_and_warns(client, monkeypatch):
    from app.services.plan_store import PLAN_STORE
    monkeypatch.setattr("app.services.operation_store.MAX_ENTITY_BYTES", 10)
    before = len(PLAN_STORE._plans)
    r = client.post("/api/routing/generate", json={
        "parcel_geometry": _POLY, "parcel_id": PARCEL, "pattern": "boustrophedon", "persist": False,
        "pattern_config": {"width_m": 20, "headland_passes": 1, "turning_radius_m": 6.0}})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["plan_id"] is None
    codes = [w["code"] for w in b["plan"]["validation"]["warnings"]]
    assert "PLAN_TOO_LARGE_TO_SAVE" in codes
    assert len(PLAN_STORE._plans) == before


def test_generate_normal_plan_is_stored_without_that_warning(client):
    r = client.post("/api/routing/generate", json={
        "parcel_geometry": _POLY, "parcel_id": PARCEL, "pattern": "boustrophedon", "persist": False,
        "pattern_config": {"width_m": 20, "headland_passes": 1, "turning_radius_m": 6.0}})
    b = r.json()
    assert b["plan_id"]
    assert "PLAN_TOO_LARGE_TO_SAVE" not in [w["code"] for w in b["plan"]["validation"]["warnings"]]


def test_transit_save_for_another_parcel_is_a_new_operation(client):
    jid = _job()
    body = {"kind": "transit", "job_id": jid, "alternative_id": "fastest", "parcel_id": PARCEL}
    a = client.post(URL, json=body).json()
    other = client.post(URL, json={**body, "parcel_id": "urn:ngsi-ld:AgriParcel:p2"}).json()
    again = client.post(URL, json=body).json()
    assert other["operation_id"] != a["operation_id"] and again == a
    assert _Orion.created[1]["hasAgriParcel"]["object"] == "urn:ngsi-ld:AgriParcel:p2"
    assert len(_Orion.created) == 2


def test_transit_entity_records_constraints_used(client):
    from app.api.pathfinding_router import JOBS
    jid = _job()
    JOBS.set(jid, {"status": "completed", "alternatives": [_alt("fastest")],
                   "report": {"constraints_used": {"parcels": 4, "gated": 2, "zones": 3}}})
    client.post(URL, json={"kind": "transit", "job_id": jid, "alternative_id": "fastest", "parcel_id": PARCEL})
    assert _Orion.created[0]["constraintsUsed"]["value"] == {"parcels": 4, "gated": 2, "zones": 3}


@pytest.mark.asyncio
async def test_save_lock_entry_survives_release_while_a_waiter_is_pending():
    import asyncio
    from app.api import routing
    key = ("t", "lock-race")
    a = routing._save_lock(key)
    await a.__aenter__()
    entered = []

    async def waiter():
        async with routing._save_lock(key):
            entered.append(1)

    w = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    entry = routing._SAVE_LOCKS[key]
    await a.__aexit__(None, None, None)
    assert routing._SAVE_LOCKS.get(key) is entry     # a third request meets the same lock
    await w
    assert entered == [1] and key not in routing._SAVE_LOCKS
