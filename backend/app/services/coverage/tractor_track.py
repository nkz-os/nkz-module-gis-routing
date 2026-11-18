"""Where the tractor drives when the implement works off to one side (side mowers).

The plan's passes are the implement's working centre lines, so the work is even. With a
lateral offset e (> 0: implement to the right of the travel) the tractor runs |e| to the
other side of each pass. That track must stay inside the parcel and out of the no-go
zones; when it does not, the plan reports it (nothing is moved or invented).
"""
from __future__ import annotations

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from app.services.coverage.validation import TOL_INSIDE_M, Warning


def tractor_track(swaths, e: float, half_track: float, parcel: Polygon,
                  zones: list[Polygon]) -> tuple[list[LineString], list[Warning]]:
    """Tractor centre line per swath (same order) and TRACTOR_TRACK_OUTSIDE when its wheels
    (centre line +/- half_track) leave the parcel or enter a zone. e == 0: nothing to add."""
    if not e:
        return [], []
    lines: list[LineString] = []
    bad_idx: list[int] = []
    bad_parts = []
    allowed = parcel.buffer(TOL_INSIDE_M)
    blocked = unary_union(zones) if zones else None
    for s in swaths:
        # offset_curve: positive distance = left of the line's direction. The implement is
        # e to the right, so the tractor is e to the left (or |e| right when e < 0).
        line = s.geometry.offset_curve(e)
        if line.geom_type != "LineString" or line.is_empty:
            line = LineString(s.geometry.coords)  # degenerate offset: keep the pass, still checked
        lines.append(line)
        body = line.buffer(half_track, cap_style="flat") if half_track > 0 else line
        outside = body.difference(allowed)
        hit = body.intersection(blocked) if blocked is not None else None
        if not outside.is_empty or (hit is not None and not hit.is_empty and hit.area > 0):
            bad_idx.append(s.index)
            bad_parts.append(outside if not outside.is_empty else hit)
    warnings = ([Warning("TRACTOR_TRACK_OUTSIDE", unary_union(bad_parts), {"swaths": bad_idx})]
                if bad_idx else [])
    return lines, warnings
