"""Client-chosen zone labels (and the zone level) in prescriptions, ISOXML and shapefile."""
import io
import json
import xml.etree.ElementTree as ET
import zipfile

import pytest
import shapefile
from pyproj import Transformer
from fastapi.testclient import TestClient
from shapely.geometry import LineString, box, mapping

from app.main import app
from app.services.coverage.plan import Swath
from app.services.export_service import RouteExporter
from app.services.vra.classify import ZoneValue
from app.services.vra.prescription import (
    build_prescription, build_zone_rate_prescription, persistable_prescription)
from app.services.vra.zones import zone_level
from tests.fixtures_parcels import wgs84
from tests.test_vra_api import C3, FakeOrion, PARCEL
from tests.test_zonings import _vra, _zone

client = TestClient(app)
_TO_WGS = Transformer.from_crs("EPSG:32630", "EPSG:4326", always_xy=True)
# Local metres (origin 0,0) <-> WGS84, as the real code gets them from the parcel.
to_wgs_fn = lambda x, y, z=None: _TO_WGS.transform(x + 600000.0, y + 4760000.0)  # noqa: E731
to_utm_fn = lambda x, y, z=None: tuple(  # noqa: E731
    a - b for a, b in zip(_TO_WGS.transform(x, y, direction="INVERSE"), (600000.0, 4760000.0)))
PARCEL_BOX = box(0, 0, 100, 100)

HIGH = "Vigor alto"
MED = "Vigor medio"
LOW = "Vigor bajo, ñandú á"
SW = [Swath(index=0, kind="work", geometry=LineString([(0, 50), (100, 50)]))]


def _zones():
    return [ZoneValue(id=f"z{i}", mean=m, area_ha=0.3, geometry=wgs84(box(x0, 0, x1, 100)))
            for i, (m, x0, x1) in enumerate([(0.2, 0, 30), (0.5, 30, 60), (0.8, 60, 100)])]


@pytest.fixture(autouse=True)
def orion(monkeypatch):
    FakeOrion.entities, FakeOrion.created, FakeOrion.calls = [], [], []
    monkeypatch.setattr("app.services.vra.zones.OrionClient", FakeOrion)
    monkeypatch.setattr("app.api.routing.OrionClient", FakeOrion)


def _op(rx):
    return {"id": "urn:x", "operation_type": "spraying", "implement_width": 12,
            "ab_line_geojson": json.dumps({"type": "MultiLineString", "coordinates": [
                [[-1.642, 42.817], [-1.6415, 42.8175]]]}),
            "prescription": json.loads(json.dumps(persistable_prescription(rx)))}


def _tzn_names(op):
    xml = RouteExporter().to_isoxml(op)
    root = ET.fromstring(xml)
    ns = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
    return [t.get("B") for t in root.iter(f"{ns}TZN")]


def _dbf_zones(op):
    zf = zipfile.ZipFile(io.BytesIO(RouteExporter().to_shapefile(op)))
    r = shapefile.Reader(shp=io.BytesIO(zf.read("prescription.shp")),
                         shx=io.BytesIO(zf.read("prescription.shx")),
                         dbf=io.BytesIO(zf.read("prescription.dbf")), encoding="utf-8")
    return [rec["zone"] for rec in r.records()]


# ---- per-zone mode -------------------------------------------------------------

def _per_zone(labels):
    zones = [{"id": f"z{i}", "label": f"T{i}", "rank": i + 1,
              "geometry": wgs84(box(x0, 0, x1, 100))}
             for i, (x0, x1) in enumerate([(0, 30), (30, 60), (60, 100)])]
    return build_zone_rate_prescription(
        zones=zones, zone_rates={"z0": 10, "z1": 20, "z2": 30}, rest_rate=0, unit="kg_ha",
        product="N", swaths_utm=SW, parcel_utm=PARCEL_BOX, to_utm=to_utm_fn, to_wgs=to_wgs_fn,
        zone_labels=labels)


