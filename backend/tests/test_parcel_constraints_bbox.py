import pytest
from app.services import parcel_constraints as pc


@pytest.mark.asyncio
async def test_zones_of_parcels_in_bbox_only(monkeypatch):
    sq = lambda x0, y0, x1, y1: {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}
    entities = [
        {"id": "urn:ngsi-ld:AgriParcel:in", "location": {"value": sq(0, 0, 0.01, 0.01)},
         "exclusionZones": {"value": {"type": "FeatureCollection", "features": [{"geometry": sq(0.001, 0.001, 0.002, 0.002)}]}}},
        {"id": "urn:ngsi-ld:AgriParcel:out", "location": {"value": sq(1, 1, 1.01, 1.01)},
         "exclusionZones": {"value": {"type": "FeatureCollection", "features": [{"geometry": sq(1.001, 1.001, 1.002, 1.002)}]}}},
        {"id": "urn:ngsi-ld:AgriParcel:nozones", "location": {"value": sq(0, 0, 0.01, 0.01)}},
    ]

    class FakeOrion:
        def __init__(self, *a, **k): ...
        async def query_entities(self, *a, **k): return entities
        async def close(self): ...

    monkeypatch.setattr(pc, "OrionClient", FakeOrion)
    zones = await pc.fetch_tenant_zones_in_bbox("tenant-a", (-0.005, -0.005, 0.005, 0.005))
    assert len(zones) == 1 and zones[0].bounds == (0.001, 0.001, 0.002, 0.002)


def _sq(x0, y0, x1, y1):
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def _fc(*geoms):
    return {"value": {"type": "FeatureCollection", "features": [{"geometry": g} for g in geoms]}}


def _fake(entities_for):
    class FakeOrion:
        calls: list = []

        def __init__(self, *a, **k): ...
        async def query_entities(self, *a, **k):
            FakeOrion.calls.append(k)
            return entities_for(k)
        async def close(self): ...
    return FakeOrion


@pytest.mark.asyncio
async def test_paginates_beyond_first_page(monkeypatch):
    filler = {"id": "f", "location": {"value": _sq(5, 5, 6, 6)}}
    last = {"id": "last", "location": {"value": _sq(0, 0, 0.01, 0.01)},
            "exclusionZones": _fc(_sq(0.001, 0.001, 0.002, 0.002))}
    fake = _fake(lambda k: [filler] * 500 if k["offset"] == 0 else [last] * 3)
    monkeypatch.setattr(pc, "OrionClient", fake)
    zones = await pc.fetch_tenant_zones_in_bbox("tenant-a", (-0.005, -0.005, 0.005, 0.005))
    assert [c["offset"] for c in fake.calls] == [0, 500]
    assert len(zones) == 3


@pytest.mark.asyncio
async def test_malformed_location_still_includes_zones(monkeypatch):
    ent = {"id": "bad-loc", "location": {"value": {"type": "Polygon", "coordinates": "x"}},
           "exclusionZones": _fc(_sq(0.001, 0.001, 0.002, 0.002))}
    monkeypatch.setattr(pc, "OrionClient", _fake(lambda k: [ent]))
    zones = await pc.fetch_tenant_zones_in_bbox("tenant-a", (-0.005, -0.005, 0.005, 0.005))
    assert len(zones) == 1


@pytest.mark.asyncio
async def test_malformed_zone_raises_with_entity_id(monkeypatch):
    ent = {"id": "bad-zone", "location": {"value": _sq(0, 0, 0.01, 0.01)},
           "exclusionZones": _fc({"type": "Polygon", "coordinates": "x"})}
    monkeypatch.setattr(pc, "OrionClient", _fake(lambda k: [ent]))
    with pytest.raises(ValueError, match="bad-zone"):
        await pc.fetch_tenant_zones_in_bbox("tenant-a", (-0.005, -0.005, 0.005, 0.005))


def test_zone_polygons_splits_multipolygon():
    mp = {"type": "MultiPolygon", "coordinates": [_sq(0, 0, 1, 1)["coordinates"], _sq(2, 2, 3, 3)["coordinates"]]}
    assert len(pc._zone_polygons(_fc(mp)["value"])) == 2


# ---- final fix C2 + minors: invalid / malformed zones ----
BOWTIE = {"type": "Polygon", "coordinates": [[[0, 0], [20, 10], [20, 0], [0, 10], [0, 0]]]}


def test_bowtie_zone_keeps_both_lobes_and_logs_entity(caplog):
    import logging
    from shapely.geometry import Point
    with caplog.at_level(logging.WARNING, logger="app.services.parcel_constraints"):
        polys = pc._zone_polygons(_fc(BOWTIE)["value"], entity_id="urn:ngsi-ld:AgriParcel:p1")
    assert len(polys) == 2 and all(p.is_valid for p in polys)
    assert sum(p.area for p in polys) == pytest.approx(100.0)
    assert any(p.covers(Point(2, 5)) for p in polys) and any(p.covers(Point(18, 5)) for p in polys)
    assert "urn:ngsi-ld:AgriParcel:p1" in caplog.text


@pytest.mark.parametrize("value", [
    {"type": "Feature", "geometry": _sq(0, 0, 1, 1)},
    [{"geometry": _sq(0, 0, 1, 1)}],
    {"type": "FeatureCollection"},
    {"type": "FeatureCollection", "features": [{"properties": {}}]},
    {"type": "FeatureCollection", "features": [{"geometry": None}]},
])
def test_malformed_zone_config_raises_naming_entity(value):
    with pytest.raises(ValueError, match="urn:ngsi-ld:AgriParcel:p1"):
        pc._zone_polygons(value, entity_id="urn:ngsi-ld:AgriParcel:p1")


def test_empty_zone_config_is_no_zones():
    assert pc._zone_polygons({}, entity_id="x") == []
    assert pc._zone_polygons(None, entity_id="x") == []
