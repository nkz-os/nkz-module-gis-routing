"""Choose a working heading aligned with terrain contours (across-slope).

Fits a least-squares plane z = a*x + b*y + c, in metres, over the DEM cells
whose centres lie inside the parcel, and returns the heading perpendicular to
its gradient (i.e. along the contour). A plane is robust to the integer-metre
steps of national DEMs, where a few point samples are not. Below
FLAT_SLOPE_PCT there are no clear contours and no heading is returned; the
caller then lets the engine choose and reports why.
"""
from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np
import shapely

_M_PER_DEG_LAT = 111320.0
FLAT_SLOPE_PCT = 2.0
_MIN_CELLS = 3


class ContourHeading(NamedTuple):
    heading_deg: float | None   # azimuth, 0 = N, clockwise; None = let the engine choose
    slope_pct: float | None     # slope of the fitted plane
    warning: str | None         # CONTOUR_DEM_UNAVAILABLE | CONTOUR_TERRAIN_FLAT | None


UNAVAILABLE = ContourHeading(None, None, "CONTOUR_DEM_UNAVAILABLE")


def contour_heading(grid: dict, wgs84_poly) -> ContourHeading:
    """Contour heading of the parcel from a DemGrid (row 0 = south, None = no data)."""
    elevations = grid["elevations"]
    rows, cols = len(elevations), len(elevations[0]) if elevations else 0
    if not rows or not cols:
        return UNAVAILABLE
    px = grid["pixel_size_deg"]
    ph = grid.get("pixel_height_deg") or px
    z = np.array([[np.nan if v is None else v for v in row] for row in elevations], dtype=float)
    lons = grid["origin_lon"] + (np.arange(cols) + 0.5) * px
    lats = grid["origin_lat"] + (np.arange(rows) + 0.5) * ph
    lon_g, lat_g = np.meshgrid(lons, lats)
    use = shapely.contains_xy(wgs84_poly, lon_g, lat_g) & ~np.isnan(z)
    if int(use.sum()) < _MIN_CELLS:
        return UNAVAILABLE

    c = wgs84_poly.centroid
    x = (lon_g[use] - c.x) * _M_PER_DEG_LAT * math.cos(math.radians(c.y))
    y = (lat_g[use] - c.y) * _M_PER_DEG_LAT
    design = np.column_stack([x, y, np.ones_like(x)])
    (a, b, _c), *_ = np.linalg.lstsq(design, z[use], rcond=None)
    slope_pct = float(math.hypot(a, b) * 100.0)
    if slope_pct < FLAT_SLOPE_PCT:
        return ContourHeading(None, slope_pct, "CONTOUR_TERRAIN_FLAT")
    uphill_az = math.degrees(math.atan2(a, b)) % 360.0
    return ContourHeading((uphill_az + 90.0) % 360.0, slope_pct, None)
