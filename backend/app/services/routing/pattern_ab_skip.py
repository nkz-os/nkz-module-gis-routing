"""AB-Skip: alternating skip-row pattern for seeding operations."""

import math
from shapely.geometry import LineString, MultiLineString, Polygon

from app.services.routing.base import (
    RoutingStrategy, PatternConfig, RouteResult,
    project_polygon_to_utm, project_linestrings_to_wgs84,
)
from app.services.routing.intersection import (
    build_serpentine_segments,
    compute_total_distance_m,
    connect_swaths_serpentine,
    generate_parallel_swaths,
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

        # Build maneuver segments per pass
        all_maneuver_segments = []
        continuous_lines = []
        for pass_idx, pass_swaths in enumerate(passes):
            segs = build_serpentine_segments(pass_swaths)
            for seg in segs:
                wgs_coords = []
                for x, y in seg["coords"]:
                    wx, wy = to_wgs84(x, y)
                    wgs_coords.append([wx, wy])
                all_maneuver_segments.append({
                    "coords": wgs_coords,
                    "type": seg["type"],
                    "swath_index": seg["swath_index"],
                    "pass_index": pass_idx,
                })
            cont = connect_swaths_serpentine(pass_swaths)
            if cont is not None:
                continuous_lines.append(cont)

        path_continuous = None
        if continuous_lines:
            path_continuous = project_linestrings_to_wgs84(continuous_lines, to_wgs84)

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
            path_continuous=path_continuous,
            maneuver_segments=all_maneuver_segments,
            metadata={
                "heading_deg": config.heading_deg,
                "skip_rows": config.skip_rows,
                "num_passes": len(passes),
            },
        )
