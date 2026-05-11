"""Clipping and geometry intersection utilities shared across strategies."""

import math

import numpy as np
from shapely.geometry import LineString, MultiLineString, Polygon


def generate_parallel_swaths(
    utm_poly: Polygon,
    start_x: float,
    start_y: float,
    heading_rad: float,
    effective_width_m: float,
) -> list[LineString]:
    """Generate parallel swaths clipped to the polygon. Core AB-line algorithm."""
    dx = math.cos(heading_rad)
    dy = math.sin(heading_rad)
    p_dx = math.cos(heading_rad + math.pi / 2)
    p_dy = math.sin(heading_rad + math.pi / 2)

    minx, miny, maxx, maxy = utm_poly.bounds
    diag = math.hypot(maxx - minx, maxy - miny)

    ref_x1 = start_x - dx * diag
    ref_y1 = start_y - dy * diag
    ref_x2 = start_x + dx * diag
    ref_y2 = start_y + dy * diag

    utm_exterior = np.array(utm_poly.exterior.coords)
    offsets = []
    for point in utm_exterior:
        vx = point[0] - start_x
        vy = point[1] - start_y
        offsets.append(vx * p_dx + vy * p_dy)

    max_offset = max(offsets)
    min_offset = min(offsets)
    max_idx = int(math.ceil(max_offset / effective_width_m))
    min_idx = int(math.floor(min_offset / effective_width_m))

    swaths = []
    for i in range(min_idx, max_idx + 1):
        offset_dist = i * effective_width_m
        off_x1 = ref_x1 + p_dx * offset_dist
        off_y1 = ref_y1 + p_dy * offset_dist
        off_x2 = ref_x2 + p_dx * offset_dist
        off_y2 = ref_y2 + p_dy * offset_dist

        swath_line = LineString([(off_x1, off_y1), (off_x2, off_y2)])
        intersected = swath_line.intersection(utm_poly)
        if intersected.is_empty:
            continue
        if intersected.geom_type == "LineString":
            swaths.append(intersected)
        elif intersected.geom_type == "MultiLineString":
            for line in intersected.geoms:
                swaths.append(line)

    return swaths


def compute_total_distance_m(utm_lines: list[LineString]) -> float:
    return sum(line.length for line in utm_lines)


def connect_swaths_serpentine(swaths: list[LineString]) -> LineString | None:
    """Connect swaths in serpentine order. Returns a single continuous LineString."""
    segments = _build_serpentine_segments(swaths)
    if not segments:
        return None
    # Flatten all segments into one continuous line
    all_coords = []
    for seg in segments:
        for coord in seg["coords"]:
            if not all_coords or all_coords[-1] != coord:
                all_coords.append(coord)
    return LineString(all_coords)


def build_serpentine_segments(swaths: list[LineString]) -> list[dict]:
    """Build serpentine path with maneuver flags for each segment.

    Returns a list of segments, each with:
      - coords: list of [x, y] points
      - type: "work" (implement engaged) or "turn" (maneuver between passes)
      - swath_index: index of the work swath (None for turn segments)
    """
    if len(swaths) < 1:
        return []

    segments = []
    for i, swath in enumerate(swaths):
        points = list(swath.coords)
        if i % 2 == 1:
            points.reverse()

        # Add turn segment from previous swath end to this swath start
        if i > 0 and segments:
            prev = segments[-1]
            prev_end = prev["coords"][-1]
            curr_start = points[0]
            segments.append({
                "coords": [prev_end, curr_start],
                "type": "turn",
                "swath_index": None,
            })

        # Add work segment
        segments.append({
            "coords": points,
            "type": "work",
            "swath_index": i,
        })

    return segments


def _build_serpentine_segments(swaths) -> list[dict]:
    """Internal: delegate to build_serpentine_segments."""
    return build_serpentine_segments(swaths)
