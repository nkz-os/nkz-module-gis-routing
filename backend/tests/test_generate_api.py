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


def test_missing_turning_radius_returns_422():
    resp = client.post("/api/routing/generate", json={
        "parcel_geometry": _POLY,
        "pattern": "boustrophedon",
        "pattern_config": {"width_m": 20, "headland_passes": 1},
        "persist": False,
    })
    assert resp.status_code == 422
