import pytest
from app.services.pathfinding.dem_provider import DemRegistry

_GRID = {"elevations": [[0.0, 1.0], [2.0, 3.0]], "origin_lon": -1.0,
         "origin_lat": 42.0, "pixel_size_deg": 0.001, "cols": 2, "rows": 2}


class _Fake:
    def __init__(self, name, priority, covers, grid):
        self.name = name
        self.priority = priority
        self._covers = covers
        self._grid = grid

    def covers(self, bbox):
        return self._covers

    async def fetch(self, bbox, resolution_m):
        return self._grid


@pytest.mark.asyncio
async def test_registry_prefers_highest_priority_that_covers():
    low = _Fake("eu", 10, True, _GRID)
    high = _Fake("lidar", 100, True, {**_GRID, "origin_lon": -2.0})
    reg = DemRegistry([low, high])
    grid = await reg.fetch_best((-1.0, 42.0, -0.99, 42.01), 10)
    assert grid["origin_lon"] == -2.0  # high-priority provider won


@pytest.mark.asyncio
async def test_registry_skips_provider_that_does_not_cover():
    high = _Fake("lidar", 100, False, _GRID)
    low = _Fake("eu", 10, True, _GRID)
    reg = DemRegistry([low, high])  # non-priority order — exercises internal sort
    grid = await reg.fetch_best((0, 0, 1, 1), 10)
    assert grid is _GRID  # fell back to eu


@pytest.mark.asyncio
async def test_registry_returns_none_when_nothing_covers():
    reg = DemRegistry([_Fake("eu", 10, False, _GRID)])
    assert await reg.fetch_best((0, 0, 1, 1), 10) is None


@pytest.mark.asyncio
async def test_registry_falls_back_when_covering_provider_returns_none():
    class _NoneFetch:
        name = "lidar"
        priority = 100
        def covers(self, bbox): return True
        async def fetch(self, bbox, resolution_m): return None
    low = _Fake("eu", 10, True, _GRID)
    reg = DemRegistry([_NoneFetch(), low])
    grid = await reg.fetch_best((0, 0, 1, 1), 10)
    assert grid is _GRID
