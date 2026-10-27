import pytest
from shapely.geometry import Polygon
from app.api import routing


@pytest.mark.asyncio
async def test_load_constraints_wgs84_delegates_to_fetch(monkeypatch):
    zone = Polygon([(0.0008, 0.0008), (0.0012, 0.0008), (0.0012, 0.0012), (0.0008, 0.0012)])

    async def fake_fetch(parcel_id, tenant_id):
        return {"access_point": (0.001, 0.001), "zones": [zone]}
    monkeypatch.setattr(routing, "_fetch_parcel_constraints", fake_fetch)
    c = await routing._load_constraints_wgs84("urn:p1", "t1")
    assert c["access_point"] == (0.001, 0.001)
    assert c["zones"] == [zone]


@pytest.mark.asyncio
async def test_load_constraints_wgs84_empty_without_parcel():
    c = await routing._load_constraints_wgs84(None, "t1")
    assert c == {"access_point": None, "zones": []}
