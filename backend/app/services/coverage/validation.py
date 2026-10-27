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


def split_working_area(work: BaseGeometry, access: Point | None) -> tuple[Polygon, list[Polygon]]:
    if isinstance(work, Polygon):
        return work, []
    pieces = sorted(work.geoms, key=lambda g: g.area, reverse=True)
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


def _first_point(geom) -> Point:
    first = geom.geoms[0] if hasattr(geom, "geoms") else geom
    return Point(first.coords[0])


def validate_plan(plan: CoveragePlan, parcel: Polygon, zones: list[Polygon],
                  cov_width: float) -> ValidationReport:
    checks = [
        check_inside_parcel(plan.route, parcel, cov_width, erode=True),
        check_outside_zones(plan.route, zones, cov_width),
    ]
    if plan.access_path is not None:
        a = check_inside_parcel(plan.access_path, parcel, cov_width, erode=False)
        a.id = "inside_parcel:access_path"
        b = check_outside_zones(plan.access_path, zones, cov_width)
        b.id = "outside_zones:access_path"
        checks += [a, b]
    start = _first_point(plan.access_path if plan.access_path is not None else plan.route)
    checks.append(check_starts_at_access(start, plan.access_point))
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
