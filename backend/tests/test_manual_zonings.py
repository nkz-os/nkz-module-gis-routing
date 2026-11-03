"""Manual zonings: preview an uploaded or drawn set of polygons, save it as one run, delete it."""
import base64
import json

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point, box, mapping

from app.main import app
from tests.fixtures_parcels import wgs84, wgs84_point
from tests.test_vra_api import FakeOrion, PARCEL
from tests.test_vra_external import make_zip

client = TestClient(app)
NS = "urn:ngsi-ld:AgriManagementZone:"


def _coords(poly):
    return " ".join(f"{x},{y}" for x, y in wgs84(poly).exterior.coords)


def _kml(*placemarks):
    body = "".join(placemarks)
    return (f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2">'
            f"<Document>{body}</Document></kml>").encode()


def _pm_poly(name, poly):
    return (f"<Placemark><name>{name}</name><Polygon><outerBoundaryIs><LinearRing>"
            f"<coordinates>{_coords(poly)}</coordinates></LinearRing></outerBoundaryIs>"
            f"</Polygon></Placemark>")


def _pm_point(name, x, y):
    lon, lat = wgs84_point(Point(x, y))
    return f"<Placemark><name>{name}</name><Point><coordinates>{lon},{lat}</coordinates></Point></Placemark>"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class DeletingOrion(FakeOrion):
    deleted: list = []

    async def delete_entity(self, entity_id):
        DeletingOrion.deleted.append(entity_id)
        FakeOrion.entities = [e for e in FakeOrion.entities if e["id"] != entity_id]


@pytest.fixture(autouse=True)
def orion(monkeypatch):
    FakeOrion.entities, FakeOrion.created, FakeOrion.calls = [], [], []
    DeletingOrion.deleted = []
    for target in ("app.services.vra.zones.OrionClient", "app.api.routing.OrionClient",
                   "app.services.vra.manual_zonings.OrionClient"):
        monkeypatch.setattr(target, DeletingOrion)


def preview(fmt, content):
    return client.post("/api/routing/zonings/manual/preview",
                       json={"parcel_id": PARCEL, "format": fmt, "content": content})


def save(fmt, content, labels=None):
    body = {"parcel_id": PARCEL, "format": fmt, "content": content}
    if labels is not None:
        body["labels"] = labels
    return client.post("/api/routing/zonings/manual", json=body)


TWO = _kml(_pm_poly("T1 compost", box(0, 0, 100, 100)), _pm_poly("T2", box(100, 0, 200, 100)))


def test_preview_kml_two_polygons_with_names():
    r = preview("kml", _b64(TWO))
    assert r.status_code == 200, r.text
    b = r.json()
    assert [(z["rank"], z["label"]) for z in b["zones"]] == [(1, "T1 compost"), (2, "T2")]
    assert all(9000 < z["area_m2"] < 11000 for z in b["zones"])  # 100 m x 100 m
    assert b["rejected"] == []
    assert FakeOrion.created == []  # preview writes nothing


def test_preview_shapefile_uses_existing_parser():
    polys = [wgs84(box(0, 0, 100, 100)), wgs84(box(100, 0, 200, 100))]
    data = make_zip(polys, [("name", ("C", 20))], [["A"], ["B"]])
    b = preview("shapefile", _b64(data)).json()
    assert [z["label"] for z in b["zones"]] == ["A", "B"]


def test_preview_drawn_featurecollection():
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": mapping(wgs84(box(0, 0, 100, 100)))}]}
    b = preview("drawn", json.dumps(fc)).json()
    assert [(z["rank"], z["label"]) for z in b["zones"]] == [(1, "Z1")]


def test_preview_rejects_non_polygons_and_outside():
    far = box(5000, 5000, 5100, 5100)
    kml = _kml(_pm_point("tree", 10, 10), _pm_poly("in", box(0, 0, 100, 100)), _pm_poly("away", far))
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "line"},
         "geometry": mapping(LineString([(0, 0), (1, 1)]))}]}
    b = preview("kml", _b64(kml)).json()
    assert [z["label"] for z in b["zones"]] == ["in"]
    assert [(x["index"], x["reason"]) for x in b["rejected"]] == [(0, "not_polygon"), (2, "outside_parcel")]
    b = preview("drawn", json.dumps(fc)).json()
    assert b["zones"] == [] and b["rejected"][0]["reason"] == "not_polygon"


def test_commit_writes_one_run_with_ranks_and_labels():
    r = save("kml", _b64(TWO), labels={"2": "T2 control"})
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    assert run_id.startswith("manual-") and r.json()["zone_count"] == 2
    ents = FakeOrion.created
    run8 = run_id[len("manual-"):][:8]
    assert [e["id"] for e in ents] == [f"{NS}tenant-a:p1:manual-{run8}-1", f"{NS}tenant-a:p1:manual-{run8}-2"]
    for e in ents:
        assert not e["id"].startswith(f"{NS}p1:Z")
        assert e["zoningMethod"]["value"] == "manual"
        assert e["zoningRunId"]["value"] == run_id
        assert e["dateZoned"]["value"]["@type"] == "DateTime"
        assert e["hasAgriParcel"] == {"type": "Relationship", "object": PARCEL}
        assert e["area"]["unitCode"] == "MTK" and e["area"]["value"] > 0
    assert [e["zoneRank"]["value"] for e in ents] == [1, 2]
    assert [e["zoneLabel"]["value"] for e in ents] == ["T1 compost", "T2 control"]


def test_commit_refuses_when_nothing_valid():
    r = save("kml", _b64(_kml(_pm_point("tree", 10, 10))))
    assert r.status_code == 400 and r.json()["code"] == "ZONES_FILE_INVALID"
    assert FakeOrion.created == []


def test_saved_manual_zoning_is_listed_not_default():
    run_id = save("kml", _b64(TWO)).json()["run_id"]
    FakeOrion.entities = list(FakeOrion.created)
    zs = client.get(f"/api/routing/zonings/{PARCEL}").json()["zonings"]
    assert [(z["run_id"], z["method"], z["is_default"]) for z in zs] == [(run_id, "manual", False)]


def test_delete_manual_zoning():
    run_id = save("kml", _b64(TWO)).json()["run_id"]
    FakeOrion.entities = list(FakeOrion.created)
    r = client.delete(f"/api/routing/zonings/{PARCEL}/{run_id}")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 2 and len(DeletingOrion.deleted) == 2


def test_delete_automatic_zoning_is_refused():
    FakeOrion.entities = [{
        "id": f"{NS}p1:Z0", "type": "AgriManagementZone",
        "hasAgriParcel": {"type": "Relationship", "object": PARCEL},
        "location": {"type": "GeoProperty", "value": mapping(wgs84(box(0, 0, 100, 100)))},
        "zoningRunId": {"type": "Property", "value": "veg-1"},
        "zoningMethod": {"type": "Property", "value": "vegetationIndex"}}]
    r = client.delete(f"/api/routing/zonings/{PARCEL}/veg-1")
    assert r.status_code == 409 and r.json()["code"] == "ZONING_NOT_MANUAL"
    assert DeletingOrion.deleted == []


def test_delete_unknown_zoning_is_404():
    r = client.delete(f"/api/routing/zonings/{PARCEL}/manual-nope")
    assert r.status_code == 404 and r.json()["code"] == "ZONING_NOT_FOUND"
