import pytest
from shapely.geometry import Polygon
from app.api import routing


@pytest.mark.asyncio
async def test_coverage_constraints_builds_kwargs(monkeypatch):
    async def fake_fetch(parcel_id, tenant_id):
        return {
            "access_point": (0.001, 0.001),
            "zones": [Polygon([(0.0008, 0.0008), (0.0012, 0.0008),
                               (0.0012, 0.0012), (0.0008, 0.0012)])],
        }
    monkeypatch.setattr(routing, "_fetch_parcel_constraints", fake_fetch)
    kwargs = await routing._coverage_constraints("urn:p1", "t1", cov_width=3.0)
    assert kwargs["start_point_wgs84"] == (0.001, 0.001)
    assert len(kwargs["exclusion_zones_wgs84"]) == 1
    assert kwargs["exclusion_buffer_m"] == pytest.approx(1.5)


@pytest.mark.asyncio
async def test_coverage_constraints_empty_without_parcel():
    kwargs = await routing._coverage_constraints(None, "t1", cov_width=3.0)
    assert kwargs == {}
