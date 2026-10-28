"""GET /operations/{id}/plan: the whole operation as one FeatureCollection."""
import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.plan_export import plan_feature_collection

NS = "https://nkz-os.org/ns/"
PARCEL = {"type": "Polygon", "coordinates": [[[-2.0, 43.0], [-1.9975, 43.0], [-1.9975, 43.0009],
                                              [-2.0, 43.0009], [-2.0, 43.0]]]}
SW0 = {"type": "LineString", "coordinates": [[-1.9999, 43.0002], [-1.9976, 43.0002]]}
SW1 = {"type": "LineString", "coordinates": [[-1.9999, 43.0006], [-1.9976, 43.0006]]}
# Class 0 covers the west half, class 1 the east half.
Z0 = {"type": "Polygon", "coordinates": [[[-2.0, 43.0], [-1.99875, 43.0], [-1.99875, 43.0009],
                                          [-2.0, 43.0009], [-2.0, 43.0]]]}
Z1 = {"type": "Polygon", "coordinates": [[[-1.99875, 43.0], [-1.9975, 43.0], [-1.9975, 43.0009],
                                          [-1.99875, 43.0009], [-1.99875, 43.0]]]}
OP_ID = "urn:ngsi-ld:AgriParcelOperation:tenant-a:op1"
PID = "urn:ngsi-ld:AgriParcel:p1"


def _p(v):
    return {"type": "Property", "value": v}


def _geo(v):
    return {"type": "GeoProperty", "value": v}


def _work(prefix="", vra=False):
    def k(n):
        return prefix + n
    e = {
        "id": OP_ID, "type": "AgriParcelOperation",
        "operationType": _p("tillage"),
        "location": _geo({"type": "LineString", "coordinates": [[-1.9999, 43.0002], [-1.9976, 43.0006]]}),
        "hasAgriParcel": {"type": "Relationship", "object": PID},
        k("planVersion"): _p(1),
        k("accessPoint"): _geo({"type": "Point", "coordinates": [-2.0, 43.0001]}),
        k("accessPath"): _geo({"type": "LineString", "coordinates": [[-2.0, 43.0001], [-1.9999, 43.0002]]}),
        k("exclusionZones"): _p({"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": Z1, "properties": {"id": "z"}}]}),
        k("workingArea"): _geo(PARCEL),
        k("swaths"): _p({"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": SW0, "properties": {"index": 0, "kind": "work"}},
            {"type": "Feature", "geometry": SW1, "properties": {"index": 1, "kind": "headland"}}]}),
    }
    if vra:
        e[k("vraConfig")] = _p({"unit": "kg_ha"})
        e[k("prescription")] = _p({"unit": "kg_ha", "zones": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": Z0, "properties": {"class_index": 0, "rate": 50.0}},
            {"type": "Feature", "geometry": Z1, "properties": {"class_index": 1, "rate": 90.0}}]}})
    return e


def _els(fc):
    out = {}
    for f in fc["features"]:
        out.setdefault(f["properties"]["element"], []).append(f)
    return out


@pytest.mark.parametrize("prefix", ["", "nkz:", NS])
def test_full_work_plan_any_attribute_form(prefix):
    fc = plan_feature_collection(_work(prefix), parcel_geometry=PARCEL)
    assert fc["type"] == "FeatureCollection"
    assert fc["properties"] == {"plan_version": 1, "operation_id": OP_ID,
                                "operation_type": "tillage", "partial": False}
    els = _els(fc)
    assert set(els) == {"route", "swath", "access_path", "access_point", "exit_point",
                        "exclusion_zone", "parcel_boundary", "working_area"}
    assert [(f["properties"]["index"], f["properties"]["kind"]) for f in els["swath"]] == [(0, "work"), (1, "headland")]
    assert els["exit_point"][0]["geometry"] == {"type": "Point", "coordinates": [-1.9976, 43.0006]}
    assert els["parcel_boundary"][0]["geometry"] == PARCEL


def test_vra_segments_recomputed_per_class():
    fc = plan_feature_collection(_work(vra=True), parcel_geometry=PARCEL)
    els = _els(fc)
    assert len(els["prescription_zone"]) == 2
    assert {(f["properties"]["class_index"], f["properties"]["rate"], f["properties"]["unit"])
            for f in els["prescription_zone"]} == {(0, 50.0, "kg_ha"), (1, 90.0, "kg_ha")}
    segs = [f for f in els["swath"] if f["properties"]["index"] == 0]
    assert sorted((f["properties"]["class_index"], f["properties"]["rate"]) for f in segs) == [(0, 50.0), (1, 90.0)]
    assert all(f["properties"]["kind"] == "work" for f in segs)


def test_transit_plan():
    e = {"id": OP_ID, "type": "AgriParcelOperation", "operationType": _p("transit"),
         "location": _geo(SW0),
         "elevationProfile": _p([[-1.9999, 43.0002, 100.0], [-1.9976, 43.0002, 105.0]]),
         "transitMetrics": _p({"distance_m": 150.0, "cumulative_climb_m": 5.0})}
    fc = plan_feature_collection(e)
    assert fc["properties"]["operation_type"] == "transit"
    assert fc["properties"]["partial"] is False
    (t,) = fc["features"]
    assert t["properties"]["element"] == "transit"
    assert t["properties"]["elevation_profile"][1][2] == 105.0
    assert t["properties"]["metrics"]["distance_m"] == 150.0
    assert t["geometry"] == SW0


