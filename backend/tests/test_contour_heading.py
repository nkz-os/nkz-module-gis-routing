"""Contour heading from a least-squares terrain plane in metres. Synthetic grids only."""
import math

import pytest
from shapely.geometry import box

from app.services.coverage.contour import FLAT_SLOPE_PCT, ContourHeading, contour_heading

_M = 111320.0


def _plane_grid(lat0, gx, gy, cols=20, rows=20, px=0.0002, ph=0.00015, none_at=()):
    """z = 100 + gx * east_m + gy * north_m, cell centres, row 0 = south."""
    lon0 = -2.0
    m_lon = _M * math.cos(math.radians(lat0))
    el = []
    for r in range(rows):
        row = []
        for c in range(cols):
            x = (c + 0.5) * px * m_lon
            y = (r + 0.5) * ph * _M
            row.append(None if (r, c) in none_at else 100.0 + gx * x + gy * y)
        el.append(row)
    grid = {"elevations": el, "origin_lon": lon0, "origin_lat": lat0, "pixel_size_deg": px,
            "pixel_height_deg": ph, "cols": cols, "rows": rows, "source": {}}
    poly = box(lon0, lat0, lon0 + cols * px, lat0 + rows * ph)
    return grid, poly


def _axis_err(heading, target):
    d = (heading - target) % 180
    return min(d, 180 - d)


def test_east_rising_plane_gives_north_south_heading():
    grid, poly = _plane_grid(42.6, gx=0.05, gy=0.0)
    ch = contour_heading(grid, poly)
    assert isinstance(ch, ContourHeading) and ch.warning is None
    assert _axis_err(ch.heading_deg, 0.0) < 1.0
    assert ch.slope_pct == pytest.approx(5.0, abs=0.01)


def test_latitude_scaling():
    # True 45 deg gradient in metres at 60 N: uphill NE, contour NW-SE (135 deg).
    grid, poly = _plane_grid(60.0, gx=0.05, gy=0.05)
    ch = contour_heading(grid, poly)
    assert ch.heading_deg == pytest.approx(135.0, abs=0.5)


def test_flat_parcel_warns():
    grid, poly = _plane_grid(42.6, gx=0.01, gy=0.0)
    ch = contour_heading(grid, poly)
    assert FLAT_SLOPE_PCT == 2.0
    assert ch.heading_deg is None and ch.warning == "CONTOUR_TERRAIN_FLAT"
    assert ch.slope_pct == pytest.approx(1.0, abs=0.01)


def test_too_few_cells_unavailable():
    grid, _ = _plane_grid(42.6, gx=0.05, gy=0.0)
    tiny = box(-2.0, 42.6, -2.0 + 0.0003, 42.6 + 0.0002)  # one cell centre inside
    ch = contour_heading(grid, tiny)
    assert ch == ContourHeading(None, None, "CONTOUR_DEM_UNAVAILABLE")


def test_none_cells_ignored():
    holes = {(r, c) for r in range(0, 20, 2) for c in range(0, 20, 3)}
    grid, poly = _plane_grid(42.6, gx=0.0, gy=0.08, none_at=holes)
    ch = contour_heading(grid, poly)
    assert ch.warning is None and _axis_err(ch.heading_deg, 90.0) < 1.0


def test_only_cells_inside_the_parcel_count():
    grid, _ = _plane_grid(42.6, gx=0.05, gy=0.0)
    # Raise the cells outside the west half: a whole-grid fit would tilt the plane.
    for row in grid["elevations"]:
        for c in range(10, 20):
            row[c] += 500.0 * (c - 9)
    west = box(-2.0, 42.6, -2.0 + 10 * 0.0002, 42.6 + 20 * 0.00015)
    ch = contour_heading(grid, west)
    assert ch.slope_pct == pytest.approx(5.0, abs=0.05)


def test_single_row_parcel_is_unavailable():
    # Every cell centre inside the strip lies in one row: north-south slope is undetermined.
    grid, _ = _plane_grid(42.6, gx=0.0, gy=0.0)
    strip = box(-2.0, 42.6 + 3 * 0.00015, -2.0 + 20 * 0.0002, 42.6 + 4 * 0.00015)
    ch = contour_heading(grid, strip)
    assert ch == ContourHeading(None, None, "CONTOUR_DEM_UNAVAILABLE")


def test_high_elevation_does_not_leak_into_slope():
    # Flat plane at 500 m over a full 2-D parcel stays flat.
    grid, poly = _plane_grid(42.6, gx=0.0, gy=0.0)
    for row in grid["elevations"]:
        for c in range(len(row)):
            row[c] += 400.0
    ch = contour_heading(grid, poly)
    assert ch.warning == "CONTOUR_TERRAIN_FLAT" and ch.slope_pct == pytest.approx(0.0, abs=1e-6)
