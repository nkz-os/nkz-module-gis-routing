"""Several zonings per parcel: the VRA default, explicit choice and per-zone rates."""
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box, mapping

from app.main import app
from tests.fixtures_parcels import RECT, wgs84
from tests.test_vra_api import C3, FakeOrion, PARCEL, gen

client = TestClient(app)


def _zone(zid, x0, x1, *, mean=None, run=None, method=None, date=None, rank=None, label=None):
    e = {"id": zid, "type": "AgriManagementZone",
         "hasAgriParcel": {"type": "Relationship", "object": PARCEL},
         "location": {"type": "GeoProperty", "value": mapping(wgs84(box(x0, 0, x1, 100)))}}
    if mean is not None:
        e["meanValue"] = {"type": "Property", "value": mean}
    if run:
        e["zoningRunId"] = {"type": "Property", "value": run}
    if method:
        e["zoningMethod"] = {"type": "Property", "value": method}
    if date:
        e["dateZoned"] = {"type": "Property", "value": {"@type": "DateTime", "@value": date}}
    if rank is not None:
        e["zoneRank"] = {"type": "Property", "value": rank}
    if label:
        e["zoneLabel"] = {"type": "Property", "value": label}
    return e


def veg(run="veg-1", date="2026-01-01T00:00:00Z", x1=200):
    half = x1 / 2
    return [_zone(f"{run}-a", 0, half, mean=0.2, run=run, method="vegetationIndex", date=date),
            _zone(f"{run}-b", half, x1, mean=0.8, run=run, method="vegetationIndex", date=date)]


MANUAL = "manual-1a2b3c4d5e6f"
T1 = f"urn:ngsi-ld:AgriManagementZone:acme:p1:{MANUAL[:15]}-1"
T2 = f"urn:ngsi-ld:AgriManagementZone:acme:p1:{MANUAL[:15]}-2"


def manual(date="2026-06-01T00:00:00Z"):
    return [_zone(T1, 0, 100, run=MANUAL, method="manual", date=date, rank=1, label="T1"),
            _zone(T2, 100, 200, run=MANUAL, method="manual", date=date, rank=2, label="T2")]


@pytest.fixture(autouse=True)
def orion(monkeypatch):
    FakeOrion.entities, FakeOrion.created, FakeOrion.calls = [], [], []
    monkeypatch.setattr("app.services.vra.zones.OrionClient", FakeOrion)
    monkeypatch.setattr("app.api.routing.OrionClient", FakeOrion)

    async def no_constraints(parcel_id, tenant_id):
        return {"access_point": None, "zones": []}
    monkeypatch.setattr("app.api.routing._fetch_parcel_constraints", no_constraints)


def _dist_ids(**params):
    r = client.get(f"/api/routing/zones/{PARCEL}/distribution", params=params)
    assert r.status_code == 200, r.text
    return sorted(z["id"] for z in r.json()["zones"])


def _swaths():
    return gen().json()["plan"]["swaths"]


def _rx(vra):
    return client.post("/api/routing/prescription",
                       json={"parcel_id": PARCEL, "swaths": _swaths(), "vra": vra})


def _vra(**kw):
    d = {"enabled": True, "source": "orion", "classes": C3, "unit": "kg_ha", "product": "N"}
    d.update(kw)
    return d


# ---- default zoning ----------------------------------------------------------

def test_default_ignores_newer_manual():
    FakeOrion.entities = veg() + manual(date="2026-06-01T00:00:00Z")
    assert _dist_ids() == ["veg-1-a", "veg-1-b"]


def test_default_is_latest_automatic_among_methods():
    older = [_zone(f"ter-{k}", 0, 200, mean=0.5, run="ter-1", method="terrain",
                   date="2025-01-01T00:00:00Z") for k in "ab"]
    FakeOrion.entities = older + veg(date="2026-01-01T00:00:00Z")
    assert _dist_ids() == ["veg-1-a", "veg-1-b"]


def test_legacy_zones_without_method_are_automatic():
    legacy = [_zone("Z0", 0, 100, mean=0.3), _zone("Z1", 100, 200, mean=0.6)]
    FakeOrion.entities = legacy + manual()
    assert _dist_ids() == ["Z0", "Z1"]


def test_only_manual_zonings_give_no_default():
    FakeOrion.entities = manual()
    r = client.get(f"/api/routing/zones/{PARCEL}/distribution")
    assert r.status_code == 200 and r.json()["zones"] == []


# ---- explicit choice ---------------------------------------------------------

def test_explicit_manual_run_is_used():
    FakeOrion.entities = veg() + manual()
    r = client.get(f"/api/routing/zones/{PARCEL}", params={"zoning_run_id": MANUAL})
    assert r.status_code == 200, r.text
    assert sorted(z["id"] for z in r.json()["data"]["zones"]) == [T1, T2]


def test_explicit_older_automatic_run_is_used():
    FakeOrion.entities = veg("veg-old", "2025-01-01T00:00:00Z") + veg("veg-new", "2026-01-01T00:00:00Z")
    assert _dist_ids(zoning_run_id="veg-old") == ["veg-old-a", "veg-old-b"]


