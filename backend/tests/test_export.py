import json
import pytest
from app.services.export_service import RouteExporter


@pytest.fixture
def sample_op():
    return {
        "id": "urn:x",
        "name": "Spraying - Parcela Norte",
        "operation_type": "spraying",
        "ab_line_geojson": json.dumps(
            {
                "type": "MultiLineString",
                "coordinates": [
                    [[-1.642, 42.817], [-1.6415, 42.8175]],
                    [[-1.6412, 42.818], [-1.6417, 42.8175]],
                ],
            }
        ),
        "implement_width": 24.0,
        "vra_enabled": False,
        "farm_name": "Test Farm",
        "parcel_name": "P1",
    }


def test_export_geojson(sample_op):
    result = RouteExporter().to_geojson(sample_op)
    data = json.loads(result)
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) > 0


def test_export_gpx(sample_op):
    result = RouteExporter().to_gpx(sample_op)
    assert "<gpx" in result and "<trk>" in result and "<trkpt" in result


def test_export_isoxml(sample_op):
    result = RouteExporter().to_isoxml(sample_op)
    assert "<ISO11783_TaskData" in result and "<TSK" in result and "<GPN" in result


# ISO 11783-10 TaskData has no XML namespace (the official XSD declares no targetNamespace).
NS = ""


def _rx(unit="kg_ha"):
    sq = [[-1.0, 42.0], [-1.0, 42.001], [-0.999, 42.001], [-0.999, 42.0], [-1.0, 42.0]]
    hole = [[-0.9995, 42.0003], [-0.9995, 42.0006], [-0.9992, 42.0006], [-0.9992, 42.0003], [-0.9995, 42.0003]]
    far = [[-0.99, 42.0], [-0.99, 42.001], [-0.989, 42.001], [-0.99, 42.0]]
    return {
        "unit": unit,
        "product": "Urea",
        "classes": [
            {"index": 0, "min_pct": 0, "max_pct": 50, "rate": 120.5},
            {"index": 1, "min_pct": 50, "max_pct": 100, "rate": 80},
        ],
        "zones": {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"class_index": 0, "rate": 120.5},
                 "geometry": {"type": "MultiPolygon", "coordinates": [[sq, hole], [far]]}},
                {"type": "Feature", "properties": {"class_index": 1, "rate": 80},
                 "geometry": {"type": "Polygon", "coordinates": [far]}},
            ],
        },
        "warnings": [],
    }


def test_isoxml_treatment_zones(sample_op):
    import xml.etree.ElementTree as ET
    sample_op["prescription"] = _rx()
    root = ET.fromstring(RouteExporter().to_isoxml(sample_op))
    tsk = root.find(f"{NS}TSK")
    tzns = tsk.findall(f"{NS}TZN")
    assert [t.get("A") for t in tzns] == ["0", "1"]
    assert all(t.get("B") for t in tzns)
    pdv0 = tzns[0].find(f"{NS}PDV")
    assert pdv0.get("A") == "0006" and pdv0.get("B") == "12050"
    assert tzns[1].find(f"{NS}PDV").get("B") == "8000"
    plns = tzns[0].findall(f"{NS}PLN")
    assert len(plns) == 2 and all(p.get("A") == "2" for p in plns)
    lsgs = plns[0].findall(f"{NS}LSG")
    assert [l.get("A") for l in lsgs] == ["1", "2"]
    first = lsgs[0].findall(f"{NS}PNT")
    assert len(first) == 4  # closing duplicate dropped
    assert first[0].get("C") == "42.000000000" and first[0].get("D") == "-1.000000000"
    assert all(p.get("A") == "2" for p in first)
    assert len(plns[1].findall(f"{NS}LSG")) == 1
    # A-B guidance still present (old operation: one GPN per route line)
    assert len(root.findall(f"{NS}PFD/{NS}GGP/{NS}GPN")) == 2


def test_isoxml_liquid_uses_volume_ddi(sample_op):
    import xml.etree.ElementTree as ET
    sample_op["prescription"] = _rx("l_ha")
    root = ET.fromstring(RouteExporter().to_isoxml(sample_op))
    pdv = root.find(f"{NS}TSK/{NS}TZN/{NS}PDV")
    assert pdv.get("A") == "0001"
    # 120.5 l/ha = 12050 mm3/m2 at resolution 0.01 -> raw 1205000
    assert pdv.get("B") == "1205000"


def test_isoxml_without_prescription_has_no_tzn(sample_op):
    assert "<TZN" not in RouteExporter().to_isoxml(sample_op)


def _iso(op):
    return RouteExporter().to_isoxml(op)


def test_isoxml_prescription_null_is_no_prescription(sample_op):
    sample_op["prescription"] = None
    assert "<TZN" not in _iso(sample_op)


