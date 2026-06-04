import pytest
from app.services.pathfinding.grid_sampler import make_grid_sampler

_GRID = {"elevations": [[0.0, 10.0], [0.0, 10.0]], "origin_lon": -1.0,
         "origin_lat": 42.0, "pixel_size_deg": 0.01, "cols": 2, "rows": 2}


def test_sampler_returns_nearest_cell_elevation():
    s = make_grid_sampler(_GRID)
    assert s(-1.0, 42.0) == 0.0     # SW cell
    assert s(-0.99, 42.0) == 10.0   # one cell east -> higher
    # Out-of-grid clamps to nearest edge, never raises.
    assert s(-5.0, 0.0) == 0.0


@pytest.mark.asyncio
async def test_generate_resolves_contour_dem(monkeypatch):
    from app.api import routing as r

    class _Reg:
        async def fetch_best(self, bbox, resolution_m):
            return _GRID

    monkeypatch.setattr(r, "build_dem_registry", lambda: _Reg())
    poly = {"type": "Polygon", "coordinates": [[[-1.0, 42.0], [-0.99, 42.0],
            [-0.99, 42.01], [-1.0, 42.01], [-1.0, 42.0]]]}
    sampler, bbox = await r._resolve_contour_dem(poly)
    assert callable(sampler)
    assert bbox == pytest.approx((-1.0, 42.0, -0.99, 42.01))
    assert sampler(-0.99, 42.0) == 10.0
