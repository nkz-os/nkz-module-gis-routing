"""Regression: list_parcels/list_equipment must resolve `auth`.

The SOTA refactor (cf5b228) switched both endpoints from `_get_tenant_id(request)`
to `auth.tenant_id` but forgot to add the `auth: AuthContext = require_auth()`
parameter. Both 500'd with NameError on the first request in production
(reported as 502 through the api-gateway). These tests hit both routes so a
missing dependency parameter can never ship silently again.
"""

from fastapi.testclient import TestClient

from app.main import create_app


class _FakeOrion:
    def __init__(self, entities=None):
        self._entities = entities or []

    async def query_entities(self, *a, **k):
        return list(self._entities)

    async def close(self):
        pass


def _parcel(eid="urn:ngsi-ld:AgriParcel:p1"):
    return {
        "id": eid,
        "name": {"type": "Property", "value": "Parcela 1"},
        "location": {"type": "GeoProperty", "value": {"type": "Point", "coordinates": [0, 0]}},
        "area": {"type": "Property", "value": 2.5},
    }


def _machine(eid="urn:ngsi-ld:ManufacturingMachine:m1"):
    return {
        "id": eid,
        "name": {"type": "Property", "value": "Tractor 1"},
        "category": {"type": "Property", "value": "tractor"},
    }


def test_list_parcels_resolves_auth(monkeypatch):
    monkeypatch.setattr(
        "app.api.routing.OrionClient",
        lambda *a, **k: _FakeOrion(entities=[_parcel()]),
    )
    client = TestClient(create_app())
    resp = client.get("/api/routing/parcels")

    assert resp.status_code == 200, (
        f"/parcels answered {resp.status_code}: {resp.text[:300]}. A NameError here "
        "means the endpoint uses `auth` without the require_auth() dependency "
        "(regression of cf5b228, live 502s in production on 2026-10-07)."
    )
    assert resp.json()[0]["name"] == "Parcela 1"


def test_list_equipment_resolves_auth(monkeypatch):
    monkeypatch.setattr(
        "app.api.routing.OrionClient",
        lambda *a, **k: _FakeOrion(entities=[_machine()]),
    )
    client = TestClient(create_app())
    resp = client.get("/api/routing/equipment")

    assert resp.status_code == 200, (
        f"/equipment answered {resp.status_code}: {resp.text[:300]}. A NameError here "
        "means the endpoint uses `auth` without the require_auth() dependency "
        "(regression of cf5b228, live 502s in production on 2026-10-07)."
    )
    assert resp.json()[0]["machine_role"] == "tractor"


def test_list_equipment_returns_the_pair_geometry(monkeypatch):
    seen = {}

    class Recording(_FakeOrion):
        async def query_entities(self, *a, **k):
            seen["attrs"] = k.get("attrs", "")
            return list(self._entities)

    mower = {**_machine("urn:m2"), "category": {"type": "Property", "value": "implement"},
             "implementOffsetY": {"type": "Property", "value": 1.6},
             "mountPosition": {"type": "Property", "value": "front"},
             "transportWidth": {"type": "Property", "value": 3.0}}
    monkeypatch.setattr("app.api.routing.OrionClient", lambda *a, **k: Recording(entities=[mower]))
    (m,) = TestClient(create_app()).get("/api/routing/equipment").json()
    for key in ("frontHitchOffsetX", "mountPosition", "implementOffsetY", "transportWidth",
                "guidanceDeviceOffsetX", "guidanceDeviceOffsetY"):
        assert key in seen["attrs"], key
        assert key in m, key
    assert (m["implementOffsetY"], m["mountPosition"], m["transportWidth"]) == (1.6, "front", 3.0)
