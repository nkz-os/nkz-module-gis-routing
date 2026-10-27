import pytest
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


@pytest.mark.xfail(strict=True, reason="plan body lands in task 7")
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
