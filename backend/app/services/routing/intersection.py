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
