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
    assert "<ISO11783TaskData" in result and "<TSK" in result and "<GPN" in result


NS = "{http://www.isobus.net/xml/ISO11783_TaskData}"


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
    assert first[0].get("C") == "42.0" and first[0].get("D") == "-1.0"
    assert all(p.get("A") == "2" for p in first)
    assert len(plns[1].findall(f"{NS}LSG")) == 1
    # A-B guidance output unchanged
    assert tsk.find(f"{NS}GPN") is not None


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
    assert root.find(f"{NS}TSK").get("TSKNAME").startswith('sp"ray<&')


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
