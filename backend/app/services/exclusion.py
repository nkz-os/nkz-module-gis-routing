"""Pure geometry for access-point and no-go-zone constraints.

Operates on shapely geometries in a single metric CRS (UTM metres) — callers
project WGS84 -> UTM with app.services.routing.base helpers before calling.
No Orion / IO here so it is exhaustively unit-testable on planar coordinates.
"""
from __future__ import annotations

from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


class ExclusionError(ValueError):
    """Raised when constraints make a parcel unroutable (fail-safe)."""


def buffered_zones(zones: list[Polygon], buffer_m: float) -> "BaseGeometry | None":
    """Union of the no-go polygons, each grown by buffer_m metres. None if empty."""
    if not zones:
        return None
    grown = [z.buffer(max(buffer_m, 0.0)) for z in zones if not z.is_empty]
    if not grown:
        return None
    return unary_union(grown)


def route_enters_zones(route: BaseGeometry, zones: list[Polygon]) -> bool:
    """True if the route geometry intersects the (raw, unbuffered) no-go zones.

    Working swaths are clipped to the buffered working polygon, so they stay
    >= buffer_m away from the raw zones and never intersect them. Only a
    connecting/turn segment that actually crosses a zone trips this check —
    which is the fail-safe gate: such a route must never be emitted.
    """
    if not zones or route.is_empty:
        return False
    block = unary_union(zones)
    return route.intersects(block)


def build_working_polygon(parcel: Polygon, zones: list[Polygon], buffer_m: float) -> "BaseGeometry":
    """Parcel minus the buffered no-go zones. Raises if nothing drivable remains."""
    block = buffered_zones(zones, buffer_m)
    work = parcel if block is None else parcel.difference(block)
    if work.is_empty or work.area <= 0.0:  # area<=0 also catches degenerate line/point remainders
        raise ExclusionError("No drivable area remains after applying no-go zones")
    return work


def validate_access_point(point: Point, parcel: Polygon, zones: list[Polygon],
                          buffer_m: float) -> None:
    """Fail-safe checks for the access point. Raises ExclusionError on violation."""
    if not parcel.covers(point):
        raise ExclusionError("Access point is outside the parcel")
    block = buffered_zones(zones, buffer_m)
    if block is not None and block.contains(point):
        raise ExclusionError("Access point falls inside a no-go zone")


def rasterize_blocked_cells(block: "BaseGeometry | None", origin_lon: float,
                            origin_lat: float, pixel_size_deg: float,
                            cols: int, rows: int) -> set:
    """Return {(col, row)} whose cell centre falls inside `block`.

    `block` is a shapely geometry already in the grid's coordinate space.
    Uses a bounding-box window to avoid scanning the full grid.
    Returns an empty set if block is None or empty.
    """
    blocked: set = set()
    if block is None or block.is_empty:
        return blocked
    minx, miny, maxx, maxy = block.bounds
    c0 = max(0, int((minx - origin_lon) / pixel_size_deg))
    c1 = min(cols - 1, int((maxx - origin_lon) / pixel_size_deg) + 1)
    r0 = max(0, int((miny - origin_lat) / pixel_size_deg))
    r1 = min(rows - 1, int((maxy - origin_lat) / pixel_size_deg) + 1)
    for r in range(r0, r1 + 1):
        lat = origin_lat + r * pixel_size_deg
        for c in range(c0, c1 + 1):
            lon = origin_lon + c * pixel_size_deg
            if block.contains(Point(lon, lat)):
                blocked.add((c, r))
    return blocked
