import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon

from app.main import app

client = TestClient(app)
SQ = {"type": "Polygon", "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]]}


def _stub(monkeypatch, parcels, seen=None):
    from app.api import routing

    async def fake(tenant_id, bbox):
        if seen is not None:
            seen.update(tenant=tenant_id, bbox=bbox)
        return parcels

    monkeypatch.setattr(routing, "fetch_tenant_parcels_in_bbox", fake)


def test_context_returns_light_parcels(monkeypatch):
    seen = {}
    zone = Polygon([(0.002, 0.002), (0.003, 0.002), (0.003, 0.003)])
    _stub(monkeypatch, [
        {"id": "urn:p1", "name": "North", "polygon": None, "geometry": SQ,
         "access_point": (0.005, 0.0), "zones": [zone]},
        {"id": "urn:p2", "name": "", "polygon": None, "geometry": SQ,
         "access_point": None, "zones": []},
    ], seen)
    r = client.get("/api/routing/parcels/context", params={"bbox": "-0.01,-0.01,0.02,0.02"})
    assert r.status_code == 200
    assert seen == {"tenant": "tenant-a", "bbox": (-0.01, -0.01, 0.02, 0.02)}
    p1, p2 = r.json()["parcels"]
    assert p1["id"] == "urn:p1" and p1["name"] == "North" and p1["geometry"] == SQ
    assert p1["access_point"] == {"type": "Point", "coordinates": [0.005, 0.0]}
    assert p1["zones"][0]["type"] == "Polygon"
    assert p2["access_point"] is None and p2["zones"] == []


def test_context_rejects_area_over_cap(monkeypatch):
    _stub(monkeypatch, [])
    r = client.get("/api/routing/parcels/context", params={"bbox": "0,0,0.21,0.1"})
    assert r.status_code == 422 and r.json()["code"] == "AREA_TOO_LARGE"
    r = client.get("/api/routing/parcels/context", params={"bbox": "0,0,0.1,0.21"})
    assert r.status_code == 422 and r.json()["code"] == "AREA_TOO_LARGE"
    assert client.get("/api/routing/parcels/context", params={"bbox": "0,0,0.2,0.2"}).status_code == 200


@pytest.mark.parametrize("bbox", ["a,b,c,d", "0,0,1", "1,1,0,0", "nan,0,1,1"])
def test_context_rejects_bad_bbox(monkeypatch, bbox):
    _stub(monkeypatch, [])
    r = client.get("/api/routing/parcels/context", params={"bbox": bbox})
    assert r.status_code == 422 and r.json()["code"] == "BBOX_INVALID"


def test_context_skips_parcels_without_readable_geometry(monkeypatch):
    _stub(monkeypatch, [{"id": "x", "name": "", "polygon": None, "geometry": None,
                         "access_point": None, "zones": []}])
    r = client.get("/api/routing/parcels/context", params={"bbox": "0,0,0.1,0.1"})
    assert r.json() == {"parcels": []}


def test_context_requires_auth():
    r = client.get("/api/routing/parcels/context", params={"bbox": "0,0,0.1,0.1"}, headers={"X-Tenant-ID": ""})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_fetch_tenant_parcels_in_bbox_reads_gate_and_skips_outside(monkeypatch):
    from app.services import parcel_constraints as pc
    far = {"type": "Polygon", "coordinates": [[[5, 5], [5.01, 5], [5.01, 5.01], [5, 5.01], [5, 5]]]}
    ents = [
        {"id": "in", "name": {"value": "A"}, "location": {"value": SQ},
         "accessPoint": {"value": {"type": "Point", "coordinates": [0.005, 0.0]}}},
        {"id": "out", "location": {"value": far}},
        {"id": "bad", "location": {"value": {"type": "Polygon", "coordinates": "x"}}},
    ]

    class FakeOrion:
        def __init__(self, *a, **k): ...
        async def query_entities(self, *a, **k): return ents
        async def close(self): ...

    monkeypatch.setattr(pc, "OrionClient", FakeOrion)
    got = await pc.fetch_tenant_parcels_in_bbox("tenant-a", (-0.01, -0.01, 0.02, 0.02))
    assert [p["id"] for p in got] == ["in", "bad"]
    assert got[1]["geometry"] is None and got[1]["polygon"] is None
    assert got[0]["access_point"] == (0.005, 0.0) and got[0]["name"] == "A" and got[0]["zones"] == []
