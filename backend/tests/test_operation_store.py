# backend/tests/test_operation_store.py
from app.services import operation_store as store


def _op_entity(**over):
    e = {
        "id": "urn:ngsi-ld:AgriParcelOperation:tenant-a:op1",
        "type": "AgriParcelOperation",
        "operationType": {"type": "Property", "value": "spraying"},
        "status": {"type": "Property", "value": "planned"},
        "hasAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:p1"},
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


# ---------------------------------------------------------------------------
# Task 2: entity builders
# ---------------------------------------------------------------------------
import json
from types import SimpleNamespace
from shapely.geometry import LineString


class _PC:
    heading_deg = 30.0
    width_m = 24.0
    overlap_pct = 5.0
    headland_passes = 1
    direction = "outside-in"
    heading_objective = "efficiency"
    turning_radius_m = 6.5


class _VRA:
    enabled = True
    source = "orion"
    base_rate = 100.0
    rate_unit = "l_ha"
    zone_ids = ["urn:ngsi-ld:AgriManagementZone:z1"]


def _body():
    return SimpleNamespace(
        parcel_id="urn:ngsi-ld:AgriParcel:p1",
        tractor_id="urn:ngsi-ld:ManufacturingMachine:t1",
        implement_id=None,
        pattern="boustrophedon",
        pattern_config=_PC(),
        operation_type="spraying",
        coupling_model="rigid",
        vra=_VRA(),
    )


def _result():
    return SimpleNamespace(
        geometry=LineString([(0, 0), (1, 1)]),
        swath_count=7,
        total_distance_m=1444.5,
        metrics={
            "worked_distance_m": 1234.5,
            "non_working_distance_m": 210.0,
            "field_efficiency": 0.83,
            "covered_area_ha": 4.2,
        },
    )


def test_build_operation_entity_has_metrics_config_and_flag():
    e = store.build_operation_entity(
        op_id="urn:ngsi-ld:AgriParcelOperation:tenant-a:opX",
        body=_body(), result=_result(), prescription_map=None, is_template=False,
    )
    assert e["type"] == "AgriParcelOperation"
    assert e["isTemplate"]["value"] is False
    assert e["fieldEfficiency"]["value"] == 0.83
    assert e["workedDistance"]["value"] == 1234.5
    assert e["nonWorkingDistance"]["value"] == 210.0
    assert e["coveredAreaHa"]["value"] == 4.2
    assert e["swathCount"]["value"] == 7
    assert e["generationConfig"]["value"]["heading_deg"] == 30.0
    assert e["generationConfig"]["value"]["turning_radius_m"] == 6.5
    assert e["vraConfig"]["value"]["source"] == "orion"
    assert e["vraConfig"]["value"]["zone_ids"] == ["urn:ngsi-ld:AgriManagementZone:z1"]
    assert e["hasAgriParcel"]["object"] == "urn:ngsi-ld:AgriParcel:p1"
    assert e["refTractor"]["object"] == "urn:ngsi-ld:ManufacturingMachine:t1"
    assert "refImplement" not in e
    assert e["location"]["value"]["type"] == "LineString"


