import pytest
from shapely.geometry import Point, mapping
from tests.fixtures_parcels import RECT, ZONE_CENTER, ZONE_SPLIT, GATE, wgs84, wgs84_point
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

_POLY = {
    "type": "Polygon",
    "coordinates": [[[-2.0, 43.0], [-1.99754, 43.0],
                     [-1.99754, 43.0009], [-2.0, 43.0009], [-2.0, 43.0]]],
}


def test_generate_boustrophedon_returns_ordered_route():
    resp = client.post("/api/routing/generate", json={
        "parcel_geometry": _POLY,
        "pattern": "boustrophedon",
        "pattern_config": {"width_m": 20, "headland_passes": 1,
                           "turning_radius_m": 6.0},
        "persist": False,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    chosen = body["selected"]
    assert chosen["metrics"]["field_efficiency"] > 0
    assert chosen["route"]["type"] in ("MultiLineString", "LineString")


def test_legacy_alias_ab_line_maps_to_boustrophedon():
    resp = client.post("/api/routing/generate", json={
        "parcel_geometry": _POLY,
        "pattern": "ab-line",
        "pattern_config": {"width_m": 20, "headland_passes": 1,
                           "turning_radius_m": 6.0},
        "persist": False,
    })
    assert resp.status_code == 200
    assert resp.json()["selected"]["pattern"] == "boustrophedon"


def test_headland_compose_does_not_crash():
    resp = client.post("/api/routing/generate", json={
        "parcel_geometry": _POLY,
        "pattern": "boustrophedon",
        "pattern_config": {"width_m": 20, "headland_passes": 2,
                           "turning_radius_m": 6.0},
        "persist": False,
    })
    assert resp.status_code == 200


def test_non_polygon_geometry_returns_invalid_geometry_code():
    resp = client.post("/api/routing/generate", json={
        "parcel_geometry": {"type": "Point", "coordinates": [0, 0]},
        "pattern": "boustrophedon", "persist": False})
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_GEOMETRY"


def test_degenerate_polygon_returns_invalid_geometry_code():
    resp = client.post("/api/routing/generate", json={
        "parcel_geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 0], [0, 0], [0, 0]]]},
        "pattern": "boustrophedon",
        "pattern_config": {"width_m": 20, "turning_radius_m": 6.0}, "persist": False})
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_GEOMETRY"


def test_missing_turning_radius_returns_coded_422():
    resp = client.post("/api/routing/generate", json={
        "parcel_geometry": _POLY, "pattern": "boustrophedon",
        "pattern_config": {"width_m": 20, "headland_passes": 1}, "persist": False})
    assert resp.status_code == 422
    assert resp.json()["code"] == "TURNING_RADIUS_MISSING"


def test_deprecated_fields_are_accepted_and_logged(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="app.api.routing"):
        resp = client.post("/api/routing/generate", json={
            "parcel_geometry": _POLY, "pattern": "boustrophedon",
            "pattern_config": {"width_m": 20, "headland_passes": 1, "turning_radius_m": 6.0,
                               "direction": "outside-in"},
            "coupling_model": "rigid", "selected_alternative_id": "x", "persist": False})
    assert resp.status_code == 200
    assert "deprecated fields ignored" in caplog.text
    for name in ("direction", "coupling_model", "selected_alternative_id"):
        assert name in caplog.text


def test_headland_passes_zero_is_coerced_to_one():
    resp = client.post("/api/routing/generate", json={
        "parcel_geometry": _POLY, "pattern": "boustrophedon",
        "pattern_config": {"width_m": 20, "headland_passes": 0, "turning_radius_m": 6.0}, "persist": False})
    assert resp.status_code == 200
    assert resp.json()["plan"]["headland_passes"] >= 1


def test_external_ingest_requires_auth():
    resp = client.post("/api/routing/zones/external/ingest",
                       json={"format": "geojson", "content": "{}"},
                       headers={"X-Tenant-ID": ""})
    assert resp.status_code == 401


def test_generate_with_parcel_id_passes_tenant_to_constraints(monkeypatch):
    seen = {}

    async def fake_fetch(parcel_id, tenant_id):
        seen["parcel_id"] = parcel_id
        seen["tenant_id"] = tenant_id
        return {"access_point": None, "zones": []}

    monkeypatch.setattr("app.api.routing._fetch_parcel_constraints", fake_fetch)
    resp = client.post("/api/routing/generate", json={
        "parcel_geometry": _POLY,
        "parcel_id": "urn:ngsi-ld:AgriParcel:p1",
        "pattern": "boustrophedon",
        "pattern_config": {"width_m": 20, "headland_passes": 1,
                           "turning_radius_m": 6.0},
        "persist": False,
    })
    assert resp.status_code == 200
    assert seen["parcel_id"] == "urn:ngsi-ld:AgriParcel:p1"
    assert seen["tenant_id"] == "tenant-a"


_RECT_WGS = mapping(wgs84(RECT))


def _fake_constraints(access=None, zones=()):
    async def fake(parcel_id, tenant_id):
        return {"access_point": access, "zones": list(zones)}
    return fake


def _gen(monkeypatch, **extra):
    monkeypatch.setattr("app.api.routing._fetch_parcel_constraints",
                        _fake_constraints(extra.pop("access", None), extra.pop("zones", ())))
    body = {"parcel_geometry": _RECT_WGS, "parcel_id": "urn:ngsi-ld:AgriParcel:p1", "pattern": "boustrophedon",
            "pattern_config": {"width_m": 4, "headland_passes": 1, "turning_radius_m": 6.0}, "persist": False}
    body.update(extra)
    return client.post("/api/routing/generate", json=body)


def test_plan_body_shape(monkeypatch):
    resp = _gen(monkeypatch, access=wgs84_point(GATE))
    assert resp.status_code == 200, resp.text
    plan = resp.json()["plan"]
    for key in ("pattern", "curve_type", "swath_count", "headland_passes", "route", "swaths", "access_path",
                "access_point", "exit_point", "working_area", "unreached_parts", "metrics", "validation",
                "exclusion_zones", "prescription"):
        assert key in plan, key
    assert plan["swath_count"] == len(plan["swaths"]) and plan["swaths"][0]["kind"] in ("work", "headland")
    assert plan["validation"]["ok"] is True and plan["prescription"] is None
    assert {"worked_distance_m", "non_working_distance_m", "access_distance_m", "field_efficiency",
            "covered_area_ha", "parcel_area_ha", "working_area_ha"} <= set(plan["metrics"])
    assert resp.json()["selected"]["route"]["type"] in ("MultiLineString", "LineString")   # legado conservado


def test_gate_in_zone_returns_access_in_zone(monkeypatch):
    resp = _gen(monkeypatch, access=wgs84_point(Point(100, 50)), zones=[wgs84(ZONE_CENTER)])
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "ACCESS_IN_ZONE" and body["params"]["point"]["type"] == "Point"


def test_gate_outside_parcel(monkeypatch):
    resp = _gen(monkeypatch, access=wgs84_point(Point(-50, 50)))
    assert resp.status_code == 422 and resp.json()["code"] == "ACCESS_OUTSIDE_PARCEL"


def test_split_zone_reports_unreached(monkeypatch):
    resp = _gen(monkeypatch, access=wgs84_point(GATE), zones=[wgs84(ZONE_SPLIT)])
    assert resp.status_code == 200, resp.text
    plan = resp.json()["plan"]
    assert len(plan["unreached_parts"]) == 1 and plan["unreached_parts"][0]["area_ha"] > 0.5
    assert any(w["code"] == "UNREACHED_AREA" for w in plan["validation"]["warnings"])


def test_auto_pattern_default(monkeypatch):
    monkeypatch.setattr("app.api.routing._fetch_parcel_constraints", _fake_constraints())
    resp = client.post("/api/routing/generate", json={
        "parcel_geometry": _RECT_WGS, "pattern_config": {"width_m": 4, "turning_radius_m": 6.0}, "persist": False})
    assert resp.status_code == 200
    assert resp.json()["plan"]["pattern"] in ("boustrophedon", "snake", "spiral")


def test_engine_failure_is_500_with_code(monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("f2c exploded")
    monkeypatch.setattr("app.api.routing.plan_with_fallbacks", boom)
    resp = _gen(monkeypatch)
    assert resp.status_code == 500 and resp.json()["code"] == "ENGINE_FAILURE"
    assert resp.json()["params"] == {}
    recs = [r for r in caplog.records if r.name == "app.api.routing" and r.exc_info]
    assert recs, "expected a logged traceback"


def test_plan_error_passes_through_unchanged(monkeypatch):
    from app.services.exclusion import ExclusionError

    def boom(*a, **k):
        raise ExclusionError("no area", code="NO_DRIVABLE_AREA",
                             params={"point": {"type": "Point", "coordinates": [0, 0]}})
    monkeypatch.setattr("app.api.routing.plan_with_fallbacks", boom)
    resp = _gen(monkeypatch)
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "NO_DRIVABLE_AREA"
    assert body["params"]["point"] == {"type": "Point", "coordinates": [0, 0]}


def test_persist_writes_plan_attributes(monkeypatch):
    captured = {}

    class FakeOrion:
        def __init__(self, *a, **k): ...
        async def create_entity(self, entity):
            captured["entity"] = entity
            return {"id": entity["id"]}
        async def close(self): ...

    monkeypatch.setattr("app.api.routing.OrionClient", FakeOrion)
    resp = _gen(monkeypatch, access=wgs84_point(GATE), persist=True,
                planned_start_at="2026-11-02T08:00:00Z", planned_end_at="2026-11-02T18:00:00Z")
    assert resp.status_code == 200 and resp.json()["operation_id"]
    e = captured["entity"]
    assert e["swaths"]["value"]["type"] == "FeatureCollection"
    assert e["accessPoint"]["type"] == "GeoProperty" and e["workingArea"]["type"] == "GeoProperty"
    assert e["planVersion"]["value"] == 1 and e["validation"]["value"]["ok"] is True
    assert e["plannedStartAt"]["value"] == {"@type": "DateTime", "@value": "2026-11-02T08:00:00Z"}
    assert e["plannedEndAt"]["value"]["@value"] == "2026-11-02T18:00:00Z"
    assert "couplingModel" not in e
    assert e["headlandPasses"]["value"] >= 1
    assert e["exclusionZones"]["value"]["type"] == "FeatureCollection"
    assert e["location"]["value"]["type"] in ("LineString", "MultiLineString")


def test_headland_only_returns_minimal_plan(monkeypatch):
    resp = _gen(monkeypatch, access=wgs84_point(GATE), pattern="headland-only")
    assert resp.status_code == 200, resp.text
    plan = resp.json()["plan"]
    assert plan["pattern"] == "headland-only" and plan["validation"]["ok"] is True
    assert plan["swaths"] and all(s["kind"] == "headland" for s in plan["swaths"])
    assert plan["access_point"]["type"] == "Point" and plan["exit_point"]["type"] == "Point"
    assert plan["swath_count"] == len(plan["swaths"])
    assert {"worked_distance_m", "non_working_distance_m", "access_distance_m", "field_efficiency",
            "covered_area_ha", "parcel_area_ha", "working_area_ha"} <= set(plan["metrics"])


def test_headland_only_persist_has_no_null_properties(monkeypatch):
    captured = {}

    class FakeOrion:
        def __init__(self, *a, **k): ...
        async def create_entity(self, entity):
            captured["entity"] = entity
            return {"id": entity["id"]}
        async def close(self): ...

    monkeypatch.setattr("app.api.routing.OrionClient", FakeOrion)
    resp = _gen(monkeypatch, access=wgs84_point(GATE), pattern="headland-only", persist=True)
    assert resp.status_code == 200 and resp.json()["operation_id"]
    nulls = [k for k, v in captured["entity"].items()
             if isinstance(v, dict) and "value" in v and v["value"] is None]
    assert nulls == []
