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


@pytest.mark.asyncio
async def test_eu_provider_covers_in_bounds_and_delegates_fetch(monkeypatch):
    from app.services.pathfinding import dem_provider as dp

    captured = {}

    async def fake_fetch(url, bbox, resolution_m):
        captured["url"] = url
        captured["res"] = resolution_m
        return _GRID

    monkeypatch.setattr(dp, "fetch_dem_raster", fake_fetch)
    prov = dp.EuElevationProvider(dem_url="http://eu-elev:8000")
    assert prov.priority == 10
    assert prov.covers((-1.0, 42.0, -0.99, 42.01)) is True
    assert prov.covers((-100.0, 42.0, -99.0, 43.0)) is False
    grid = await prov.fetch((-1.0, 42.0, -0.99, 42.01), 30)
    assert grid is _GRID
    assert captured["url"] == "http://eu-elev:8000"
    assert captured["res"] == 30


def _src_grid(res):
    return {**_GRID, "pixel_height_deg": 0.001, "source": {"resolution_m": res}}


async def _provider_with(monkeypatch, responses):
    from app.services.pathfinding import dem_provider as dp
    calls = []

    async def fake_fetch(url, bbox, resolution_m):
        calls.append(resolution_m)
        return responses[len(calls) - 1]

    monkeypatch.setattr(dp, "fetch_dem_raster", fake_fetch)
    return dp.EuElevationProvider(dem_url="http://eu-elev:8000"), calls


async def test_coarse_source_triggers_native_refetch(monkeypatch):
    from app.services.pathfinding import dem_provider as dp
    first, native = _src_grid(25.0), {**_src_grid(25.0), "origin_lon": -9.0}
    seen = {}
    monkeypatch.setattr(dp, "resample_bilinear", lambda n, t: seen.update(n=n, t=t) or "resampled")
    prov, calls = await _provider_with(monkeypatch, [first, native])
    assert await prov.fetch((-1.0, 42.0, -0.99, 42.01), 10) == "resampled"
    assert calls == [10, 25.0]
    assert seen["n"] is native and seen["t"] is first


async def test_fine_source_no_refetch(monkeypatch):
    first = _src_grid(10.0)
    prov, calls = await _provider_with(monkeypatch, [first])
    assert await prov.fetch((-1.0, 42.0, -0.99, 42.01), 10) is first
    assert calls == [10]


async def test_threshold_is_one_and_a_half_times(monkeypatch):
    first = _src_grid(15.0)
    prov, calls = await _provider_with(monkeypatch, [first])
    assert await prov.fetch((-1.0, 42.0, -0.99, 42.01), 10) is first
    assert calls == [10]


async def test_native_refetch_failure_returns_none(monkeypatch):
    prov, calls = await _provider_with(monkeypatch, [_src_grid(25.0), None])
    assert await prov.fetch((-1.0, 42.0, -0.99, 42.01), 10) is None
    assert calls == [10, 25.0]


async def test_missing_source_resolution_is_logged(monkeypatch, caplog):
    import logging
    first = {**_GRID, "pixel_height_deg": 0.001, "source": {}}
    prov, calls = await _provider_with(monkeypatch, [first])
    with caplog.at_level(logging.WARNING):
        assert await prov.fetch((-1.0, 42.0, -0.99, 42.01), 10) is first
    assert "resolution" in caplog.text and calls == [10]