def test_build_template_entity_roundtrips_to_legacy_dict():
    e = store.build_template_entity(
        op_id="urn:ngsi-ld:AgriParcelOperation:tenant-a:tplX",
        parcel_id="urn:ngsi-ld:AgriParcel:p1",
        name="Headland spray",
        pattern_type="boustrophedon",
        pattern_config={"width_m": 24, "heading_deg": 30},
        route_geojson='{"type":"LineString","coordinates":[[0,0],[1,1]]}',
        vra_prescription_map={"z1": 1.2},
        equipment_tractor_id="urn:ngsi-ld:ManufacturingMachine:t1",
        equipment_implement_id=None,
        source_operation_id="urn:ngsi-ld:AgriParcelOperation:tenant-a:op1",
    )
    assert e["isTemplate"]["value"] is True
    d = store.template_to_dict(e)
    assert d["name"] == "Headland spray"
    assert d["parcel_id"] == "urn:ngsi-ld:AgriParcel:p1"
    assert d["pattern_type"] == "boustrophedon"
    assert d["pattern_config"] == {"width_m": 24, "heading_deg": 30}
    assert json.loads(d["route_geojson"]) == {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
    assert d["vra_prescription_map"] == {"z1": 1.2}
    assert d["equipment_tractor_id"] == "urn:ngsi-ld:ManufacturingMachine:t1"
    assert d["equipment_implement_id"] is None
    assert d["source_operation_id"] == "urn:ngsi-ld:AgriParcelOperation:tenant-a:op1"


# ---------------------------------------------------------------------------
# Task 3: async store readers
# ---------------------------------------------------------------------------
import pytest


class _FakeOrion:
    def __init__(self, entities=None, one=None):
        self._entities = entities or []
        self._one = one
        self.closed = False

    async def query_entities(self, entity_type, tenant_id, **kw):
        assert entity_type == "AgriParcelOperation"
        return list(self._entities)

    async def get_entity(self, entity_id, tenant_id):
        return self._one

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_list_operations_excludes_templates_and_filters_parcel():
    ents = [
        _op_entity(id="op-a"),  # parcel p1, not template
        _op_entity(id="tpl", isTemplate={"type": "Property", "value": True}),  # template -> excluded
        _op_entity(id="op-b", hasAgriParcel={"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:OTHER"}),
    ]
    orion = _FakeOrion(entities=ents)
    rows = await store.list_operations(orion, "tenant-a", parcel_id="urn:ngsi-ld:AgriParcel:p1")
    ids = [r["id"] for r in rows]
    assert ids == ["op-a"]
    assert all("route" not in r for r in rows)


@pytest.mark.asyncio
async def test_list_templates_only_templates_for_parcel():
    ents = [
        _op_entity(id="op-a"),
        store.build_template_entity(
            op_id="tpl-1", parcel_id="urn:ngsi-ld:AgriParcel:p1", name="T", pattern_type="boustrophedon",
            pattern_config={"width_m": 24}, route_geojson='{"type":"LineString","coordinates":[[0,0],[1,1]]}',
            vra_prescription_map=None, equipment_tractor_id=None, equipment_implement_id=None,
            source_operation_id=None,
        ),
    ]
    orion = _FakeOrion(entities=ents)
    out = await store.list_templates(orion, "tenant-a", parcel_id="urn:ngsi-ld:AgriParcel:p1")
    assert [t["id"] for t in out] == ["tpl-1"]
    assert out[0]["name"] == "T"


@pytest.mark.asyncio
async def test_get_operation_returns_detail_or_none():
    orion = _FakeOrion(one=_op_entity(id="op-a"))
    d = await store.get_operation(orion, "op-a", "tenant-a")
    assert d["route"]["type"] == "LineString"
    none_orion = _FakeOrion(one=None)
    assert await store.get_operation(none_orion, "missing", "tenant-a") is None


# ---------------------------------------------------------------------------
# Fix 1: template_to_dict created_at must be epoch-seconds int
# ---------------------------------------------------------------------------

def test_template_to_dict_created_at_is_epoch_int():
    e = store.build_template_entity(
        op_id="urn:ngsi-ld:AgriParcelOperation:t:tplEpoch",
        parcel_id="urn:ngsi-ld:AgriParcel:p1",
        name="EpochTest",
        pattern_type="boustrophedon",
        pattern_config={"width_m": 24},
        route_geojson='{"type":"LineString","coordinates":[[0,0],[1,1]]}',
        vra_prescription_map=None,
        equipment_tractor_id=None,
        equipment_implement_id=None,
        source_operation_id=None,
    )
    d = store.template_to_dict(e)
    assert isinstance(d["created_at"], int), "created_at must be an int (epoch seconds)"
    assert d["created_at"] > 1_700_000_000, "created_at must be a plausible recent epoch"


def test_iso_to_epoch_s_none_on_none():
    assert store._iso_to_epoch_s(None) is None


def test_iso_to_epoch_s_none_on_bad_string():
    assert store._iso_to_epoch_s("not-a-date") is None


def test_iso_to_epoch_s_known_value():
    # 2024-01-01T00:00:00Z => 1704067200
    result = store._iso_to_epoch_s({"@value": "2024-01-01T00:00:00Z"})
    assert result == 1704067200


# ---------------------------------------------------------------------------
# Fix 3: exact parcel match (_matches_parcel)
# ---------------------------------------------------------------------------

def test_matches_parcel_no_cross_match_suffix():
    """urn:...:p10 must NOT match filter urn:...:p1"""
    entity_p10 = _op_entity(
        id="op-p10",
        hasAgriParcel={"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:p10"},
    )
    # Use list_operations indirectly via _FakeOrion is async; test _matches_parcel directly.
    # We call the internal function via the module.
    result = store._matches_parcel(entity_p10, "urn:ngsi-ld:AgriParcel:p1")
    assert result is False, "p10 must not match filter for p1 (substring false positive)"


def test_matches_parcel_exact_match():
    entity_p1 = _op_entity(id="op-p1")  # hasAgriParcel is urn:...:p1
    assert store._matches_parcel(entity_p1, "urn:ngsi-ld:AgriParcel:p1") is True


def test_matches_parcel_none_filter():
    entity_p10 = _op_entity(
        id="op-p10",
        hasAgriParcel={"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:p10"},
    )
    assert store._matches_parcel(entity_p10, None) is True
