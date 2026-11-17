"""Contour heading is resolved before the engine and its fallbacks are reported."""
import math

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_POLY = {
    "type": "Polygon",
    "coordinates": [[[-2.0, 43.0], [-1.99754, 43.0],
                     [-1.99754, 43.0009], [-2.0, 43.0009], [-2.0, 43.0]]],
}


def _grid(gx):
    """Plane rising east by gx m/m over the parcel, 0.0001 deg cells."""
    lon0, lat0, px = -2.0005, 42.9995, 0.0001
    cols, rows = 36, 20
    m_lon = 111320.0 * math.cos(math.radians(lat0))
    el = [[100.0 + gx * (c + 0.5) * px * m_lon for c in range(cols)] for _ in range(rows)]
    return {"elevations": el, "origin_lon": lon0, "origin_lat": lat0, "pixel_size_deg": px,
            "pixel_height_deg": px, "cols": cols, "rows": rows, "source": {}}


@pytest.fixture
def registry(monkeypatch):
    from app.api import routing as r
    state = {"grid": None, "calls": 0}

    class _Reg:
        async def fetch_best(self, bbox, resolution_m):
            state["calls"] += 1
            return state["grid"]

    monkeypatch.setattr(r, "build_dem_registry", lambda: _Reg())
    return state


@pytest.fixture
def engine_cfg(monkeypatch):
    from app.api import routing as r
    seen = {}
    real = r.run_ladder_isolated

    async def spy(inp, **kw):
        seen["cfg"] = inp.cfg
        return await real(inp, **kw)

    monkeypatch.setattr(r, "run_ladder_isolated", spy)
    return seen


def _generate(**pc):
    cfg = {"width_m": 20, "headland_passes": 1, "turning_radius_m": 6.0,
           "heading_objective": "contour", **pc}
    resp = client.post("/api/routing/generate", json={
        "parcel_geometry": _POLY, "pattern": "boustrophedon", "pattern_config": cfg, "persist": False})
    assert resp.status_code == 200, resp.text
    return resp.json()["plan"]


def _codes(plan):
    return [w["code"] for w in ((plan.get("validation") or {}).get("warnings") or [])]


def test_generate_contour_sets_heading(registry, engine_cfg):
    registry["grid"] = _grid(0.05)
    plan = _generate()
    h = engine_cfg["cfg"].heading_deg
    assert h is not None and min(h % 180, 180 - h % 180) < 1.0
    assert not {"CONTOUR_DEM_UNAVAILABLE", "CONTOUR_TERRAIN_FLAT"} & set(_codes(plan))


def test_generate_contour_without_dem_warns(registry, engine_cfg):
    plan = _generate()
    assert engine_cfg["cfg"].heading_deg is None
    assert "CONTOUR_DEM_UNAVAILABLE" in _codes(plan)


def test_generate_contour_flat_warns(registry, engine_cfg):
    registry["grid"] = _grid(0.005)
    plan = _generate()
    assert engine_cfg["cfg"].heading_deg is None
    assert "CONTOUR_TERRAIN_FLAT" in _codes(plan)


def test_explicit_heading_skips_dem(registry, engine_cfg):
    plan = _generate(heading_deg=30.0)
    assert registry["calls"] == 0
    assert engine_cfg["cfg"].heading_deg == 30.0
    assert "CONTOUR_DEM_UNAVAILABLE" not in _codes(plan)


def test_contour_bbox_is_padded(registry, engine_cfg, monkeypatch):
    from app.api import routing as r
    seen = {}

    class _Reg:
        async def fetch_best(self, bbox, resolution_m):
            seen["bbox"] = bbox
            return None

    monkeypatch.setattr(r, "build_dem_registry", lambda: _Reg())
    _generate()
    min_lon, min_lat, max_lon, max_lat = seen["bbox"]
    pad_lat_m = (43.0 - min_lat) * 111320.0
    pad_lon_m = (-2.0 - min_lon) * 111320.0 * math.cos(math.radians(43.0))
    assert pad_lat_m >= 30.0 - 1e-6 and pad_lon_m >= 30.0 - 1e-6
    assert (max_lat - 43.0009) * 111320.0 >= 30.0 - 1e-6
