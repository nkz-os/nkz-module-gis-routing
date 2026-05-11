"""Spiral pattern: inside-out or outside-in for harvesting operations.

Both directions use the same ring-generation process (buffer erosion inward),
differing only in traversal order. Outside-in starts from the outermost ring
and spirals inward; inside-out reverses the ring order.
"""

from shapely.geometry import LineString, Polygon

from app.services.routing.base import (
    RoutingStrategy, PatternConfig, RouteResult,
    project_polygon_to_utm, project_linestrings_to_wgs84,
)


class SpiralStrategy(RoutingStrategy):
    def generate(self, polygon: Polygon, config: PatternConfig) -> RouteResult:
        utm_poly, _, _to_utm, to_wgs84 = project_polygon_to_utm(polygon)

        ew = config.effective_width_m

        # Always erode inward to build concentric rings — both directions
        # use the same ring set, only traversal order differs.
        rings = []
        current = utm_poly
        safety = 0
        while safety < 200:
            eroded = current.buffer(-ew)
            if eroded.is_empty:
                break
            if not eroded.is_valid:
                eroded = eroded.buffer(0)
            if eroded.is_empty:
                break

            # Handle MultiPolygon from concave erosion (split at narrow points)
            if eroded.geom_type == "MultiPolygon":
                eroded = max(eroded.geoms, key=lambda p: p.area)

                boundary = current.exterior
            if boundary is not None and not boundary.is_empty:
                rings.append(boundary)

            current = eroded
            safety += 1

        if config.direction == "inside-out":
            rings.reverse()

        spiral_utm = _connect_rings(rings)

        geometry = project_linestrings_to_wgs84(spiral_utm, to_wgs84)

        total_dist = sum(line.length for line in spiral_utm)
        ring_count = len(rings)
        area = ring_count * ew * (total_dist / max(ring_count, 1))
        area_ha = area / 10000.0

        return RouteResult(
            geometry=geometry,
            pattern=f"spiral-{config.direction}",
            swath_count=ring_count,
            headland_count=0,
            total_distance_m=round(total_dist, 1),
            covered_area_ha=round(area_ha, 2),
            pass_order=[list(range(ring_count))],
            metadata={
                "direction": config.direction,
                "ring_count": ring_count,
            },
        )


def _connect_rings(rings: list) -> list:
    """Connect concentric rings with diagonal transition segments."""
    if len(rings) <= 1:
        return rings

    spiral_lines = []
    for i, ring in enumerate(rings):
        coords = list(ring.coords)
        spiral_lines.append(LineString(coords))
        if i < len(rings) - 1:
            next_coords = list(rings[i + 1].coords)
            if coords and next_coords:
                transition = LineString([coords[-1], next_coords[0]])
                spiral_lines.append(transition)

    return spiral_lines
