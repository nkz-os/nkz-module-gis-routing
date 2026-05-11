"""AB-Skip: alternating skip-row pattern for seeding operations."""

import math
from shapely.geometry import LineString, MultiLineString, Polygon

from app.services.routing.base import (
    RoutingStrategy, PatternConfig, RouteResult,
    project_polygon_to_utm, project_linestrings_to_wgs84,
)
from app.services.routing.intersection import (
    generate_parallel_swaths, compute_total_distance_m,
)


class ABSkipStrategy(RoutingStrategy):
    def generate(self, polygon: Polygon, config: PatternConfig) -> RouteResult:
        utm_poly, _, to_utm, to_wgs84 = project_polygon_to_utm(polygon)
        centroid = polygon.centroid
        start_x, start_y = to_utm(centroid.x, centroid.y)

        heading_rad = math.radians(90 - config.heading_deg)
        spacing = config.effective_width_m

        all_swaths = generate_parallel_swaths(
            utm_poly, start_x, start_y, heading_rad, spacing,
        )

        # Split into passes: each pass = one swath (skip_rows between)
        passes = []
        for offset in range(config.skip_rows + 1):
            pass_swaths = all_swaths[offset::config.skip_rows + 1]
            if pass_swaths:
                passes.append(pass_swaths)

        all_wgs = []
        for p in passes:
            all_wgs.extend(list(project_linestrings_to_wgs84(p, to_wgs84).geoms))

        geometry = MultiLineString(all_wgs)
        total_dist = sum(compute_total_distance_m(p) for p in passes)
        swath_count = sum(len(p) for p in passes)
        area = swath_count * config.effective_width_m * (total_dist / max(swath_count, 1))
        area_ha = area / 10000.0

        return RouteResult(
            geometry=geometry,
            pattern="ab-skip",
            swath_count=swath_count,
            headland_count=0,
            total_distance_m=round(total_dist, 1),
            covered_area_ha=round(area_ha, 2),
            pass_order=[[i for i in range(len(p))] for p in passes],
            metadata={
                "heading_deg": config.heading_deg,
                "skip_rows": config.skip_rows,
                "num_passes": len(passes),
            },
        )
