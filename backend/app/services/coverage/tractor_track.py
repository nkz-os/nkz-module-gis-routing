"""Where the tractor drives when the implement works off to one side (side mowers).

The plan's passes are the implement's working centre lines, so the work is even. With a
lateral offset e (> 0: implement to the right of the travel) the tractor runs |e| to the
other side of each pass. That track must stay inside the parcel and out of the no-go
zones; when it does not, the plan reports it (nothing is moved or invented).
"""
from __future__ import annotations

from shapely.geometry import LinearRing, LineString, Point, Polygon
from shapely.ops import linemerge, unary_union

from app.services.coverage.validation import TOL_INSIDE_M, Warning


def _offset_left(line: LineString, dist: float) -> LineString | None:
    """The line moved `dist` to its left (negative: right), same direction; None when it
    cannot be drawn (a ring narrower than the offset, a broken offset)."""
    if line.is_closed and len(line.coords) >= 4:
        ring = LinearRing(line.coords)
        # Left of an anticlockwise ring is its inside: shrink; of a clockwise one, grow.
        grown = Polygon(ring).buffer(-dist if ring.is_ccw else dist, join_style="mitre")
        if grown.is_empty or grown.geom_type != "Polygon":
            return None
        coords = list(grown.exterior.coords)
        if LinearRing(coords).is_ccw != ring.is_ccw:
            coords = coords[::-1]
        start = Point(line.coords[0])
        verts = coords[:-1]
        i = min(range(len(verts)), key=lambda j: start.distance(Point(verts[j])))
        rot = verts[i:] + verts[:i]
        return LineString(rot + [rot[0]])
    out = line.offset_curve(dist)
    if out.geom_type == "MultiLineString":
        out = linemerge(out)
    return out if out.geom_type == "LineString" and not out.is_empty else None


def tractor_track(swaths, e: float, half_track: float, parcel: Polygon,
                  zones: list[Polygon]) -> tuple[list[LineString | None], list[Warning]]:
    """Tractor centre line per swath (same order; None where it cannot be drawn) plus
    TRACTOR_TRACK_OUTSIDE when its wheels (centre line +/- half_track) leave the parcel or
    enter a zone, and TRACTOR_TRACK_UNAVAILABLE for lines that cannot be drawn.
    e == 0: nothing to add."""
    if not e:
        return [], []
    lines: list[LineString | None] = []
    bad_idx, bad_parts, missing_idx = [], [], []
    allowed = parcel.buffer(TOL_INSIDE_M)
    blocked = unary_union(zones) if zones else None
    for s in swaths:
        # The implement is e to the right, so the tractor is e to the left.
        line = _offset_left(s.geometry, e)
        lines.append(line)
        if line is None:
            missing_idx.append(s.index)
            continue
        body = line.buffer(half_track, cap_style="flat") if half_track > 0 else line
        outside = body.difference(allowed)
        hit = body.intersection(blocked) if blocked is not None else None
        # A bare centre line (track unknown) touches a zone with length, not area.
        in_zone = hit is not None and not hit.is_empty and (hit.area > 0 or hit.length > 0)
        if not outside.is_empty or in_zone:
            bad_idx.append(s.index)
            bad_parts.append(outside if not outside.is_empty else hit)
    warnings = []
    if bad_idx:
        warnings.append(Warning("TRACTOR_TRACK_OUTSIDE", unary_union(bad_parts), {"swaths": bad_idx}))
    if missing_idx:
        warnings.append(Warning("TRACTOR_TRACK_UNAVAILABLE", None, {"swaths": missing_idx}))
    return lines, warnings
