import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box, mapping

from app.main import app
from tests.fixtures_parcels import RECT, wgs84

client = TestClient(app)
PARCEL = "urn:ngsi-ld:AgriParcel:p1"
RECT_GJ = mapping(wgs84(RECT))


def _zone(zid, x0, x1, mean=None, run=None, stamp=None, parcel=PARCEL):
    e = {"id": zid, "type": "AgriManagementZone",
         "hasAgriParcel": {"type": "Relationship", "object": parcel},
         "location": {"type": "GeoProperty", "value": mapping(wgs84(box(x0, 0, x1, 100)))},
         "areaHa": {"type": "Property", "value": (x1 - x0) * 100 / 10000.0}}
    if mean is not None:
        e["meanValue"] = {"type": "Property", "value": mean}
    if run:
        e["zoningRunId"] = {"type": "Property", "value": run}
    if stamp:
        e["observedAt"] = {"type": "Property", "value": stamp}
    return e


def zones3():
    return [_zone("z1", 0, 70, 0.2), _zone("z2", 70, 140, 0.5), _zone("z3", 140, 200, 0.8),
            _zone("z4", 0, 10)]


class FakeOrion:
    entities: list = []
    created: list = []
    calls: list = []
    parcel = {"id": PARCEL, "location": {"type": "GeoProperty", "value": RECT_GJ}}

    def __init__(self, *a, **k): ...

    async def query_entities(self, type=None, q=None, limit=100, offset=0, attrs=None, options=None):
        FakeOrion.calls.append({"type": type, "q": q, "limit": limit, "offset": offset})
        return FakeOrion.entities[offset:offset + limit]

    async def get_entity(self, entity_id):
        return FakeOrion.parcel if entity_id == PARCEL else None

    async def create_entity(self, entity):
        FakeOrion.created.append(entity)
        return {"id": entity["id"]}

    async def close(self): ...


@pytest.fixture(autouse=True)
def orion(monkeypatch):
    FakeOrion.entities, FakeOrion.created, FakeOrion.calls = zones3(), [], []
    monkeypatch.setattr("app.services.vra.zones.OrionClient", FakeOrion)
    monkeypatch.setattr("app.api.routing.OrionClient", FakeOrion)

    async def no_constraints(parcel_id, tenant_id):
        return {"access_point": None, "zones": []}
    monkeypatch.setattr("app.api.routing._fetch_parcel_constraints", no_constraints)


C3 = [{"min_pct": 0, "max_pct": 33, "rate": 100},
      {"min_pct": 33, "max_pct": 67, "rate": 200},
      {"min_pct": 67, "max_pct": 100, "rate": 300}]


def vra(**kw):
    d = {"enabled": True, "source": "orion", "classes": C3, "unit": "kg_ha", "product": "N"}
    d.update(kw)
    return d


def gen(**extra):
    body = {"parcel_geometry": RECT_GJ, "parcel_id": PARCEL, "pattern": "boustrophedon",
            "pattern_config": {"width_m": 4, "headland_passes": 1, "turning_radius_m": 6.0},
            "persist": False}
    body.update(extra)
    return client.post("/api/routing/generate", json=body)


def test_distribution_with_missing_mean():
    r = client.get(f"/api/routing/zones/{PARCEL}/distribution?source=orion")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["source"] == "orion" and b["variable"] == "NDVI"
    assert [z["id"] for z in b["zones"]] == ["z1", "z2", "z3"]
    assert b["missing"] == [{"id": "z4", "reason": "no_mean_value"}]
    assert len(b["percentiles"]) == 21
    assert b["percentiles"][0] == 0.2 and b["percentiles"][-1] == 0.8
    assert FakeOrion.calls[0]["q"] == f'hasAgriParcel=="{PARCEL}"'


def test_distribution_no_zones_is_empty_200():
    FakeOrion.entities = []
    r = client.get(f"/api/routing/zones/{PARCEL}/distribution")
    assert r.status_code == 200
    b = r.json()
    assert b["zones"] == [] and b["missing"] == [] and b["percentiles"] == []


def test_distribution_pages_through_all_zones():
    FakeOrion.entities = [_zone(f"z{i}", 0, 10, 0.5) for i in range(250)]
    r = client.get(f"/api/routing/zones/{PARCEL}/distribution")
    assert len(r.json()["zones"]) == 250
    assert [c["offset"] for c in FakeOrion.calls] == [0, 100, 200]


def test_distribution_keeps_only_latest_run():
    FakeOrion.entities = [
        _zone("old1", 0, 100, 0.1, run="r1", stamp="2026-01-01T00:00:00Z"),
        _zone("old2", 100, 200, 0.9, run="r1", stamp="2026-01-01T00:00:00Z"),
        _zone("new1", 0, 100, 0.3, run="r2", stamp="2026-02-01T00:00:00Z"),
        _zone("new2", 100, 200, 0.6, run="r2", stamp="2026-02-01T00:00:00Z"),
    ]
    b = client.get(f"/api/routing/zones/{PARCEL}/distribution").json()
    assert [z["id"] for z in b["zones"]] == ["new1", "new2"]


def test_get_zones_uses_paged_equality_query():
    FakeOrion.entities = [_zone(f"z{i}", 0, 10, 0.5) for i in range(130)]
    r = client.get(f"/api/routing/zones/{PARCEL}")
    assert r.status_code == 200 and r.json()["data"]["count"] == 130
    assert all(c["q"] == f'hasAgriParcel=="{PARCEL}"' for c in FakeOrion.calls)