def test_per_zone_labels_replace_and_reach_exports():
    rx = _per_zone({"z0": HIGH, "z1": MED, "z2": LOW})
    assert [c["label"] for c in rx["classes"]] == [HIGH, MED, LOW]
    assert [f["properties"]["label"] for f in rx["zones"]["features"]] == [HIGH, MED, LOW]
    op = _op(rx)
    assert op["prescription"]["classes"][2]["label"] == LOW  # survives storage
    assert _tzn_names(op)[:3] == [HIGH, MED, LOW]
    assert _dbf_zones(op) == [HIGH, MED, LOW]


def test_per_zone_without_labels_is_unchanged():
    rx = _per_zone(None)
    assert [c["label"] for c in rx["classes"]] == ["T0", "T1", "T2"]
    assert _per_zone({}) == rx


def test_per_zone_partial_labels_keep_the_others():
    rx = _per_zone({"z1": MED})
    assert [c["label"] for c in rx["classes"]] == ["T0", MED, "T2"]


def test_per_zone_unknown_label_keys_are_ignored():
    assert _per_zone({"zX": "Otra zona"}) == _per_zone(None)


# ---- class mode ----------------------------------------------------------------

def _class_mode(labels):
    return build_prescription(
        zones=_zones(), classes=C3, unit="kg_ha", product="N", invert=False, swaths_utm=SW,
        parcel_utm=PARCEL_BOX, to_utm=to_utm_fn, to_wgs=to_wgs_fn, zone_labels=labels)


def test_class_mode_label_is_that_of_its_zones_and_reaches_exports():
    rx = _class_mode({"z0": HIGH, "z1": MED, "z2": LOW})
    assert [c["label"] for c in rx["classes"]] == [HIGH, MED, LOW]
    op = _op(rx)
    assert _tzn_names(op)[:3] == [HIGH, MED, LOW]
    assert _dbf_zones(op) == [HIGH, MED, LOW]


def test_class_mode_joins_the_labels_of_zones_sharing_a_class():
    two = [{"min_pct": 0, "max_pct": 67, "rate": 100}, {"min_pct": 67, "max_pct": 100, "rate": 200}]
    rx = build_prescription(
        zones=_zones(), classes=two, unit="kg_ha", product="N", invert=False, swaths_utm=SW,
        parcel_utm=PARCEL_BOX, to_utm=to_utm_fn, to_wgs=to_wgs_fn,
        zone_labels={"z0": "Bajo", "z1": "Medio", "z2": "Alto", "zX": "Nada"})
    assert [c["label"] for c in rx["classes"]] == ["Bajo + Medio", "Alto"]


def test_class_mode_without_labels_or_unknown_keys_is_unchanged():
    base = _class_mode(None)
    assert all("label" not in c for c in base["classes"])
    assert _class_mode({"zX": "Nada"}) == base


# ---- request model -------------------------------------------------------------

def _post(vra_body, swaths=None):
    line = mapping(LineString([wgs84(box(0, 0, 1, 1)).exterior.coords[0],
                               wgs84(box(0, 0, 1, 1)).exterior.coords[2]]))
    return client.post("/api/routing/prescription", json={
        "parcel_id": PARCEL, "swaths": swaths or [{"index": 0, "kind": "work", "geometry": line}],
        "vra": vra_body})


def test_api_labels_reach_the_prescription_in_both_modes():
    FakeOrion.entities = [_zone("za", 0, 100, mean=0.2, run="r1", method="vegetationIndexMultiDate"),
                          _zone("zb", 100, 200, mean=0.8, run="r1", method="vegetationIndexMultiDate")]
    r = _post(_vra(zone_labels={"za": "Vigor bajo", "zb": "Vigor alto", "zq": "x"}))
    assert r.status_code == 200, r.text
    assert [c["label"] for c in r.json()["prescription"]["classes"]
            if "label" in c] == ["Vigor bajo", "Vigor alto"]
    r = _post(_vra(classes=[], zone_rates={"za": 1, "zb": 2}, rest_rate=0,
                   zone_labels={"za": "Vigor bajo", "zq": "x"}))
    assert r.status_code == 200, r.text
    assert [c["label"] for c in r.json()["prescription"]["classes"]][0] == "Vigor bajo"


