"""Gated parcels as barriers for A-B routes.

A parcel with an access point (gate) is a fence: a band just INSIDE its boundary
is blocked except for an opening centred on the gate, so a route enters or leaves
only through it. Nothing outside the parcel is ever blocked (farm tracks between
parcels stay open). A parcel without a gate is open ground and contributes nothing.
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
_EDGE_TOL_M = 0.05  # centimetres: far below any cell, only absorbs round-off


def band_thickness_m(width_m: float, cell_m: float) -> float:
    """Thickness of the fence band, measured inwards from the boundary."""
    return max(2.0 * cell_m, width_m / 2.0 + cell_m)


def _parts(geom) -> list[Polygon]:
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return []


def _ring_wgs84(poly: Polygon, gate: tuple[float, float] | None, width_m: float, cell_m: float):
    """Inner boundary band of poly (WGS84) minus a gate opening (none when gate is None), or None if empty."""
    utm_poly, _crs, to_utm, to_wgs84 = project_polygon_to_utm(poly)
    half = band_thickness_m(width_m, cell_m)
    # Strictly inside the parcel, at least 2 cells thick (no 8-connected or diagonal leak).
    # _EDGE_TOL_M keeps a cell centred exactly on the boundary (float round-off) in the fence.
    ring = utm_poly.buffer(_EDGE_TOL_M).difference(utm_poly.buffer(-half))
    if gate is not None:
        gx, gy = to_utm(gate[0], gate[1])
        # Snap the gate onto the boundary: an access point slightly inside or outside
        # must still open the fence, never leave it sealed.
        on_edge = utm_poly.exterior.interpolate(utm_poly.exterior.project(Point(gx, gy)))
        # The disc must reach past the band's half-thickness, or a corridor of the
        # machine's width is left closed (seen at width == 2 cells).
        ring = ring.difference(on_edge.buffer(half + max(width_m, 2.0 * cell_m) / 2.0))
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
    inside = shapely.intersects_xy(geom, o_lon + cs * px, o_lat + rs * px)
    return {(int(c), int(r)) for c, r in zip(cs[inside], rs[inside])}


def parcel_barrier_map(parcels: list[dict], raster: dict, machine_width_m: float,
                       cols: int | None = None, rows: int | None = None) -> dict:
    """Blocked (col, row) cells of each gated parcel's fence, keyed by parcel id.

    parcels: [{id, polygon (WGS84 shapely)|None, access_point (lon, lat)|None}].
    The band lies inside the boundary, max(2 cells, machine_width/2 + 1 cell) thick; the opening
    around the gate has radius max(machine_width, 2 cells). Ungated parcels (and
    parcels without a readable polygon) have no fence.
    """
    if rows is None:
        rows = len(raster["elevations"])
    if cols is None:
        cols = len(raster["elevations"][0]) if rows else 0
    cell_m = raster["pixel_size_deg"] * _M_PER_DEG_LAT
    fences: dict = {}
    for n, parcel in enumerate(parcels):
        gate = parcel.get("access_point")
        if not gate or parcel.get("polygon") is None:
            continue
        cells: set = set()
        parts = [p for p in _parts(parcel["polygon"]) if not p.is_empty]
        # Only the part the gate belongs to (the nearest) is opened; the others stay sealed.
        gate_pt = Point(gate)
        gated = min(parts, key=lambda p: p.exterior.distance(gate_pt), default=None)
        for part in parts:
            try:
                ring = _ring_wgs84(part, gate if part is gated else None, machine_width_m, cell_m)
                cells |= _rasterize(ring, raster, cols, rows)
            except Exception:
                # A fence we cannot build must not silently become open ground.
                logger.error("gated parcel barrier failed: id=%s", parcel.get("id"), exc_info=True)
                raise
        fences[parcel.get("id") or f"#{n}"] = cells
    return fences


def parcel_barrier_cells(parcels: list[dict], raster: dict, machine_width_m: float,
                         cols: int | None = None, rows: int | None = None) -> set:
    """Union of the fences of parcel_barrier_map."""
    out: set = set()
    for cells in parcel_barrier_map(parcels, raster, machine_width_m, cols, rows).values():
        out |= cells
    return out
