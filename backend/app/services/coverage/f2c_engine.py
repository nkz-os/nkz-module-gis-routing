"""Fields2Cover coverage pipeline: headland -> swaths -> route order -> path.

Returns a routing.base.RouteResult in WGS84 with honest coverage metrics.
This is the only orchestration point; F2C stays behind robot_model and
geometry_adapter. API verified against Fields2Cover v2.0.0.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import fields2cover as f2c
from shapely.geometry import LineString, MultiLineString

from app.services.routing.base import (
    RouteResult, project_polygon_to_utm, project_linestrings_to_wgs84,
)
from app.services.coverage.robot_model import RobotParams
from app.services.coverage.geometry_adapter import shapely_to_f2c_cells

_ROUTE_PLANNERS = {
    "boustrophedon": f2c.RP_Boustrophedon,
    "snake": f2c.RP_Snake,
    "spiral": lambda: f2c.RP_Spiral(2),
}


@dataclass
class CoverageConfig:
    pattern: str = "boustrophedon"     # boustrophedon|snake|spiral|headland-only
    heading_deg: float | None = None   # None + efficiency -> F2C best angle
    headland_passes: int = 1
    heading_objective: str = "efficiency"   # "efficiency" | "contour"
    dem_sampler: object = None              # callable(lon,lat)->m, or None
    parcel_bbox: tuple | None = None        # (min_lon,min_lat,max_lon,max_lat)


def generate_coverage(
    wgs84_poly, robot: RobotParams, cfg: CoverageConfig,
) -> RouteResult:
    utm_poly, _crs, _to_utm, to_wgs84 = project_polygon_to_utm(wgs84_poly)
    parcel_area_ha = utm_poly.area / 10000.0

    if cfg.pattern == "headland-only":
        return _headland_only(utm_poly, to_wgs84, robot, cfg, parcel_area_ha)

    cells = shapely_to_f2c_cells(utm_poly)
    f2c_robot = robot.to_f2c_robot()
    passes = max(cfg.headland_passes, 1)

    # 1. Headland band -> working interior cell.
    headland = f2c.HG_Const_gen().generateHeadlands(cells, robot.cov_width * passes)
    work_cell = headland.getGeometry(0)

    # 2. Swaths at chosen heading.
    bf = f2c.SG_BruteForce()
    angle = _resolve_angle(cfg, wgs84_poly)
    if angle is not None:
        swaths = bf.generateSwaths(angle, robot.cov_width, work_cell)
    else:
        swaths = bf.generateBestSwaths(f2c.OBJ_NSwath(), robot.cov_width, work_cell)

    # 3. Order the passes (boustrophedon / snake / spiral).
    planner = _ROUTE_PLANNERS.get(cfg.pattern, f2c.RP_Boustrophedon)()
    ordered = planner.genSortedSwaths(swaths)

    # 4. Plan the connecting path honoring the turning radius.
    curve = (
        f2c.PP_ReedsSheppCurves() if robot.curve_type == "reeds_shepp"
        else f2c.PP_DubinsCurves()
    )
    path = f2c.PP_PathPlanning().planPath(f2c_robot, ordered, curve)

    # 5. Geometry (continuous route incl. turns) + honest metrics.
    geometry = _route_to_wgs84(path, to_wgs84)
    worked = sum(ordered.at(i).length() for i in range(ordered.size()))
    total = path.length()
    non_working = max(total - worked, 0.0)
    covered_ha = min(worked * robot.cov_width / 10000.0, parcel_area_ha)

    return RouteResult(
        geometry=geometry, pattern=cfg.pattern,
        swath_count=ordered.size(), headland_count=passes,
        total_distance_m=round(total, 1), covered_area_ha=round(covered_ha, 3),
        pass_order=[list(range(ordered.size()))],
        metadata={"curve_type": robot.curve_type},
        metrics=_metrics(worked, non_working, covered_ha, parcel_area_ha),
    )


def _resolve_angle(cfg: CoverageConfig, wgs84_poly) -> float | None:
    """Return the swath angle in radians, or None to let F2C optimize it."""
    if cfg.heading_deg is not None:
        return _deg_to_rad(cfg.heading_deg)
    if cfg.heading_objective == "contour" and cfg.dem_sampler and cfg.parcel_bbox:
        from app.services.coverage.contour import best_contour_heading_deg
        centroid = (wgs84_poly.centroid.x, wgs84_poly.centroid.y)
        return _deg_to_rad(
            best_contour_heading_deg(centroid, cfg.parcel_bbox, cfg.dem_sampler)
        )
    return None


def _route_to_wgs84(path, to_wgs84) -> MultiLineString:
    """Convert an F2C Path to a WGS84 MultiLineString via path.toLineString()."""
    ls = path.toLineString()
    coords = [(ls.getGeometry(i).getX(), ls.getGeometry(i).getY())
              for i in range(ls.size())]
    if len(coords) < 2:
        return MultiLineString([])
    arr = np.array(coords)
    wx, wy = to_wgs84(arr[:, 0], arr[:, 1])
    return MultiLineString([LineString(np.column_stack((wx, wy)))])


def _headland_only(utm_poly, to_wgs84, robot, cfg, parcel_area_ha) -> RouteResult:
    """Perimeter passes only, eroding inward by cov_width per pass (shapely).

    F2C's headland generator returns the remaining interior, not the ring
    lines, so the perimeter rings are produced here with the projection helpers
    already used by the rest of the module.
    """
    ew = robot.cov_width
    passes = max(cfg.headland_passes, 1)
    rings = []
    cur = utm_poly
    for _ in range(passes):
        if cur.is_empty:
            break
        boundary = cur.exterior
        if boundary is not None and not boundary.is_empty:
            rings.append(LineString(boundary.coords))
        cur = cur.buffer(-ew)
        if cur.geom_type == "MultiPolygon" and not cur.is_empty:
            cur = max(cur.geoms, key=lambda p: p.area)
    geometry = project_linestrings_to_wgs84(rings, to_wgs84)
    total = sum(r.length for r in rings)
    remaining = 0.0 if cur.is_empty else cur.area
    covered_ha = (parcel_area_ha * 10000.0 - remaining) / 10000.0
    return RouteResult(
        geometry=geometry, pattern="headland-only",
        swath_count=len(rings), headland_count=len(rings),
        total_distance_m=round(total, 1), covered_area_ha=round(covered_ha, 3),
        pass_order=[list(range(len(rings)))],
        metadata={"headland_passes": passes},
        metrics=_metrics(total, 0.0, covered_ha, parcel_area_ha),
    )


def _metrics(worked, non_working, covered_ha, parcel_ha) -> dict:
    total = worked + non_working
    return {
        "worked_distance_m": round(worked, 1),
        "non_working_distance_m": round(non_working, 1),
        "field_efficiency": round(worked / total, 4) if total > 0 else 0.0,
        "covered_area_ha": round(covered_ha, 3),
        "parcel_area_ha": round(parcel_ha, 3),
    }


def _deg_to_rad(deg: float) -> float:
    return math.radians(90 - deg)  # azimuth (0=N, CW) -> math angle (0=E, CCW)
