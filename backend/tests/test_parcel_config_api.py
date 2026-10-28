# backend/tests/test_parcel_config_api.py
import httpx
from fastapi.testclient import TestClient

from app.main import create_app


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

    async def get_entity(self, eid, options=None):
        return self.entity

    async def append_entity_attrs(self, eid, attrs):
        self.patched = (eid, attrs)

    async def delete_entity_attr(self, eid, attr):
        self.deleted = getattr(self, "deleted", []) + [(eid, attr)]

    async def close(self):
        pass


def test_get_parcel_config_returns_attrs(monkeypatch):
    fake = _FakeOrion()
    monkeypatch.setattr("app.api.parcel_config.OrionClient", lambda *a, **k: fake)
    client = TestClient(create_app())

    resp = client.get(
        "/api/routing/parcels/urn:ngsi-ld:AgriParcel:t1:p1/config"
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["accessPoint"] == {"type": "Point", "coordinates": [1.0, 2.0]}
    assert body["exclusionZones"] == {"type": "FeatureCollection", "features": []}


def test_put_parcel_config_appends_to_orion(monkeypatch):
    fake = _FakeOrion()
    monkeypatch.setattr("app.api.parcel_config.OrionClient", lambda *a, **k: fake)
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
    eid, attrs = fake.patched
    assert eid == "urn:ngsi-ld:AgriParcel:t1:p1"
    assert attrs["accessPoint"] == {
        "type": "GeoProperty",
        "value": {"type": "Point", "coordinates": [3.0, 4.0]},
    }
    assert attrs["exclusionZones"] == {
        "type": "Property",
        "value": {"type": "FeatureCollection", "features": []},
    }


def test_get_parcel_config_missing_entity(monkeypatch):

    class _FakeOrionNone(_FakeOrion):
        async def get_entity(self, eid, options=None):
            return None

    monkeypatch.setattr("app.api.parcel_config.OrionClient", lambda *a, **k: _FakeOrionNone())
    client = TestClient(create_app())

    resp = client.get("/api/routing/parcels/urn:ngsi-ld:AgriParcel:t1:missing/config")
    assert resp.status_code == 404


def test_put_parcel_config_invalid_access_point(monkeypatch):
    fake = _FakeOrion()
    monkeypatch.setattr("app.api.parcel_config.OrionClient", lambda *a, **k: fake)
    client = TestClient(create_app())

    resp = client.put(
        "/api/routing/parcels/urn:ngsi-ld:AgriParcel:t1:p1/config",
        json={"accessPoint": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}},
    )
    assert resp.status_code == 400


def test_put_parcel_config_invalid_exclusion_zones(monkeypatch):
    fake = _FakeOrion()
    monkeypatch.setattr("app.api.parcel_config.OrionClient", lambda *a, **k: fake)
    client = TestClient(create_app())

    resp = client.put(
        "/api/routing/parcels/urn:ngsi-ld:AgriParcel:t1:p1/config",
        json={"exclusionZones": {"type": "Point", "coordinates": [1.0, 2.0]}},
    )
    assert resp.status_code == 400


def test_get_parcel_config_orion_error_returns_502(monkeypatch):

    class _FakeOrionRaises(_FakeOrion):
        async def get_entity(self, eid, options=None):
            raise RuntimeError("Orion is down")

    monkeypatch.setattr("app.api.parcel_config.OrionClient", lambda *a, **k: _FakeOrionRaises())
    client = TestClient(create_app())

    resp = client.get("/api/routing/parcels/urn:ngsi-ld:AgriParcel:t1:p1/config")
    assert resp.status_code == 502
    assert resp.json()["detail"] == "Orion-LD error"


def test_put_parcel_config_orion_error_returns_502(monkeypatch):

    class _FakeOrionPatchRaises(_FakeOrion):
        async def append_entity_attrs(self, eid, attrs):
            raise RuntimeError("Orion patch failed")

    monkeypatch.setattr("app.api.parcel_config.OrionClient", lambda *a, **k: _FakeOrionPatchRaises())
    client = TestClient(create_app())

    resp = client.put(
        "/api/routing/parcels/urn:ngsi-ld:AgriParcel:t1:p1/config",
        json={"accessPoint": {"type": "Point", "coordinates": [1.0, 2.0]}},
    )
    assert resp.status_code == 502
    assert resp.json()["detail"] == "Orion-LD error"


def test_get_parcel_config_non_urn_returns_400(monkeypatch):
    fake = _FakeOrion()
    monkeypatch.setattr("app.api.parcel_config.OrionClient", lambda *a, **k: fake)
    client = TestClient(create_app())

    resp = client.get("/api/routing/parcels/not-a-urn/config")
    assert resp.status_code == 400
    assert "NGSI-LD URN" in resp.json()["detail"]


