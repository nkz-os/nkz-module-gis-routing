# backend/tests/test_parcel_config_api.py
from fastapi.testclient import TestClient

from app.main import create_app
from app.middleware import TenantStateMiddleware


def _tenant_dispatch(tid):
    async def dispatch(self, request, call_next):
        request.state.tenant_id = tid
        request.state.user_id = "test-user"
        return await call_next(request)
    return dispatch


class _FakeOrion:
    def __init__(self):
        self.patched = None
        self.entity = {
            "id": "urn:ngsi-ld:AgriParcel:t1:p1",
            "type": "AgriParcel",
            "accessPoint": {
                "type": "GeoProperty",
                "value": {"type": "Point", "coordinates": [1.0, 2.0]},
            },
            "exclusionZones": {
                "type": "Property",
                "value": {"type": "FeatureCollection", "features": []},
            },
        }

    async def get_entity(self, eid, tenant):
        return self.entity

    async def patch_entity(self, eid, attrs, tenant):
        self.patched = (eid, attrs, tenant)

    async def close(self):
        pass


def test_get_parcel_config_returns_attrs(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("t1"))
    fake = _FakeOrion()
    monkeypatch.setattr("app.api.parcel_config.OrionLDClient", lambda *a, **k: fake)
    client = TestClient(create_app())

    resp = client.get(
        "/api/routing/parcels/urn:ngsi-ld:AgriParcel:t1:p1/config"
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["accessPoint"] == {"type": "Point", "coordinates": [1.0, 2.0]}
    assert body["exclusionZones"] == {"type": "FeatureCollection", "features": []}


def test_put_parcel_config_patches_orion(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("t1"))
    fake = _FakeOrion()
    monkeypatch.setattr("app.api.parcel_config.OrionLDClient", lambda *a, **k: fake)
    client = TestClient(create_app())

    payload = {
        "accessPoint": {"type": "Point", "coordinates": [3.0, 4.0]},
        "exclusionZones": {"type": "FeatureCollection", "features": []},
    }
    resp = client.put(
        "/api/routing/parcels/urn:ngsi-ld:AgriParcel:t1:p1/config",
        json=payload,
    )

    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Verify Orion was called with NGSI-LD-wrapped attrs
    assert fake.patched is not None
    eid, attrs, tenant = fake.patched
    assert eid == "urn:ngsi-ld:AgriParcel:t1:p1"
    assert tenant == "t1"
    assert attrs["accessPoint"] == {
        "type": "GeoProperty",
        "value": {"type": "Point", "coordinates": [3.0, 4.0]},
    }
    assert attrs["exclusionZones"] == {
        "type": "Property",
        "value": {"type": "FeatureCollection", "features": []},
    }


def test_get_parcel_config_missing_entity(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("t1"))

    class _FakeOrionNone(_FakeOrion):
        async def get_entity(self, eid, tenant):
            return None

    monkeypatch.setattr("app.api.parcel_config.OrionLDClient", lambda *a, **k: _FakeOrionNone())
    client = TestClient(create_app())

    resp = client.get("/api/routing/parcels/urn:ngsi-ld:AgriParcel:t1:missing/config")
    assert resp.status_code == 404


def test_put_parcel_config_invalid_access_point(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("t1"))
    fake = _FakeOrion()
    monkeypatch.setattr("app.api.parcel_config.OrionLDClient", lambda *a, **k: fake)
    client = TestClient(create_app())

    resp = client.put(
        "/api/routing/parcels/urn:ngsi-ld:AgriParcel:t1:p1/config",
        json={"accessPoint": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}},
    )
    assert resp.status_code == 400


def test_put_parcel_config_invalid_exclusion_zones(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("t1"))
    fake = _FakeOrion()
    monkeypatch.setattr("app.api.parcel_config.OrionLDClient", lambda *a, **k: fake)
    client = TestClient(create_app())

    resp = client.put(
        "/api/routing/parcels/urn:ngsi-ld:AgriParcel:t1:p1/config",
        json={"exclusionZones": {"type": "Point", "coordinates": [1.0, 2.0]}},
    )
    assert resp.status_code == 400
