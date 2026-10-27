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
