"""AB-Line: parallel swaths with fixed heading."""

import math

from shapely.geometry import LineString, MultiLineString, Polygon

from app.services.routing.base import (
    PatternConfig,
    RouteResult,
    RoutingStrategy,
    project_linestrings_to_wgs84,
    project_polygon_to_utm,
)
from app.services.routing.intersection import (
    build_serpentine_segments,
    compute_total_distance_m,
    connect_swaths_serpentine,
    generate_parallel_swaths,
)


class ABLineStrategy(RoutingStrategy):
    def generate(self, polygon: Polygon, config: PatternConfig) -> RouteResult:
        utm_poly, _, to_utm, to_wgs84 = project_polygon_to_utm(polygon)
        centroid = polygon.centroid
        start_x, start_y = to_utm(centroid.x, centroid.y)

        heading_rad = math.radians(90 - config.heading_deg)
        swaths_utm = generate_parallel_swaths(
            utm_poly, start_x, start_y, heading_rad, config.effective_width_m,
        )

        geometry = project_linestrings_to_wgs84(swaths_utm, to_wgs84)

        # Build continuous serpentine path with maneuver flags
        continuous_utm = connect_swaths_serpentine(swaths_utm)
        segments_utm = build_serpentine_segments(swaths_utm)

        # Project maneuver segments to WGS84
        maneuver_segments = []
        for seg in segments_utm:
            utm_coords = seg["coords"]
            wgs_coords = []
            for x, y in utm_coords:
                wx, wy = to_wgs84(x, y)
                wgs_coords.append([wx, wy])
            maneuver_segments.append({
                "coords": wgs_coords,
                "type": seg["type"],
                "swath_index": seg["swath_index"],
            })

        path_continuous = None
        if continuous_utm is not None:
            path_continuous = project_linestrings_to_wgs84(
                [continuous_utm], to_wgs84,
            )

        swath_count = len(swaths_utm)
        total_dist = compute_total_distance_m(swaths_utm)
        area = swath_count * config.effective_width_m * (total_dist / max(swath_count, 1))
        area_ha = area / 10000.0

        return RouteResult(
            geometry=geometry,
            pattern="ab-line",
            swath_count=swath_count,
            headland_count=0,
            total_distance_m=round(total_dist, 1),
            covered_area_ha=round(area_ha, 2),
            pass_order=[list(range(swath_count))],
            path_continuous=path_continuous,
            maneuver_segments=maneuver_segments,
            metadata={
                "heading_deg": config.heading_deg,
                "effective_width_m": round(config.effective_width_m, 2),
            },
        )
