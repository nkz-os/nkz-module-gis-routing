"""Convert between shapely (UTM) geometry and Fields2Cover types.

All F2C work happens in UTM meters; this module is the only place that knows
F2C's geometry classes besides f2c_engine. Reprojection to WGS84 reuses the
transformers from routing.base.
"""
from __future__ import annotations

import numpy as np
import fields2cover as f2c
from shapely.geometry import LineString, MultiLineString, Polygon


def _ring_to_f2c(coords) -> "f2c.LinearRing":
    ring = f2c.LinearRing()
    for x, y in coords:
        ring.addPoint(f2c.Point(float(x), float(y)))
    return ring


def shapely_to_f2c_cells(utm_poly: Polygon) -> "f2c.Cells":
    """Build an f2c.Cells (single cell) from a UTM shapely Polygon, holes included."""
    if not utm_poly.is_valid:
        utm_poly = utm_poly.buffer(0)
    cell = f2c.Cell()
    cell.addRing(_ring_to_f2c(utm_poly.exterior.coords))
    for interior in utm_poly.interiors:
        cell.addRing(_ring_to_f2c(interior.coords))
    cells = f2c.Cells()
    cells.addGeometry(cell)
    return cells


def f2c_line_to_coords(line) -> list[tuple[float, float]]:
    """Read (x, y) vertices from an f2c LineString/Swath geometry."""
    coords: list[tuple[float, float]] = []
    n = line.size()
    for i in range(n):
        p = line.getGeometry(i)
        coords.append((p.getX(), p.getY()))
    return coords


def f2c_path_to_wgs84(utm_lines: list, to_wgs84) -> MultiLineString:
    """Project a list of F2C UTM line geometries back to a WGS84 MultiLineString."""
    wgs_lines = []
    for line in utm_lines:
        coords = f2c_line_to_coords(line)
        if len(coords) < 2:
            continue
        arr = np.array(coords)
        wx, wy = to_wgs84(arr[:, 0], arr[:, 1])
        wgs_lines.append(LineString(np.column_stack((wx, wy))))
    return MultiLineString(wgs_lines)
