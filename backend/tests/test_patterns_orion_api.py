# backend/tests/test_patterns_orion_api.py
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


class _FakeOrion:
    def __init__(self, entities=None, one=None):
        self._entities = entities or []
        self._one = one
        self.created = []
        self.deleted = []
    async def query_entities(self, *a, **k): return list(self._entities)
    async def get_entity(self, *a, **k): return self._one
    async def create_entity(self, entity, tenant_id):
        self.created.append(entity); return entity["id"]
    async def delete_entity(self, entity_id, tenant_id):
        self.deleted.append(entity_id)
    async def close(self): pass


def _save_body():
    return {
        "parcel_id": "urn:ngsi-ld:AgriParcel:p1",
        "name": "Headland spray",
        "pattern_type": "boustrophedon",
        "pattern_config": {"width_m": 24, "heading_deg": 30},
        "route_geojson": '{"type":"LineString","coordinates":[[0,0],[1,1]]}',
        "vra_prescription_map": {"z1": 1.2},
        "equipment_tractor_id": None,
        "equipment_implement_id": None,
        "source_operation_id": None,
    }


def test_save_pattern_creates_template_entity(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("tenant-a"))
    fake = _FakeOrion()
    monkeypatch.setattr("app.api.patterns_router.OrionLDClient", lambda *a, **k: fake)
    client = TestClient(create_app())
    resp = client.post("/api/routing/patterns", json=_save_body())
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert len(fake.created) == 1
    assert fake.created[0]["isTemplate"]["value"] is True
    assert fake.created[0]["name"]["value"] == "Headland spray"


def test_list_patterns_returns_only_templates(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("tenant-a"))
    from app.services import operation_store
    tpl = operation_store.build_template_entity(
        op_id="tpl-1", parcel_id="urn:ngsi-ld:AgriParcel:p1", name="T",
        pattern_type="boustrophedon", pattern_config={"width_m": 24},
        route_geojson='{"type":"LineString","coordinates":[[0,0],[1,1]]}',
        vra_prescription_map=None, equipment_tractor_id=None,
        equipment_implement_id=None, source_operation_id=None,
    )
    op = {"id": "op-1", "type": "AgriParcelOperation",
          "refAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:p1"},
          "isTemplate": {"type": "Property", "value": False}}
    monkeypatch.setattr("app.api.patterns_router.OrionLDClient",
                        lambda *a, **k: _FakeOrion(entities=[tpl, op]))
    client = TestClient(create_app())
    resp = client.get("/api/routing/patterns?parcel_id=urn:ngsi-ld:AgriParcel:p1")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert [t["id"] for t in data] == ["tpl-1"]
    assert data[0]["name"] == "T"


def test_delete_pattern_calls_orion(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("tenant-a"))
    fake = _FakeOrion(one={"id": "tpl-1", "isTemplate": {"type": "Property", "value": True}})
    monkeypatch.setattr("app.api.patterns_router.OrionLDClient", lambda *a, **k: fake)
    client = TestClient(create_app())
    resp = client.delete("/api/routing/patterns/tpl-1")
    assert resp.status_code == 200
    assert fake.deleted == ["tpl-1"]