def test_unknown_zoning_run_is_404():
    FakeOrion.entities = veg()
    r = client.get(f"/api/routing/zones/{PARCEL}/distribution", params={"zoning_run_id": "nope"})
    assert r.status_code == 404 and r.json()["code"] == "ZONING_NOT_FOUND"
    r = _rx(_vra(zoning_run_id="nope"))
    assert r.status_code == 404 and r.json()["code"] == "ZONING_NOT_FOUND"


def test_zonings_listing_shape():
    FakeOrion.entities = veg() + manual()
    r = client.get(f"/api/routing/zonings/{PARCEL}")
    assert r.status_code == 200, r.text
    zs = r.json()["zonings"]
    assert [z["run_id"] for z in zs] == [MANUAL, "veg-1"]  # most recent first
    m, v = zs
    assert m == {"run_id": MANUAL, "method": "manual", "date": "2026-06-01T00:00:00Z",
                 "zone_count": 2, "labels": ["T1", "T2"], "is_default": False}
    assert v["is_default"] is True and v["method"] == "vegetationIndex" and v["zone_count"] == 2


def test_prescription_uses_vra_zoning_run_id():
    # the newer zoning covers only half the parcel; the chosen older one covers it all
    FakeOrion.entities = veg("veg-old", "2025-01-01T00:00:00Z") + \
        veg("veg-new", "2026-01-01T00:00:00Z", x1=100)
    codes = lambda r: [w["code"] for w in r.json()["prescription"]["warnings"]]  # noqa: E731
    assert "VRA_UNCOVERED" in codes(_rx(_vra()))
    r = _rx(_vra(zoning_run_id="veg-old"))
    assert r.status_code == 200, r.text
    assert "VRA_UNCOVERED" not in codes(r)


# ---- per-zone rates (manual zonings carry no value) ----------------------------

def test_zone_rates_prescribe_each_manual_zone():
    FakeOrion.entities = veg() + manual()
    r = _rx(_vra(classes=[], zoning_run_id=MANUAL, zone_rates={T1: 120, T2: 80}))
    assert r.status_code == 200, r.text
    p = r.json()["prescription"]
    rows = [(c["index"], c["zone_id"], c["label"], c["rate"]) for c in p["classes"]]
    assert rows == [(0, T1, "T1", 120), (1, T2, "T2", 80)]
    assert all(c["min_pct"] is None and c["max_pct"] is None for c in p["classes"])
    assert all(c["area_ha"] > 0 for c in p["classes"])
    assert {f["properties"]["rate"] for f in p["zones"]["features"]} == {120, 80}
    seg_rates = {f["properties"]["rate"] for f in p["swath_segments"]["features"]}
    assert {120, 80} <= seg_rates
    assert "VRA_UNCOVERED" not in [w["code"] for w in p["warnings"]]


def test_zone_rates_missing_zone_is_422():
    FakeOrion.entities = manual()
    r = _rx(_vra(classes=[], zoning_run_id=MANUAL, zone_rates={T1: 120}))
    assert r.status_code == 422 and r.json()["code"] == "INVALID_VRA"
    assert r.json()["params"]["missing"] == [T2]


def test_zone_rates_unknown_zone_is_422():
    FakeOrion.entities = manual()
    r = _rx(_vra(classes=[], zoning_run_id=MANUAL,
                 zone_rates={T1: 120, T2: 80, "urn:ngsi-ld:AgriManagementZone:x": 1}))
    assert r.status_code == 422 and r.json()["code"] == "INVALID_VRA"
    assert r.json()["params"]["unknown"] == ["urn:ngsi-ld:AgriManagementZone:x"]


def test_zone_rates_negative_is_422():
    FakeOrion.entities = manual()
    r = _rx(_vra(classes=[], zoning_run_id=MANUAL, zone_rates={T1: -1, T2: 80}))
    assert r.status_code == 422


def test_zone_rates_with_external_source_is_422():
    r = _rx(_vra(source="external", classes=[], zone_rates={"a": 1},
                 external_features={"type": "FeatureCollection", "features": []}))
    assert r.status_code == 422 and r.json()["code"] == "INVALID_VRA"


def test_manual_zoning_without_rates_is_422_no_value():
    FakeOrion.entities = manual()
    r = _rx(_vra(zoning_run_id=MANUAL))
    assert r.status_code == 422 and r.json()["code"] == "INVALID_VRA"


def test_generate_persists_zone_rates_config():
    FakeOrion.entities = manual()
    r = gen(vra=_vra(classes=[], zoning_run_id=MANUAL, zone_rates={T1: 120, T2: 80}), persist=True)
    assert r.status_code == 200, r.text
    cfg = FakeOrion.created[0]["vraConfig"]["value"]
    assert cfg["zoning_run_id"] == MANUAL and cfg["zone_rates"] == {T1: 120, T2: 80}
