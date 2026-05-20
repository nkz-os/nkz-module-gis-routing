"""Headland: perimeter passes around field boundary."""

from shapely.geometry import MultiLineString, Polygon

from app.services.routing.base import (
    RoutingStrategy, PatternConfig, RouteResult,
    project_polygon_to_utm, project_linestrings_to_wgs84,
)


def erode_polygon_for_headland(polygon: Polygon, config: PatternConfig) -> Polygon | None:
    """Erode polygon inward by headland passes. Returns the remaining inner polygon,
    or None if the polygon is completely consumed."""
    utm_poly, _, _to_utm, _to_wgs84 = project_polygon_to_utm(polygon)
    ew = config.effective_width_m
    passes = max(config.headland_passes, 1)

    current = utm_poly
    for i in range(passes):
        offset = -ew * (0.5 + i)
        eroded = current.buffer(offset)
        if eroded.is_empty:
            return None
        if not eroded.is_valid:
            eroded = eroded.buffer(0)
        if eroded.geom_type == "MultiPolygon":
            eroded = max(eroded.geoms, key=lambda p: p.area)
        current = eroded

    # Project back to WGS84
    eroded_wgs84 = _to_wgs84(current)
    if isinstance(eroded_wgs84, Polygon) and not eroded_wgs84.is_empty:
        return eroded_wgs84
    return None


class HeadlandStrategy(RoutingStrategy):
    def generate(self, polygon: Polygon, config: PatternConfig) -> RouteResult:
        utm_poly, _, _to_utm, to_wgs84 = project_polygon_to_utm(polygon)

        ew = config.effective_width_m
        passes = max(config.headland_passes, 1)

        headland_lines = []
        current = utm_poly
        for i in range(passes):
            offset = -ew * (0.5 + i)
            eroded = current.buffer(offset)
            if eroded.is_empty:
                break
            if not eroded.is_valid:
                eroded = eroded.buffer(0)

            # Handle MultiPolygon from concave erosion
            if eroded.geom_type == "MultiPolygon":
                eroded = max(eroded.geoms, key=lambda p: p.area)

            boundary = current.exterior
            if boundary and not boundary.is_empty:
                headland_lines.append(boundary)
            current = eroded

        geometry = project_linestrings_to_wgs84(headland_lines, to_wgs84)

        total_dist = sum(line.length for line in headland_lines)
        count = len(headland_lines)
        area = count * ew * total_dist / max(count, 1)
        area_ha = area / 10000.0

        return RouteResult(
            geometry=geometry,
            pattern="headland-only",
            swath_count=count,
            headland_count=count,
            total_distance_m=round(total_dist, 1),
            covered_area_ha=round(area_ha, 2),
            pass_order=[list(range(count))],
        )
