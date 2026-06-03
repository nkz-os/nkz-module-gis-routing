import pytest
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
    default_origin, blocked = await pr._resolve_path_constraints(
        parcel_id="urn:p1", tenant_id="t1", raster=raster, cols=10, rows=10,
        machine_width_m=2.0)
    assert default_origin == (0.0, 0.0)
    assert blocked
    assert (0, 0) not in blocked


@pytest.mark.asyncio
async def test_resolve_constraints_empty_without_parcel():
    default_origin, blocked = await pr._resolve_path_constraints(
        None, "t1", {"origin_lon": 0.0, "origin_lat": 0.0, "pixel_size_deg": 0.001},
        10, 10, 2.0)
    assert default_origin is None and blocked == set()
