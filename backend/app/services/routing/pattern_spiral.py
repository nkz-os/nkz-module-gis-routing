"""Spiral pattern: inside-out or outside-in for harvesting operations."""

import math

from shapely.geometry import (
    LineString, MultiLineString, Polygon,
)

from app.services.routing.base import (
    RoutingStrategy, PatternConfig, RouteResult,
    project_polygon_to_utm, project_linestrings_to_wgs84,
)


class SpiralStrategy(RoutingStrategy):
    def generate(self, polygon: Polygon, config: PatternConfig) -> RouteResult:
        utm_poly, _, to_utm, to_wgs84 = project_polygon_to_utm(polygon)

        ew = config.effective_width_m
        offset_step = ew if config.direction == "inside-out" else -ew

        rings = []
        current = utm_poly
        safety = 0
        while safety < 200:
            eroded = current.buffer(offset_step)
            if eroded.is_empty:
                break
            if not eroded.is_valid:
                eroded = eroded.buffer(0)
            if eroded.is_empty:
                break

            boundary = current.exterior
            if boundary is not None and not boundary.is_empty:
                rings.append(boundary)

            current = eroded
            safety += 1

        if config.direction == "outside-in":
            rings.reverse()

        spiral_utm = _connect_rings(rings)

        geometry = project_linestrings_to_wgs84(spiral_utm, to_wgs84)

        total_dist = sum(line.length for line in spiral_utm)
        swath_count = len(spiral_utm)
        area = swath_count * ew * (total_dist / max(swath_count, 1))
        area_ha = area / 10000.0

        return RouteResult(
            geometry=geometry,
            pattern=f"spiral-{config.direction}",
            swath_count=swath_count,
            headland_count=0,
            total_distance_m=round(total_dist, 1),
            covered_area_ha=round(area_ha, 2),
            pass_order=[list(range(swath_count))],
            metadata={
                "direction": config.direction,
                "ring_count": len(rings),
            },
        )


def _connect_rings(rings: list) -> list:
    """Connect concentric rings with diagonal transition segments."""
    from shapely.geometry import LineString

    if len(rings) <= 1:
        return rings

    spiral_lines = []
    for i, ring in enumerate(rings):
        coords = list(ring.coords)
        spiral_lines.append(LineString(coords))
        # Add transition to next ring
        if i < len(rings) - 1:
            next_coords = list(rings[i + 1].coords)
            if coords and next_coords:
                transition = LineString([coords[-1], next_coords[0]])
                spiral_lines.append(transition)

    return spiral_lines
