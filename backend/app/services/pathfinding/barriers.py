"""Gated parcels as barriers for A-B routes.

A parcel with an access point (gate) is a fence: its boundary ring is blocked
except for an opening centred on the gate, so a route enters or leaves only
through it. A parcel without a gate is open ground and contributes nothing.
"""
from __future__ import annotations

import logging

import numpy as np
import shapely
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import transform

from app.services.routing.base import project_polygon_to_utm

logger = logging.getLogger(__name__)

_M_PER_DEG_LAT = 111320.0


def _parts(geom) -> list[Polygon]:
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return []


def _ring_wgs84(poly: Polygon, gate: tuple[float, float], width_m: float, cell_m: float):
    """Boundary ring of poly (WGS84) minus a gate opening, or None if empty."""
    utm_poly, _crs, to_utm, to_wgs84 = project_polygon_to_utm(poly)
    half = width_m / 2.0 + cell_m
    ring = utm_poly.exterior.buffer(half)
    gx, gy = to_utm(gate[0], gate[1])
    # Snap the gate onto the boundary: an access point slightly inside or outside
    # must still open the fence, never leave it sealed.
    on_edge = utm_poly.exterior.interpolate(utm_poly.exterior.project(Point(gx, gy)))
    ring = ring.difference(on_edge.buffer(max(width_m, 2.0 * cell_m)))
    if ring.is_empty:
        return None
    return transform(to_wgs84, ring)


def _rasterize(geom, raster: dict, cols: int, rows: int) -> set:
    cells: set = set()
    if geom is None or geom.is_empty:
        return cells
    o_lon, o_lat, px = raster["origin_lon"], raster["origin_lat"], raster["pixel_size_deg"]
    minx, miny, maxx, maxy = geom.bounds
    c0 = max(0, int((minx - o_lon) / px))
    c1 = min(cols - 1, int((maxx - o_lon) / px) + 1)
    r0 = max(0, int((miny - o_lat) / px))
    r1 = min(rows - 1, int((maxy - o_lat) / px) + 1)
    if c1 < c0 or r1 < r0:
        return cells
    cs, rs = np.meshgrid(np.arange(c0, c1 + 1), np.arange(r0, r1 + 1))
    inside = shapely.contains_xy(geom, o_lon + cs * px, o_lat + rs * px)
    return {(int(c), int(r)) for c, r in zip(cs[inside], rs[inside])}


def parcel_barrier_cells(parcels: list[dict], raster: dict, machine_width_m: float,
                         cols: int | None = None, rows: int | None = None) -> set:
    """Blocked (col, row) cells for the fences of the gated parcels.

    parcels: [{polygon (WGS84 shapely), access_point (lon, lat)|None, id?}].
    The ring is the boundary widened by machine_width/2 + one cell; the opening
    around the gate has radius max(machine_width, 2 cells).
    """
    if rows is None:
        rows = len(raster["elevations"])
    if cols is None:
        cols = len(raster["elevations"][0]) if rows else 0
    cell_m = raster["pixel_size_deg"] * _M_PER_DEG_LAT
    blocked: set = set()
    for parcel in parcels:
        gate = parcel.get("access_point")
        if not gate:
            continue
        for part in _parts(parcel["polygon"]):
            if part.is_empty:
                continue
            try:
                ring = _ring_wgs84(part, gate, machine_width_m, cell_m)
                blocked |= _rasterize(ring, raster, cols, rows)
            except Exception:
                # A fence we cannot build must not silently become open ground.
                logger.error("gated parcel barrier failed: id=%s", parcel.get("id"), exc_info=True)
                raise
    return blocked