@pytest.mark.parametrize("labels", [
    {f"z{i}": "a" for i in range(51)},   # too many
    {"za": ""},                          # empty
    {"za": "   "},                       # blank
    {"za": "x" * 81},                    # too long
    {"": "a"},                           # empty key
    {"za": 5},                           # not text
    ["za"],                              # not a map
])
def test_api_rejects_invalid_zone_labels(labels):
    FakeOrion.entities = []
    r = _post(_vra(zone_labels=labels))
    assert r.status_code == 422
    assert FakeOrion.calls == []  # refused before any broker read


def test_api_accepts_the_limits():
    FakeOrion.entities = [_zone("za", 0, 100, mean=0.2), _zone("zb", 100, 200, mean=0.8)]
    labels = {f"zz{i}": "a" for i in range(49)} | {"za": "ñ" * 80}
    assert _post(_vra(zone_labels=labels)).status_code == 200


# ---- level ---------------------------------------------------------------------

@pytest.mark.parametrize("attr", ["zoneLevel", "nkz:zoneLevel", "https://nkz-os.org/ns/zoneLevel"])
@pytest.mark.parametrize("form", ["normalized", "keyvalues"])
def test_level_is_read_in_every_spelling_and_form(attr, form):
    e = {"id": "z"}
    e[attr] = {"type": "Property", "value": "critical"} if form == "normalized" else "critical"
    assert zone_level(e) == "critical"


@pytest.mark.parametrize("value", ["extreme", "", "HIGH", None, 3, "Vigor alto"])
def test_unknown_level_is_null(value):
    assert zone_level({"id": "z", "zoneLevel": {"type": "Property", "value": value}}) is None
    assert zone_level({"id": "z", "zoneLevel": value}) is None


def test_no_level_is_null():
    assert zone_level({"id": "z"}) is None


def _multi(zid, rank, level, spelling="zoneLevel", dates=True):
    e = _zone(zid, 0, 100, mean=0.5, run="run-md", method="vegetationIndexMultiDate",
              date="2026-06-01T00:00:00Z", rank=rank)
    e[spelling] = {"type": "Property", "value": level}
    e["zoneName"] = {"type": "Property", "value": level}
    if dates:
        e["sourceDates"] = {"type": "Property", "value": ["2026-05-01", "2026-06-01"]}
    return e


def test_zones_route_carries_level():
    FakeOrion.entities = [_multi("zh", 1, "high"), _multi("zc", 4, "critical", "nkz:zoneLevel"),
                          _multi("zu", 2, "mystery", dates=False)]
    r = client.get(f"/api/routing/zones/{PARCEL}")
    assert r.status_code == 200, r.text
    by = {z["id"]: z for z in r.json()["data"]["zones"]}
    assert (by["zh"]["level"], by["zc"]["level"], by["zu"]["level"]) == ("high", "critical", None)


def test_zones_route_old_zoning_has_null_level():
    FakeOrion.entities = [_zone("zo", 0, 100, mean=0.5, run="r", method="vegetationIndex")]
    z = client.get(f"/api/routing/zones/{PARCEL}").json()["data"]["zones"][0]
    assert z["level"] is None


def test_zonings_route_carries_levels_in_rank_order():
    FakeOrion.entities = [_multi("zc", 4, "critical"), _multi("zh", 1, "high"),
                          _multi("zm", 2, "medium", "https://nkz-os.org/ns/zoneLevel")]
    r = client.get(f"/api/routing/zonings/{PARCEL}")
    assert r.status_code == 200, r.text
    z = r.json()["zonings"][0]
    assert z["method"] == "vegetationIndexMultiDate"
    assert z["levels"] == ["high", "medium", "critical"]
    assert z["zone_count"] == 3


def test_zonings_route_old_entries_keep_shape_plus_null_levels():
    FakeOrion.entities = [_zone("zo", 0, 100, mean=0.5, run="r", method="vegetationIndex",
                                date="2026-01-01T00:00:00Z")]
    z = client.get(f"/api/routing/zonings/{PARCEL}").json()["zonings"][0]
    assert z["levels"] == [None] and z["labels"] == [None]