def test_isoxml_zones_json_string_accepted(sample_op):
    rx = _rx()
    rx["zones"] = json.dumps(rx["zones"])
    sample_op["prescription"] = json.dumps(rx)
    assert _iso(sample_op).count("<TZN") == 2


def _bad_cases():
    out = {}
    out["list"] = [1, 2]
    out["unit"] = {**_rx(), "unit": "t_ha"}
    out["rate_none"] = {**_rx(), "classes": [{"index": 0, "rate": None}]}
    out["rate_nan"] = {**_rx(), "classes": [{"index": 0, "rate": float("nan")}]}
    out["rate_neg"] = {**_rx(), "classes": [{"index": 0, "rate": -1}]}
    out["no_classes"] = {k: v for k, v in _rx().items() if k != "classes"}
    out["zones_bad_str"] = {**_rx(), "zones": "{nope"}
    out["dup_index"] = {**_rx(), "classes": [{"index": 0, "rate": 1}, {"index": 0, "rate": 2}]}
    return out


@pytest.mark.parametrize("name", list(_bad_cases()))
def test_isoxml_invalid_prescription_raises(sample_op, name):
    from app.services.coverage.errors import PlanError
    sample_op["prescription"] = _bad_cases()[name]
    with pytest.raises(PlanError) as ei:
        _iso(sample_op)
    assert ei.value.code == "INVALID_VRA"


def test_isoxml_escapes_op_type_and_width(sample_op):
    import xml.etree.ElementTree as ET
    sample_op["operation_type"] = 'sp"ray<&'
    sample_op["implement_width"] = '2"4'
    root = ET.fromstring(_iso(sample_op))
    assert root.find(f"{NS}TSK").get("B").startswith('sp"ray<&')


def test_isoxml_skips_degenerate_rings_and_polygons(sample_op):
    import xml.etree.ElementTree as ET
    rx = _rx()
    sq = rx["zones"]["features"][1]["geometry"]["coordinates"][0]
    tiny = [[0, 0], [1, 1], [0, 0]]
    rx["zones"]["features"][0]["geometry"] = {
        "type": "MultiPolygon",
        "coordinates": [[tiny], [sq, tiny]],
    }
    sample_op["prescription"] = rx
    root = ET.fromstring(_iso(sample_op))
    tzn0 = root.find(f"{NS}TSK/{NS}TZN")
    plns = tzn0.findall(f"{NS}PLN")
    assert len(plns) == 1 and len(plns[0].findall(f"{NS}LSG")) == 1


def _entity(rx):
    return {
        "id": "urn:ngsi-ld:AgriParcelOperation:t:op1",
        "name": {"value": "n"},
        "operationType": {"value": "spraying"},
        "location": {"value": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}},
        "prescription": rx,
    }


class _Orion:
    def __init__(self, ent):
        self.ent = ent

    async def get_entity(self, *a, **k):
        return self.ent

    async def close(self):
        pass


def _client(monkeypatch, ent):
    from fastapi.testclient import TestClient
    from app.main import create_app
    monkeypatch.setattr("app.api.routing.OrionClient", lambda *a, **k: _Orion(ent))
    return TestClient(create_app())


def test_export_route_isoxml_includes_zones(monkeypatch):
    c = _client(monkeypatch, _entity({"type": "Property", "value": _rx()}))
    r = c.get("/api/routing/export/op1?format=isoxml")
    assert r.status_code == 200 and r.text.count("<TZN") == 2


def test_export_route_null_prescription_ok(monkeypatch):
    c = _client(monkeypatch, _entity(None))
    r = c.get("/api/routing/export/op1?format=isoxml")
    assert r.status_code == 200 and "<TZN" not in r.text


def test_export_route_invalid_prescription_422_only_isoxml(monkeypatch):
    c = _client(monkeypatch, _entity({"type": "Property", "value": [1]}))
    r = c.get("/api/routing/export/op1?format=isoxml")
    assert r.status_code == 422
    assert r.json()["code"] == "INVALID_VRA" and r.json()["detail"] and "params" in r.json()
    assert c.get("/api/routing/export/op1?format=geojson").status_code == 200
    assert c.get("/api/routing/export/op1?format=gpx").status_code == 200


PARCEL = {"type": "Polygon", "coordinates": [[[-1.0, 42.0], [-1.0, 42.001], [-0.999, 42.001],
                                              [-0.999, 42.0], [-1.0, 42.0]]]}