def test_old_operation_is_partial_not_an_error():
    e = {"id": OP_ID, "type": "AgriParcelOperation", "operationType": _p("tillage"),
         "location": _geo(SW0)}
    fc = plan_feature_collection(e)
    assert fc["properties"]["partial"] is True
    assert [f["properties"]["element"] for f in fc["features"]] == ["route", "exit_point"]


def test_operation_without_any_geometry_is_empty_partial():
    fc = plan_feature_collection({"id": OP_ID, "type": "AgriParcelOperation"})
    assert fc["features"] == [] and fc["properties"]["partial"] is True


class _Orion:
    entities: dict = {}

    def __init__(self, *a, **k):
        pass

    async def get_entity(self, eid, *a, **k):
        if eid not in _Orion.entities:
            req = httpx.Request("GET", "http://orion/x")
            raise httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, request=req))
        return _Orion.entities[eid]

    async def close(self):
        pass


@pytest.fixture
def client(monkeypatch):
    _Orion.entities = {OP_ID: _work(vra=True), PID: {"id": PID, "location": _geo(PARCEL)}}
    monkeypatch.setattr("app.api.routing.OrionClient", _Orion)
    return TestClient(create_app())


def test_endpoint_returns_plan(client):
    r = client.get(f"/api/routing/operations/{OP_ID}/plan")
    assert r.status_code == 200
    els = _els(r.json())
    assert "parcel_boundary" in els and "prescription_zone" in els


def test_endpoint_unknown_operation_404(client):
    r = client.get("/api/routing/operations/urn:ngsi-ld:AgriParcelOperation:tenant-a:nope/plan")
    assert r.status_code == 404
    assert r.json()["code"] == "OPERATION_NOT_FOUND"


def test_endpoint_missing_parcel_keeps_plan(client):
    del _Orion.entities[PID]
    r = client.get(f"/api/routing/operations/{OP_ID}/plan")
    assert r.status_code == 200
    assert "parcel_boundary" not in _els(r.json())


def test_outside_prescription_zones_rate_is_zero():
    """Same semantics as the ISOXML fallback: no dose outside the zones (owner decision)."""
    e = _work(vra=True)
    e["swaths"]["value"]["features"][0]["geometry"] = {
        "type": "LineString", "coordinates": [[-1.9999, 43.0002], [-1.9976, 43.0002]]}
    # shrink class 1 so part of the swath is outside every zone
    e["prescription"]["value"]["zones"]["features"][1]["geometry"] = {
        "type": "Polygon", "coordinates": [[[-1.99875, 43.0], [-1.9985, 43.0], [-1.9985, 43.0009],
                                            [-1.99875, 43.0009], [-1.99875, 43.0]]]}
    fc = plan_feature_collection(e, parcel_geometry=PARCEL)
    outside = [f for f in fc["features"] if f["properties"]["element"] == "swath"
               and f["properties"].get("class_index") is None and f["properties"]["index"] == 0]
    assert outside and all(f["properties"]["rate"] == 0 for f in outside)
    assert fc["properties"]["outside_rate"] == 0


def test_stored_exit_point_and_return_path_are_emitted():
    ret = {"type": "LineString", "coordinates": [[-1.9976, 43.0006], [-2.0, 43.0001]]}
    e = _work()
    e["returnPath"] = _geo(ret)
    e["exitPoint"] = _geo({"type": "Point", "coordinates": [-1.9976, 43.0006]})
    els = _els(plan_feature_collection(e, parcel_geometry=PARCEL))
    assert els["exit_point"][0]["geometry"]["coordinates"] == [-1.9976, 43.0006]
    assert els["return_path"][0]["geometry"] == ret


def test_malformed_swath_is_skipped_not_a_500():
    e = _work(vra=True)
    e["swaths"]["value"]["features"].append({"type": "Feature", "geometry": None, "properties": {"index": 9}})
    e["swaths"]["value"]["features"].append({"type": "Feature", "geometry": {"type": "LineString"}, "properties": {"index": 10}})
    fc = plan_feature_collection(e, parcel_geometry=PARCEL)
    assert {f["properties"]["index"] for f in fc["features"] if f["properties"]["element"] == "swath"} == {0, 1}
    assert fc["properties"]["partial"] is False


def test_non_operation_entity_is_rejected(client):
    _Orion.entities[OP_ID] = {"id": OP_ID, "type": "AgriParcel"}
    r = client.get(f"/api/routing/operations/{OP_ID}/plan")
    assert r.status_code == 404 and r.json()["code"] == "OPERATION_NOT_FOUND"


def test_failed_parcel_read_marks_plan_partial(client, monkeypatch):
    del _Orion.entities[PID]
    r = client.get(f"/api/routing/operations/{OP_ID}/plan")
    assert r.json()["properties"]["partial"] is True


def test_transit_does_not_fetch_the_parcel(client):
    e = {"id": OP_ID, "type": "AgriParcelOperation", "operationType": _p("transit"),
         "location": _geo(SW0), "hasAgriParcel": {"type": "Relationship", "object": PID}}
    _Orion.entities[OP_ID] = e
    asked = []
    orig = _Orion.get_entity

    async def spy(self, eid, *a, **k):
        asked.append(eid)
        return await orig(self, eid, *a, **k)
    _Orion.get_entity = spy
    try:
        client.get(f"/api/routing/operations/{OP_ID}/plan")
    finally:
        _Orion.get_entity = orig
    assert asked == [OP_ID]
