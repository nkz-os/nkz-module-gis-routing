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