def test_put_parcel_config_non_urn_returns_400(monkeypatch):
    fake = _FakeOrion()
    monkeypatch.setattr("app.api.parcel_config.OrionClient", lambda *a, **k: fake)
    client = TestClient(create_app())

    resp = client.put(
        "/api/routing/parcels/not-a-urn/config",
        json={"accessPoint": {"type": "Point", "coordinates": [1.0, 2.0]}},
    )
    assert resp.status_code == 400
    assert "NGSI-LD URN" in resp.json()["detail"]


def test_put_parcel_config_access_point_missing_coordinates_returns_400(monkeypatch):
    fake = _FakeOrion()
    monkeypatch.setattr("app.api.parcel_config.OrionClient", lambda *a, **k: fake)
    client = TestClient(create_app())

    resp = client.put(
        "/api/routing/parcels/urn:ngsi-ld:AgriParcel:t1:p1/config",
        json={"accessPoint": {"type": "Point"}},
    )
    assert resp.status_code == 400
    assert "coordinates" in resp.json()["detail"]


def test_put_parcel_config_multi_status_returns_502(monkeypatch):

    class _FakeOrion207(_FakeOrion):
        async def append_entity_attrs(self, eid, attrs):
            req = httpx.Request("POST", "http://orion/ngsi-ld/v1/entities/x/attrs")
            raise httpx.HTTPStatusError(
                "207", request=req, response=httpx.Response(207, request=req)
            )

    monkeypatch.setattr("app.api.parcel_config.OrionClient", lambda *a, **k: _FakeOrion207())
    client = TestClient(create_app())

    resp = client.put(
        "/api/routing/parcels/urn:ngsi-ld:AgriParcel:t1:p1/config",
        json={"accessPoint": {"type": "Point", "coordinates": [1.0, 2.0]}},
    )
    assert resp.status_code == 502
    assert resp.json()["detail"] == "Orion-LD error"


_URL = "/api/routing/parcels/urn:ngsi-ld:AgriParcel:t1:p1/config"


def test_put_null_access_point_deletes_attribute(monkeypatch):
    fake = _FakeOrion()
    monkeypatch.setattr("app.api.parcel_config.OrionClient", lambda *a, **k: fake)
    client = TestClient(create_app())

    resp = client.put(_URL, json={
        "accessPoint": None,
        "exclusionZones": {"type": "FeatureCollection", "features": []},
    })

    assert resp.status_code == 200
    assert fake.deleted == [("urn:ngsi-ld:AgriParcel:t1:p1", "accessPoint")]
    assert "accessPoint" not in fake.patched[1]
    assert "exclusionZones" in fake.patched[1]
    assert resp.json()["removed"] == ["accessPoint"]


def test_put_null_access_point_alone_is_valid(monkeypatch):
    fake = _FakeOrion()
    monkeypatch.setattr("app.api.parcel_config.OrionClient", lambda *a, **k: fake)
    client = TestClient(create_app())

    resp = client.put(_URL, json={"accessPoint": None})

    assert resp.status_code == 200
    assert fake.patched is None
    assert len(fake.deleted) == 1


def test_put_absent_access_point_does_not_delete(monkeypatch):
    fake = _FakeOrion()
    monkeypatch.setattr("app.api.parcel_config.OrionClient", lambda *a, **k: fake)
    client = TestClient(create_app())

    resp = client.put(_URL, json={"exclusionZones": {"type": "FeatureCollection", "features": []}})

    assert resp.status_code == 200
    assert getattr(fake, "deleted", []) == []


def test_put_null_access_point_tolerates_404(monkeypatch):
    class _Fake404(_FakeOrion):
        async def delete_entity_attr(self, eid, attr):
            req = httpx.Request("DELETE", "http://orion/x")
            raise httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, request=req))

    monkeypatch.setattr("app.api.parcel_config.OrionClient", lambda *a, **k: _Fake404())
    client = TestClient(create_app())

    assert client.put(_URL, json={"accessPoint": None}).status_code == 200


def test_put_null_access_point_orion_error_returns_502(monkeypatch):
    class _Fake500(_FakeOrion):
        async def delete_entity_attr(self, eid, attr):
            req = httpx.Request("DELETE", "http://orion/x")
            raise httpx.HTTPStatusError("500", request=req, response=httpx.Response(500, request=req))

    monkeypatch.setattr("app.api.parcel_config.OrionClient", lambda *a, **k: _Fake500())
    client = TestClient(create_app())

    assert client.put(_URL, json={"accessPoint": None}).status_code == 502
