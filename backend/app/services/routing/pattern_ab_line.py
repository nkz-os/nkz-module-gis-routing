"""AB-Line: parallel swaths with fixed heading."""

import math

from shapely.geometry import MultiLineString, Polygon

from app.services.routing.base import (
    PatternConfig,
    RouteResult,
    RoutingStrategy,
    project_linestrings_to_wgs84,
    project_polygon_to_utm,
)
from app.services.routing.intersection import (
    compute_total_distance_m,
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
            metadata={
                "heading_deg": config.heading_deg,
                "effective_width_m": round(config.effective_width_m, 2),
            },
        )
