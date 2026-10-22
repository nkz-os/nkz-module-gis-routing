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