def _swaths():
    return [
        {"type": "Feature", "properties": {"index": 0, "kind": "work"},
         "geometry": {"type": "LineString", "coordinates": [[-0.9995, 42.0001], [-0.9995, 42.0005], [-0.9995, 42.0009]]}},
        {"type": "Feature", "properties": {"index": 1, "kind": "work"},
         "geometry": {"type": "LineString", "coordinates": [[-0.9992, 42.0009], [-0.9992, 42.0001]]}},
        {"type": "Feature", "properties": {"index": 2, "kind": "headland"},
         "geometry": {"type": "LineString", "coordinates": [[-0.9999, 42.0], [-0.9991, 42.0]]}},
    ]


def _rootx(op):
    import xml.etree.ElementTree as ET
    return ET.fromstring(_iso(op))


def test_isoxml_one_guidance_line_per_swath(sample_op):
    sample_op["swaths"] = _swaths()
    root = _rootx(sample_op)
    gpns = root.findall("PFD/GGP/GPN")
    assert len(gpns) == 3  # swaths, not the 2 route lines
    for g in gpns:
        assert g.get("C") == "1"
        lsg = g.findall("LSG")
        assert len(lsg) == 1 and lsg[0].get("A") == "5"
        pnts = lsg[0].findall("PNT")
        assert [p.get("A") for p in pnts] == ["6", "7"]
    p = gpns[0].find("LSG").findall("PNT")
    assert p[0].get("C") == "42.000100000" and p[0].get("D") == "-0.999500000"
    assert p[1].get("C") == "42.000900000"  # B = last vertex
    assert len({g.get("A") for g in gpns}) == 3
    assert "headland" in gpns[2].get("B")


def test_isoxml_parcel_boundary_partfield(sample_op):
    sample_op["parcel_geometry"] = PARCEL
    sample_op["swaths"] = _swaths()
    root = _rootx(sample_op)
    pfd = root.find("PFD")
    assert pfd is not None and pfd.get("C") == "P1"
    assert 9000 < int(pfd.get("D")) < 9500  # ~0.001 deg x 0.001 deg at 42N, in m2
    pln = pfd.find("PLN")
    assert pln.get("A") == "1"
    lsg = pln.find("LSG")
    assert lsg.get("A") == "1" and len(lsg.findall("PNT")) == 4
    assert root.find("TSK").get("E") == pfd.get("A")


def test_isoxml_without_parcel_still_valid_partfield(sample_op):
    root = _rootx(sample_op)
    pfd = root.find("PFD")
    assert pfd is not None and pfd.find("PLN") is None and pfd.get("D") == "0"


def test_isoxml_swaths_and_vra_together(sample_op):
    sample_op["swaths"] = _swaths()
    sample_op["prescription"] = _rx()
    root = _rootx(sample_op)
    assert len(root.findall("PFD/GGP/GPN")) == 3
    assert len(root.findall("TSK/TZN")) == 2


def test_isoxml_malformed_swath_skipped(sample_op):
    sample_op["swaths"] = _swaths() + [
        {"type": "Feature", "properties": {"index": 9}, "geometry": {"type": "LineString", "coordinates": [[0, 0]]}},
        {"type": "Feature", "properties": {"index": 10}, "geometry": None}]
    assert len(_rootx(sample_op).findall("PFD/GGP/GPN")) == 3


def test_isoxml_validates_against_official_xsd(sample_op):
    """Local check: set NKZ_ISOXML_XSD to ISO11783_TaskFile_V4-3.xsd (not shipped: licence)."""
    import os
    path = os.environ.get("NKZ_ISOXML_XSD")
    if not path:
        pytest.skip("NKZ_ISOXML_XSD not set")
    from lxml import etree
    schema = etree.XMLSchema(etree.parse(path))
    sample_op["parcel_geometry"] = PARCEL
    sample_op["swaths"] = _swaths()
    sample_op["prescription"] = _rx()
    for op in (sample_op, {**sample_op, "swaths": None}):
        doc = etree.fromstring(_iso(op).encode())
        assert schema.validate(doc), schema.error_log


def test_export_route_isoxml_uses_stored_swaths_and_parcel(monkeypatch):
    ent = _entity(None)
    ent["nkz:swaths"] = {"type": "Property", "value": {"type": "FeatureCollection", "features": _swaths()}}
    ent["hasAgriParcel"] = {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:parcelx"}
    seen = []

    class O(_Orion):
        async def get_entity(self, eid, *a, **k):
            seen.append(eid)
            if eid.endswith("parcelx"):
                return {"id": eid, "name": {"value": "Norte"}, "location": {"value": PARCEL}}
            return self.ent

    from fastapi.testclient import TestClient
    from app.main import create_app
    monkeypatch.setattr("app.api.routing.OrionClient", lambda *a, **k: O(ent))
    r = TestClient(create_app()).get("/api/routing/export/op1?format=isoxml")
    assert r.status_code == 200
    assert r.text.count("<GPN") == 3 and 'A="1"' in r.text and "Norte" in r.text
