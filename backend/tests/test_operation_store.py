# backend/tests/test_operation_store.py
from app.services import operation_store as store


def _op_entity(**over):
    e = {
        "id": "urn:ngsi-ld:AgriParcelOperation:tenant-a:op1",
        "type": "AgriParcelOperation",
        "operationType": {"type": "Property", "value": "spraying"},
        "status": {"type": "Property", "value": "planned"},
        "refAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:p1"},
        "location": {"type": "GeoProperty", "value": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}},
        "swathCount": {"type": "Property", "value": 7},
        "fieldEfficiency": {"type": "Property", "value": 0.83},
        "workedDistance": {"type": "Property", "value": 1234.5},
        "nonWorkingDistance": {"type": "Property", "value": 210.0},
        "coveredAreaHa": {"type": "Property", "value": 4.2},
        "isTemplate": {"type": "Property", "value": False},
        "generationConfig": {"type": "Property", "value": {"pattern": "boustrophedon", "width_m": 24}},
        "vraConfig": {"type": "Property", "value": {"source": "orion", "base_rate": 100}},
    }
    e.update(over)
    return e


def test_is_template_entity_defaults_false_when_absent():
    e = _op_entity()
    del e["isTemplate"]
    assert store.is_template_entity(e) is False


def test_is_template_entity_true():
    assert store.is_template_entity(_op_entity(isTemplate={"type": "Property", "value": True})) is True


def test_operation_to_row_is_lightweight_no_geometry():
    row = store.operation_to_row(_op_entity())
    assert row["id"] == "urn:ngsi-ld:AgriParcelOperation:tenant-a:op1"
    assert row["parcel_id"] == "urn:ngsi-ld:AgriParcel:p1"
    assert row["operation_type"] == "spraying"
    assert row["status"] == "planned"
    assert row["swath_count"] == 7
    assert row["field_efficiency"] == 0.83
    assert row["worked_distance_m"] == 1234.5
    assert row["non_working_distance_m"] == 210.0
    assert row["covered_area_ha"] == 4.2
    assert "location" not in row and "route" not in row


def test_operation_to_row_missing_metrics_are_none():
    e = _op_entity()
    for k in ("fieldEfficiency", "workedDistance", "nonWorkingDistance", "coveredAreaHa", "swathCount"):
        del e[k]
    row = store.operation_to_row(e)
    assert row["field_efficiency"] is None
    assert row["swath_count"] is None


def test_operation_to_detail_includes_geometry_and_config():
    d = store.operation_to_detail(_op_entity())
    assert d["route"] == {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
    assert d["generation_config"] == {"pattern": "boustrophedon", "width_m": 24}
    assert d["vra_config"] == {"source": "orion", "base_rate": 100}
