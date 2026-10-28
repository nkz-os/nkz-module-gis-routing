import pytest


def _pz(zones):
    return {"id": "urn:p", "name": "", "polygon": None, "geometry": None, "access_point": None, "zones": zones}
from shapely.geometry import Polygon
from app.api import pathfinding_router as pr


@pytest.mark.asyncio
async def test_resolve_constraints_builds_blocked_and_default_origin(monkeypatch):
    async def fake_fetch(parcel_id, tenant_id):
        return {
            "access_point": (0.0, 0.0),
            "zones": [Polygon([(0.001, 0.001), (0.003, 0.001),
                               (0.003, 0.003), (0.001, 0.003)])],
        }
    monkeypatch.setattr(pr, "_fetch_parcel_constraints", fake_fetch)
    raster = {"origin_lon": 0.0, "origin_lat": 0.0, "pixel_size_deg": 0.001}
    default_origin, blocked, _fences = await pr._resolve_path_constraints(
        parcel_id="urn:p1", tenant_id="t1", raster=raster, cols=10, rows=10,
        machine_width_m=2.0, bbox=(0, 0, 0.01, 0.01))
    assert default_origin == (0.0, 0.0)
    assert blocked
    assert (0, 0) not in blocked


@pytest.mark.asyncio
async def test_resolve_constraints_empty_without_parcel(monkeypatch):
    default_origin, blocked, _fences = await pr._resolve_path_constraints(
        None, "t1", {"origin_lon": 0.0, "origin_lat": 0.0, "pixel_size_deg": 0.001},
        10, 10, 2.0, (0, 0, 0.01, 0.01))
    assert default_origin is None and blocked == set()


@pytest.mark.asyncio
async def test_bowtie_zone_blocks_cells_of_both_lobes(monkeypatch):
    from app.services import parcel_constraints as pcs
    bowtie = {"type": "Polygon", "coordinates": [[[0.002, 0.002], [0.008, 0.006], [0.008, 0.002],
                                                  [0.002, 0.006], [0.002, 0.002]]]}

    class FakeOrion:
        def __init__(self, *a, **k): ...
        async def get_entity(self, eid):
            return {"id": eid, "exclusionZones": {"value": {
                "type": "FeatureCollection", "features": [{"type": "Feature", "geometry": bowtie}]}}}
        async def query_entities(self, *a, **k):
            return []
        async def close(self): ...

    monkeypatch.setattr(pcs, "OrionClient", FakeOrion)
    raster = {"origin_lon": 0.0, "origin_lat": 0.0, "pixel_size_deg": 0.001}
    _origin, blocked, _fences = await pr._resolve_path_constraints(
        parcel_id="urn:ngsi-ld:AgriParcel:p1", tenant_id="tenant-a", raster=raster, cols=10, rows=10,
        machine_width_m=2.0, bbox=(0, 0, 0.01, 0.01))
    assert (3, 4) in blocked and (7, 4) in blocked


@pytest.mark.asyncio
async def test_parcel_and_neighbouring_tenant_zones_both_block(monkeypatch):
    own = Polygon([(0.001, 0.001), (0.002, 0.001), (0.002, 0.002), (0.001, 0.002)])
    neighbour = Polygon([(0.006, 0.006), (0.008, 0.006), (0.008, 0.008), (0.006, 0.008)])
    seen = {}

    async def fake_fetch(parcel_id, tenant_id):
        return {"access_point": (0.0, 0.0), "zones": [own]}

    async def fake_tenant(tenant_id, bbox):
        seen["bbox"], seen["tenant"] = bbox, tenant_id
        return [_pz([neighbour])]

    monkeypatch.setattr(pr, "_fetch_parcel_constraints", fake_fetch)
    monkeypatch.setattr(pr, "fetch_tenant_parcels_in_bbox", fake_tenant)
    raster = {"origin_lon": 0.0, "origin_lat": 0.0, "pixel_size_deg": 0.001}
    origin, blocked, _fences = await pr._resolve_path_constraints(
        parcel_id="urn:ngsi-ld:AgriParcel:p1", tenant_id="tenant-a", raster=raster, cols=10, rows=10,
        machine_width_m=2.0, bbox=(0, 0, 0.01, 0.01))
    assert origin == (0.0, 0.0)
    assert seen == {"bbox": (0, 0, 0.01, 0.01), "tenant": "tenant-a"}
    assert (2, 2) in blocked or (1, 1) in blocked          # own parcel zone
    assert (7, 7) in blocked                                # neighbouring parcel zone