def _swaths():
    plan = gen().json()["plan"]
    return plan["swaths"]


def test_prescription_ok():
    r = client.post("/api/routing/prescription",
                    json={"parcel_id": PARCEL, "swaths": _swaths(), "vra": vra()})
    assert r.status_code == 200, r.text
    p = r.json()["prescription"]
    assert [c["rate"] for c in p["classes"]] == [100, 200, 300]
    assert {f["properties"]["rate"] for f in p["swath_segments"]["features"]
            if f["properties"]["rate"] is not None} == {100, 200, 300}


def test_prescription_invalid_vra_is_422():
    r = client.post("/api/routing/prescription",
                    json={"parcel_id": PARCEL, "swaths": _swaths(),
                          "vra": vra(classes=[{"min_pct": 0, "max_pct": 100, "rate": 1}])})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_VRA"


def test_prescription_requires_auth():
    r = client.post("/api/routing/prescription", headers={"X-Tenant-ID": ""},
                    json={"parcel_id": PARCEL, "swaths": [], "vra": vra()})
    assert r.status_code == 401


def test_generate_with_vra_has_prescription_and_persists_it():
    r = gen(vra=vra(), persist=True)
    assert r.status_code == 200, r.text
    plan = r.json()["plan"]
    assert [c["rate"] for c in plan["prescription"]["classes"]] == [100, 200, 300]
    rates = {f["properties"]["rate"] for f in plan["prescription"]["swath_segments"]["features"]}
    assert {100, 200, 300} <= rates
    e = FakeOrion.created[0]
    assert e["prescription"]["value"]["unit"] == "kg_ha"
    assert e["vraConfig"]["value"]["classes"] == C3
    assert "prescriptionMap" not in e


def test_generate_vra_warnings_join_validation():
    FakeOrion.entities = [_zone("z1", 0, 70, 0.2), _zone("z2", 70, 140, 0.9)]
    plan = gen(vra=vra()).json()["plan"]
    codes = [w["code"] for w in plan["validation"]["warnings"]]
    assert "VRA_UNCOVERED" in codes
    w = next(w for w in plan["validation"]["warnings"] if w["code"] == "VRA_UNCOVERED")
    assert set(w) == {"code", "geometry", "params"} and w["params"]["length_m"] > 0


def test_generate_without_vra_has_null_prescription():
    r = gen(persist=True)
    assert r.json()["plan"]["prescription"] is None
    e = FakeOrion.created[0]
    assert "prescription" not in e and "vraConfig" not in e


def test_generate_vra_disabled_has_null_prescription():
    assert gen(vra=vra(enabled=False)).json()["plan"]["prescription"] is None


def test_generate_vra_invalid_is_422():
    r = gen(vra=vra(classes=[]))
    assert r.status_code == 422 and r.json()["code"] == "INVALID_VRA"


def test_generate_vra_external_source():
    feats = [{"type": "Feature", "geometry": mapping(wgs84(box(0, 0, 100, 100))),
              "properties": {"zone_id": "a", "value": 1.0}},
             {"type": "Feature", "geometry": mapping(wgs84(box(100, 0, 200, 100))),
              "properties": {"zone_id": "b", "value": 5.0}}]
    v = vra(source="external", external_features={"type": "FeatureCollection", "features": feats},
            classes=C3[:2][:0] + [{"min_pct": 0, "max_pct": 50, "rate": 10},
                                  {"min_pct": 50, "max_pct": 100, "rate": 20}])
    p = gen(vra=v).json()["plan"]["prescription"]
    assert [c["rate"] for c in p["classes"]] == [10, 20]


def test_legacy_vra_fields_rejected():
    r = gen(vra={"enabled": True, "base_rate": 100})
    assert r.status_code == 422


def test_zone_generation_n_zones(monkeypatch):
    sent = {}

    class Resp:
        def raise_for_status(self): ...
        def json(self): return {"ok": True}

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def post(self, url, json=None, headers=None):
            sent["json"] = json
            return Resp()

    monkeypatch.setattr("app.api.routing.httpx.AsyncClient", FakeClient)
    url = f"/api/routing/zones/{PARCEL}/generate"
    assert client.post(url, json={}).status_code == 200 and sent["json"] == {"n_zones": 8}
    assert client.post(url, json={"n_zones": 5}).status_code == 200 and sent["json"] == {"n_zones": 5}
    for bad in (1, 13, "x", True, 2.5):
        assert client.post(url, json={"n_zones": bad}).status_code == 422, bad


def test_external_ingest_returns_distribution():
    import json
    feats = [{"type": "Feature", "geometry": mapping(wgs84(box(0, 0, 100, 100))),
              "properties": {"zone_id": "a", "value": 1.0}},
             {"type": "Feature", "geometry": mapping(wgs84(box(100, 0, 200, 100))),
              "properties": {"zone_id": "b", "mean_value": 5.0}},
             {"type": "Feature", "geometry": mapping(wgs84(box(0, 100, 50, 150))),
              "properties": {"zone_id": "c", "prescription_rate": 2.0}}]
    r = client.post("/api/routing/zones/external/ingest", json={
        "format": "geojson", "content": json.dumps({"type": "FeatureCollection", "features": feats})})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["count"] == 3
    dist = d["distribution"]
    assert dist["source"] == "external" and len(dist["percentiles"]) == 21
    assert {z["id"]: z["mean"] for z in dist["zones"]} == {"a": 1.0, "b": 5.0, "c": 2.0}
