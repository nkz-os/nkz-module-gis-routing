"""Fields2Cover coverage pipeline: headland -> swaths -> route order -> path.

plan_coverage() is the core: it works in UTM, splits the F2C path into
pasadas (Swath) and giros (Turn), appends the headland rings and orients the
route to the access point. generate_coverage() is a thin compatibility wrapper
returning a routing.base.RouteResult in WGS84. F2C stays behind robot_model and
geometry_adapter. API verified against Fields2Cover v2.0.0.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import fields2cover as f2c
from shapely.geometry import LineString, Point, Polygon
from app.services.exclusion import build_working_polygon, route_enters_zones, ExclusionError

from app.services.routing.base import RouteResult, project_polygon_to_utm
from app.services.coverage.access import compute_access_path
from app.services.coverage.plan import CoveragePlan, Swath, Turn
from app.services.coverage.robot_model import RobotParams
from app.services.coverage.geometry_adapter import shapely_to_f2c_cells
from app.services.coverage.validation import split_working_area

logger = logging.getLogger(__name__)

_ROUTE_PLANNERS = {
    "boustrophedon": f2c.RP_Boustrophedon,
    "snake": f2c.RP_Snake,
    "spiral": lambda: f2c.RP_Spiral(2),
}
_EPS = 1e-9
TURN_SIMPLIFY_M = 0.05   # F2C emits a turn point every ~0.1 m; keep curves within 5 cm
# F2C's default curve discretization (0.01 m) doubles planPath time on large
# parcels; 0.1 m changes a turn by < 1 mm (chord sagitta at R = 5 m).
TURN_DISCRETIZATION_M = 0.1


@dataclass
class CoverageConfig:
    pattern: str = "boustrophedon"     # boustrophedon|snake|spiral|headland-only
    heading_deg: float | None = None   # None + efficiency -> F2C best angle
    headland_passes: int = 1
    heading_objective: str = "efficiency"   # "efficiency" | "contour"
    dem_sampler: object = None              # callable(lon,lat)->m, or None
    parcel_bbox: tuple | None = None        # (min_lon,min_lat,max_lon,max_lat)
    return_to_access: bool = False          # close the route back at the access point


def generate_coverage(
    wgs84_poly, robot: RobotParams, cfg: CoverageConfig,
    exclusion_zones_wgs84: list | None = None,
    exclusion_buffer_m: float = 0.0,
    start_point_wgs84: tuple | None = None,
) -> RouteResult:
    """Compatibility wrapper: project, build working area, plan, return WGS84."""
    utm_poly, _crs, to_utm, to_wgs84 = project_polygon_to_utm(wgs84_poly)
    work = utm_poly

    if exclusion_zones_wgs84:
        zones_utm = []
        for z in exclusion_zones_wgs84:
            zx, zy = to_utm(*z.exterior.coords.xy)
            zones_utm.append(Polygon(zip(zx, zy)))
        buffer_m = exclusion_buffer_m if exclusion_buffer_m > 0 else robot.cov_width / 2.0
        work = build_working_polygon(utm_poly, zones_utm, buffer_m)

    access_utm = None
    if start_point_wgs84 is not None:
        sx, sy = to_utm(start_point_wgs84[0], start_point_wgs84[1])
        access_utm = Point(sx, sy)

    piece, _unreached = split_working_area(work, access_utm)

    plan = plan_coverage(piece, utm_poly, robot, cfg,
                         access_utm=access_utm, wgs84_poly=wgs84_poly)
    result = plan.to_route_result(to_wgs84, robot.cov_width)

    # Fail-safe: working swaths are clipped away from the zones, but F2C's
    # obstacle-blind connecting/turn curves can still cross a no-go zone.
    # Never emit a route that enters a no-go area — fail instead.
    if exclusion_zones_wgs84 and route_enters_zones(result.geometry, exclusion_zones_wgs84):
        raise ExclusionError("Generated route would cross a no-go zone")
    return result


def plan_coverage(
    piece_utm: Polygon, parcel_utm: Polygon, robot: RobotParams, cfg: CoverageConfig, *,
    access_utm: Point | None, wgs84_poly: Polygon, swath_cache: dict | None = None,
) -> CoveragePlan:
    """Plan pasadas, giros and headland rings over one drivable piece (UTM).

    swath_cache: optional dict shared by the attempts over the same piece; F2C
    headlands + swaths are computed once per (passes, cov_width, heading) and
    only ordering and path planning run per pattern/curve.
    """
    passes = max(cfg.headland_passes, 1)
    w = robot.cov_width

    # parts: ("swath", geometry) | ("turn", geometry), in travel order.
    # headland-only: no interior swaths, the rings below are the whole plan.
    parts = ([] if cfg.pattern == "headland-only"
             else _interior_parts(piece_utm, robot, cfg, wgs84_poly, passes, swath_cache))

    # Orient to the access point BEFORE adding the rings.
    if access_utm is not None and parts:
        first = parts[0][1].coords[0]
        last = parts[-1][1].coords[-1]
        if access_utm.distance(Point(last)) < access_utm.distance(Point(first)):
            parts = [(k, LineString(list(g.coords)[::-1])) for k, g in parts[::-1]]

    # Headland rings, innermost first, outermost last.
    rings = _headland_rings(piece_utm, w, passes)
    if len(rings) < passes:
        logger.warning(
            "headland rings fewer than requested",
            extra={"requested": passes, "produced": len(rings), "cov_width": w},
        )
    prev = Point(parts[-1][1].coords[-1]) if parts else access_utm
    for ring in rings:
        ring = _rotate_ring(ring, prev)
        if parts and prev is not None and prev.distance(Point(ring.coords[0])) > _EPS:
            parts.append(("turn", LineString([prev.coords[0], ring.coords[0]])))
        parts.append(("headland", ring))
        prev = Point(ring.coords[-1])

    if not any(k != "turn" for k, _ in parts):
        raise ExclusionError("No drivable area remains", code="NO_DRIVABLE_AREA")

    route_coords: list[tuple[float, float]] = []
    for _k, g in parts:
        for c in g.coords:
            if not route_coords or math.hypot(c[0] - route_coords[-1][0],
                                              c[1] - route_coords[-1][1]) > _EPS:
                route_coords.append((c[0], c[1]))
    route = LineString(route_coords)
    exit_point = Point(route.coords[-1])

    if cfg.return_to_access and access_utm is not None:
        back = compute_access_path(exit_point, access_utm, piece_utm)
        if back is not None:
            parts.append(("turn", back))
            exit_point = Point(access_utm.x, access_utm.y)
            route = LineString(route_coords + [c for c in back.coords][1:])
        else:
            logger.warning("no return path to access point",
                           extra={"exit": (exit_point.x, exit_point.y)})

    access_path = None
    if access_utm is not None:
        access_path = compute_access_path(access_utm, Point(route.coords[0]), piece_utm)

    swaths, turns = _index_parts(parts)
    return CoveragePlan(
        pattern=cfg.pattern, curve_type=robot.curve_type, headland_passes=passes,
        swaths=swaths, turns=turns, route=route, working_area=piece_utm,
        unreached=[], parcel_area_m2=parcel_utm.area, access_point=access_utm,
        access_path=access_path, exit_point=exit_point, exclusion_zones=[],
    )


def _interior_parts(piece_utm, robot, cfg, wgs84_poly, passes, swath_cache=None) -> list:
    """F2C interior swaths + turns as ordered ("swath"|"turn", LineString) parts."""
    angle = _resolve_angle(cfg, wgs84_poly)
    key = (passes, robot.cov_width, angle)
    if swath_cache is not None and key in swath_cache:
        swaths = swath_cache[key]
    else:
        swaths = _generate_swaths(piece_utm, robot.cov_width, passes, angle)
        if swath_cache is not None:
            swath_cache[key] = swaths
    if swaths is None:
        return []

    planner = _ROUTE_PLANNERS.get(cfg.pattern, f2c.RP_Boustrophedon)()
    ordered = planner.genSortedSwaths(swaths)
    curve = (
        f2c.PP_ReedsSheppCurves() if robot.curve_type == "reeds_shepp"
        else f2c.PP_DubinsCurves()
    )
    curve.setDiscretization(TURN_DISCRETIZATION_M)
    path = f2c.PP_PathPlanning().planPath(robot.to_f2c_robot(), ordered, curve)
    return [(k, g.simplify(TURN_SIMPLIFY_M, preserve_topology=True) if k == "turn" else g)
            for k, g in _split_path(path)]


def _generate_swaths(piece_utm, cov_width: float, passes: int, angle: float | None):
    """F2C headland reduction + swath generation; None when no swath fits."""
    cells = shapely_to_f2c_cells(piece_utm)
    headland = f2c.HG_Const_gen().generateHeadlands(cells, cov_width * passes)
    if headland.size() == 0:
        return None
    work_cell = headland.getGeometry(0)
    if work_cell.area() <= 0:
        return None
    bf = f2c.SG_BruteForce()
    if angle is not None:
        swaths = bf.generateSwaths(angle, cov_width, work_cell)
    else:
        swaths = bf.generateBestSwaths(f2c.OBJ_NSwath(), cov_width, work_cell)
    return swaths if swaths.size() > 0 else None


def _split_path(path) -> list:
    """Split an F2C Path into ordered ("swath"|"turn", LineString) parts.

    Probe (F2C 2.0.0, CI image): path.getStates() is indexable (size(), [i]).
    Each PathState has type, point, angle, len, dir. A swath (type
    PathSectionType_SWATH=1 / HL_SWATH=3) is stored as ONE state: point = start,
    angle = heading (rad, math convention), len = length, so its end is
    point + len*(cos, sin). A turn (type TURN=2) is a dense run of states
    (~0.1 m apart), each point being the start of a short segment; the first
    turn point equals the previous swath end and the next swath start follows
    the last turn point. A run's LineString is closed with the next run's first
    point so consecutive parts share their junction vertex.
    """
    states = path.getStates()
    swath_types = (f2c.PathSectionType_SWATH, f2c.PathSectionType_HL_SWATH)
    runs: list[tuple[str, list[tuple[float, float]]]] = []
    for i in range(states.size()):
        s = states[i]
        x, y = s.point.getX(), s.point.getY()
        if s.type in swath_types:
            end = (x + s.len * math.cos(s.angle), y + s.len * math.sin(s.angle))
            runs.append(("swath", [(x, y), end]))
        elif s.type == f2c.PathSectionType_TURN:
            if runs and runs[-1][0] == "turn":
                runs[-1][1].append((x, y))
            else:
                runs.append(("turn", [(x, y)]))
    parts = []
    for n, (kind, raw) in enumerate(runs):
        if kind == "turn" and n + 1 < len(runs):
            raw = raw + [runs[n + 1][1][0]]
        pts = [raw[0]]
        for p in raw[1:]:   # drop consecutive duplicates, O(n)
            if math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > _EPS:
                pts.append(p)
        if len(pts) < 2:
            continue
        parts.append((kind, LineString(pts)))
        # Two swaths with no TURN state between them: record the jump as a
        # straight connector so the route stays continuous and the turn is
        # a first-class, removable part.
        if kind == "swath" and n + 1 < len(runs) and runs[n + 1][0] == "swath":
            a, b = pts[-1], runs[n + 1][1][0]
            if math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-6:
                parts.append(("turn", LineString([a, b])))
    return parts


def _headland_rings(piece: Polygon, w: float, passes: int) -> list:
    """Closed rings at w/2 + k*w inside the fence, ordered innermost -> outermost."""
    # Built from the exterior only: holes get no rings (the wrapper's fail-safe
    # and the ladder's validation guard crossings).
    rings = []
    for k in range(passes):
        ring_poly = piece.buffer(-(w / 2.0 + k * w))
        if ring_poly.is_empty:
            break
        if ring_poly.geom_type == "MultiPolygon":
            ring_poly = max(ring_poly.geoms, key=lambda g: g.area)
        rings.append(LineString(ring_poly.exterior.coords))
    return rings[::-1]


def _rotate_ring(ring: LineString, prev: Point | None) -> LineString:
    """Start the closed ring at its vertex nearest to prev, and re-close it."""
    if prev is None:
        return ring
    verts = list(ring.coords)[:-1]
    i = min(range(len(verts)), key=lambda j: prev.distance(Point(verts[j])))
    rot = verts[i:] + verts[:i]
    return LineString(rot + [rot[0]])


def _index_parts(parts) -> tuple[list, list]:
    """Assign swath/turn indices; each turn links the swaths around it."""
    swaths: list[Swath] = []
    turns: list[Turn] = []
    pending: list[LineString] = []
    for kind, g in parts:
        if kind == "turn":
            pending.append(g)
            continue
        idx = len(swaths)
        swaths.append(Swath(idx, "headland" if kind == "headland" else "work", g))
        for t in pending:
            turns.append(Turn(len(turns), max(idx - 1, 0), idx, t))
        pending = []
    last = max(len(swaths) - 1, 0)
    for t in pending:
        turns.append(Turn(len(turns), last, last, t))
    return swaths, turns


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


def _deg_to_rad(deg: float) -> float:
    return math.radians(90 - deg)  # azimuth (0=N, CW) -> math angle (0=E, CCW)
