"""Pure geometric guarantees for coverage plans (UTM metres, no Fields2Cover)."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import shapely
from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from app.services.coverage.plan import CoveragePlan, geojson_wgs84
from app.services.exclusion import ExclusionError

logger = logging.getLogger(__name__)

TOL_INSIDE_M = 0.5
TOL_ZONE_M = 0.1
ACCESS_START_MAX_M = 1.0


@dataclass
class Check:
    id: str
    ok: bool
    value: float
    limit: float
    geometry: BaseGeometry | None


@dataclass
class Warning:  # noqa: A001 - name fixed by the plan contract
    code: str
    geometry: BaseGeometry | None
    params: dict


@dataclass
class ValidationReport:
    ok: bool
    checks: list[Check]
    fallbacks_applied: list[str]
    warnings: list[Warning]

    def to_dict(self, to_wgs84) -> dict:
        return {
            "ok": self.ok,
            "checks": [
                {"id": c.id, "ok": c.ok, "value": c.value, "limit": c.limit,
                 "geometry": geojson_wgs84(c.geometry, to_wgs84)}
                for c in self.checks
            ],
            "fallbacks_applied": list(self.fallbacks_applied),
            "warnings": [
                {"code": w.code, "geometry": geojson_wgs84(w.geometry, to_wgs84), "params": w.params}
                for w in self.warnings
            ],
        }


def min_headland_passes(turning_radius_m: float, cov_width_m: float) -> int:
    return max(1, math.ceil((turning_radius_m + cov_width_m / 2) / cov_width_m))


def _polygons(geom: BaseGeometry) -> list[Polygon]:
    """Flatten to the non-empty Polygon parts, dropping lines and points."""
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if hasattr(geom, "geoms"):
        return [p for g in geom.geoms for p in _polygons(g)]
    return []


def split_working_area(work: BaseGeometry, access: Point | None) -> tuple[Polygon, list[Polygon]]:
    if isinstance(work, Polygon) and not work.is_empty:
        return work, []
    pieces = sorted(_polygons(work), key=lambda g: g.area, reverse=True)
    if not pieces:
        raise ExclusionError("No drivable area remains", code="NO_DRIVABLE_AREA")
    if access is None:
        return pieces[0], pieces[1:]
    for i, p in enumerate(pieces):
        if p.covers(access):
            return p, pieces[:i] + pieces[i + 1:]
    raise ExclusionError(
        "Access point is not inside any drivable area",
        code="NO_DRIVABLE_AREA",
        params={"point": {"type": "Point", "coordinates": [float(access.x), float(access.y)]}},
    )


def check_inside_parcel(geom: BaseGeometry, parcel: Polygon, cov_width: float,
                        *, erode: bool = True) -> Check:
    allowed = parcel.buffer(-cov_width / 2 + TOL_INSIDE_M if erode else TOL_INSIDE_M)
    if allowed.is_empty:
        # parcel narrower than the implement: the whole geometry is outside
        return Check("inside_parcel", False, round(float(geom.length), 2), 0.0, geom)
    outside = geom.difference(allowed)
    if outside.is_empty:
        return Check("inside_parcel", True, 0.0, 0.0, None)
    value = max(Point(v).distance(allowed) for v in shapely.get_coordinates(outside))
    value = round(float(value), 2)
    return Check("inside_parcel", False, value, 0.0, outside)


def check_outside_zones(geom: BaseGeometry, zones: list[Polygon], cov_width: float) -> Check:
    if not zones:
        return Check("outside_zones", True, 0.0, 0.0, None)
    forbidden = unary_union([z.buffer(cov_width / 2 - TOL_ZONE_M) for z in zones])
    hit = geom.intersection(forbidden)
    if hit.is_empty or hit.length == 0:
        return Check("outside_zones", True, 0.0, 0.0, None)
    return Check("outside_zones", False, round(float(hit.length), 2), 0.0, hit)


def check_starts_at_access(start: Point | None, access: Point | None) -> Check:
    if access is None or start is None:
        return Check("starts_at_access", True, 0.0, ACCESS_START_MAX_M, None)
    d = round(float(start.distance(access)), 2)
    return Check("starts_at_access", d <= ACCESS_START_MAX_M, d, ACCESS_START_MAX_M, None)


def check_access_reaches_route(access_end: Point | None, route_start: Point) -> Check:
    if access_end is None:
        return Check("access_reaches_route", True, 0.0, ACCESS_START_MAX_M, None)
    d = round(float(access_end.distance(route_start)), 2)
    return Check("access_reaches_route", d <= ACCESS_START_MAX_M, d, ACCESS_START_MAX_M, None)


def _first_point(geom) -> Point:
    first = geom.geoms[0] if hasattr(geom, "geoms") else geom
    return Point(first.coords[0])


def _transit_checks(name: str, geom, parcel: Polygon, zones: list[Polygon], cov_width: float,
                    *, erode: bool) -> list[Check]:
    a = check_inside_parcel(geom, parcel, cov_width, erode=erode)
    a.id = f"inside_parcel:{name}"
    b = check_outside_zones(geom, zones, cov_width)
    b.id = f"outside_zones:{name}"
    return [a, b]


def validate_plan(plan: CoveragePlan, parcel: Polygon, zones: list[Polygon],
                  cov_width: float) -> ValidationReport:
    """Hard checks on the route and on every transit geometry; soft access checks.

    The fence leg (gate -> eroded area) may run next to the fence (erode=False);
    the access and return paths must stay inside the eroded parcel (erode=True).
    """
    checks = [
        check_inside_parcel(plan.route, parcel, cov_width, erode=True),
        check_outside_zones(plan.route, zones, cov_width),
    ]
    if plan.access_leg is not None:
        checks += _transit_checks("access_leg", plan.access_leg, parcel, zones, cov_width, erode=False)
    if plan.access_path is not None:
        checks += _transit_checks("access_path", plan.access_path, parcel, zones, cov_width, erode=True)
    if plan.return_path is not None:
        checks += _transit_checks("return_path", plan.return_path, parcel, zones, cov_width, erode=True)
    entry = next((g for g in (plan.access_leg, plan.access_path) if g is not None), plan.route)
    checks.append(check_starts_at_access(_first_point(entry), plan.access_point))
    access_end = Point(plan.access_path.coords[-1]) if plan.access_path is not None else None
    checks.append(check_access_reaches_route(access_end, _first_point(plan.route)))
    warnings = [
        Warning("UNREACHED_AREA", p, {"area_ha": round(p.area / 1e4, 3)}) for p in plan.unreached
    ]
    report = ValidationReport(
        ok=all(c.ok for c in checks),
        checks=checks,
        fallbacks_applied=list(plan.fallbacks),
        warnings=warnings,
    )
    logger.info("plan validated", extra={"ok": report.ok,
                                         "failed": [c.id for c in checks if not c.ok]})
    return report
