# backend/tests/test_operations_listing_api.py
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.middleware import TenantStateMiddleware


def _tenant_dispatch(tid):
    async def dispatch(self, request, call_next):
        request.state.tenant_id = tid
        request.state.user_id = "test-user"
        return await call_next(request)
    return dispatch


def _entity(eid, parcel="urn:ngsi-ld:AgriParcel:p1", template=False):
    return {
        "id": eid, "type": "AgriParcelOperation",
        "operationType": {"type": "Property", "value": "spraying"},
        "status": {"type": "Property", "value": "planned"},
        "hasAgriParcel": {"type": "Relationship", "object": parcel},
        "location": {"type": "GeoProperty", "value": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}},
        "fieldEfficiency": {"type": "Property", "value": 0.9},
        "isTemplate": {"type": "Property", "value": template},
    }


class _FakeOrion:
    def __init__(self, entities=None, one=None):
        self._entities = entities or []
        self._one = one
    async def query_entities(self, *a, **k): return list(self._entities)
    async def get_entity(self, *a, **k): return self._one
    async def create_entity(self, *a, **k): return "x"
    async def delete_entity(self, *a, **k): return None
    async def close(self): pass


def test_list_operations_returns_lightweight_rows(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("tenant-a"))
    monkeypatch.setattr(
        "app.api.routing.OrionLDClient",
        lambda *a, **k: _FakeOrion(entities=[_entity("op-1"), _entity("tpl", template=True)]),
    )
    client = TestClient(create_app())
    resp = client.get("/api/routing/operations?parcel_id=urn:ngsi-ld:AgriParcel:p1")
    assert resp.status_code == 200
    data = resp.json()
    assert [r["id"] for r in data] == ["op-1"]      # template excluded
    assert "route" not in data[0]                    # lightweight
    assert data[0]["field_efficiency"] == 0.9


def test_get_operation_detail_includes_geometry(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("tenant-a"))
    monkeypatch.setattr(
        "app.api.routing.OrionLDClient",
        lambda *a, **k: _FakeOrion(one=_entity("op-1")),
    )
    client = TestClient(create_app())
    resp = client.get("/api/routing/operations/op-1")
    assert resp.status_code == 200
    assert resp.json()["route"]["type"] == "LineString"


def test_get_operation_404_when_missing(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("tenant-a"))
    monkeypatch.setattr("app.api.routing.OrionLDClient", lambda *a, **k: _FakeOrion(one=None))
    client = TestClient(create_app())
    resp = client.get("/api/routing/operations/missing")
    assert resp.status_code == 404


def test_list_operations_502_on_orion_error(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("tenant-a"))
    class _Boom(_FakeOrion):
        async def query_entities(self, *a, **k): raise RuntimeError("orion down")
    monkeypatch.setattr("app.api.routing.OrionLDClient", lambda *a, **k: _Boom())
    client = TestClient(create_app())
    resp = client.get("/api/routing/operations")
    assert resp.status_code == 502
