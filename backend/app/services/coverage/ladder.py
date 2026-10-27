"""Fallback ladder: guarantees the route never violates the hard geometric checks.

Order of alternatives per attempt: pattern -> curve -> headland passes. When no
attempt passes, the turns that still violate are removed (manual turns); curves
are never clipped.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from time import monotonic

from shapely.geometry import LineString, MultiLineString, Point, Polygon, mapping
from shapely.ops import transform

from app.services.coverage.f2c_engine import CoverageConfig, plan_coverage
from app.services.coverage.plan import CoveragePlan, Swath, Turn
from app.services.coverage.robot_model import RobotParams
from app.services.coverage.validation import (
    ValidationReport, Warning, check_inside_parcel, check_outside_zones,
    min_headland_passes, split_working_area, validate_plan,
)
from app.services.exclusion import ExclusionError, build_working_polygon
from app.services.routing.base import project_polygon_to_utm

logger = logging.getLogger(__name__)

AUTO_PATTERN_ORDER = ("boustrophedon", "snake", "spiral")
HEADLAND_EXTRA_MAX = 2
HEADLAND_ONLY = "headland-only"
_HARD_IDS = ("inside_parcel", "outside_zones")


@dataclass
class LadderInput:
    parcel_utm: Polygon
    zones_utm: list[Polygon]
    robot: RobotParams
    cfg: CoverageConfig
    access_utm: Point | None
    wgs84_poly: Polygon


@dataclass
class _Attempt:
    plan: CoveragePlan
    report: ValidationReport
    pattern: str
    passes: int

    @property
    def hard_ok(self) -> bool:
        return all(c.ok for c in self.report.checks if c.id in _HARD_IDS)

    @property
    def hard_score(self) -> float:
        return sum(c.value for c in self.report.checks if c.id in _HARD_IDS)


def _to_lists(obj):
    if isinstance(obj, (list, tuple)):
        return [_to_lists(i) for i in obj]
    return obj


def _turn_violates(turn: Turn, parcel: Polygon, zones: list[Polygon], w: float) -> bool:
    return (not check_inside_parcel(turn.geometry, parcel, w).ok
            or not check_outside_zones(turn.geometry, zones, w).ok)


def remove_violating_turns(plan: CoveragePlan, parcel_utm: Polygon, zones_utm: list[Polygon],
                           cov_width: float) -> tuple[CoveragePlan, list[Warning]]:
    """Drop violating turns (manual turns); route becomes the continuous runs left.

    Returns the new plan and one MANUAL_TURN warning per removed turn.
    """
    kept, removed = [], []
    for t in plan.turns:
        (removed if _turn_violates(t, parcel_utm, zones_utm, cov_width) else kept).append(t)
    if not removed:
        return plan, []
    route = _rebuild_route(plan.swaths, kept)
    fallbacks = list(plan.fallbacks) + [f"manual_turns:{len(removed)}"]
    return replace(plan, turns=kept, route=route, fallbacks=fallbacks), _manual_warnings(plan, removed)


def ensure_swaths_clear(plan: CoveragePlan, parcel_utm: Polygon, zones_utm: list[Polygon],
                        cov_width: float, to_wgs84) -> None:
    """Raise NO_DRIVABLE_AREA with the first swath that violates a hard check."""
    for s in plan.swaths:
        if (not check_inside_parcel(s.geometry, parcel_utm, cov_width).ok
                or not check_outside_zones(s.geometry, zones_utm, cov_width).ok):
            gj = mapping(transform(to_wgs84, s.geometry))
            raise ExclusionError(
                "a swath cannot avoid a no-go zone or the parcel boundary",
                code="NO_DRIVABLE_AREA",
                params={"geometry": {"type": gj["type"], "coordinates": _to_lists(gj["coordinates"])}})


def _rebuild_route(swaths: list[Swath], turns: list[Turn]):
    by_swath = {s.index: s for s in swaths}
    turn_from = {t.from_swath: t for t in turns}
    to_swath = {t.to_swath for t in turns}
    runs: list[list] = []
    for s in swaths:
        if s.index in to_swath and runs:
            pass
        else:
            runs.append([])
        runs[-1].append(s.geometry)
        t = turn_from.get(s.index)
        if t is not None and t.to_swath in by_swath:
            runs[-1].append(t.geometry)
    lines = []
    for run in runs:
        coords = []
        for g in run:
            coords.extend(g.coords if not coords else list(g.coords)[1:])
        lines.append(LineString(coords))
    return lines[0] if len(lines) == 1 else MultiLineString(lines)


def _manual_warnings(plan: CoveragePlan, removed: list[Turn]) -> list[Warning]:
    by_swath = {s.index: s for s in plan.swaths}
    out = []
    for t in removed:
        a = Point(by_swath[t.from_swath].geometry.coords[-1])
        b = Point(by_swath[t.to_swath].geometry.coords[0])
        out.append(Warning("MANUAL_TURN", LineString([a, b]),
                           {"from_swath": t.from_swath, "to_swath": t.to_swath}))
    return out


def _attempt_fallbacks(inp: LadderInput, pattern: str, curve: str, passes: int) -> list[str]:
    fb = []
    if passes != inp.cfg.headland_passes:
        fb.append(f"headland_passes:{inp.cfg.headland_passes}->{passes}")
    if curve != inp.robot.curve_type:
        fb.append(f"curve:{curve}")
    if inp.cfg.pattern == "auto" and pattern != AUTO_PATTERN_ORDER[0]:
        fb.append(f"pattern:{pattern}")
    return fb


def _extra_warnings(inp: LadderInput, plan: CoveragePlan, applied: int) -> list[Warning]:
    out = []
    if applied > 3:
        out.append(Warning("HEADLAND_WIDENED", None,
                           {"requested": inp.cfg.headland_passes, "applied": applied}))
    if inp.access_utm is not None and plan.access_path is None:
        out.append(Warning("ACCESS_PATH_UNAVAILABLE", inp.access_utm, {}))
    return out


def _over_budget(inp: LadderInput, budget_s: float | None, first_ok: dict, start: float) -> bool:
    """auto only: stop once a hard-ok plan exists and the budget is spent."""
    return (inp.cfg.pattern == "auto" and budget_s is not None and bool(first_ok)
            and monotonic() - start > budget_s)


def plan_with_fallbacks(inp: LadderInput, time_budget_s: float | None = None) -> CoveragePlan:
    """Plan with the fallback ladder.

    time_budget_s applies to pattern "auto" only: once a hard-ok plan exists and
    the budget is spent, no further attempts run and "time_budget" is reported.
    """
    start = monotonic()
    w = inp.robot.cov_width
    work = build_working_polygon(inp.parcel_utm, inp.zones_utm, w / 2)
    piece, unreached = split_working_area(work, inp.access_utm)
    if inp.cfg.pattern == HEADLAND_ONLY:
        # Rings only: no interior turns, so no curve or headland alternatives.
        passes0, extra = max(inp.cfg.headland_passes, 1), 0
        patterns, curves = (HEADLAND_ONLY,), (inp.robot.curve_type,)
    else:
        passes0 = max(inp.cfg.headland_passes, min_headland_passes(inp.robot.min_turning_radius, w))
        extra = HEADLAND_EXTRA_MAX
        patterns = AUTO_PATTERN_ORDER if inp.cfg.pattern == "auto" else (inp.cfg.pattern,)
        curves = (inp.robot.curve_type,) + (("reeds_shepp",) if inp.robot.curve_type == "dubins" else ())

    attempts: list[_Attempt] = []
    first_ok: dict[str, _Attempt] = {}
    last_error: ExclusionError | None = None
    swath_cache: dict = {}
    budget_hit = False
    for pattern in patterns:
        done = False
        for curve in curves:
            for passes in range(passes0, passes0 + extra + 1):
                if _over_budget(inp, time_budget_s, first_ok, start):
                    budget_hit = True
                    logger.warning("ladder time budget spent: elapsed=%.1fs budget=%.1fs "
                                   "next_pattern=%s ok_patterns=%s", monotonic() - start,
                                   time_budget_s, pattern, sorted(first_ok))
                    break
                try:
                    plan = plan_coverage(
                        piece, inp.parcel_utm, replace(inp.robot, curve_type=curve),
                        replace(inp.cfg, pattern=pattern, headland_passes=passes),
                        access_utm=inp.access_utm, wgs84_poly=inp.wgs84_poly,
                        swath_cache=swath_cache)
                except ExclusionError as e:
                    logger.info("ladder attempt pattern=%s curve=%s passes=%s raised=%s",
                                pattern, curve, passes, e.code)
                    last_error = e
                    continue
                plan.unreached = list(unreached)
                plan.exclusion_zones = list(inp.zones_utm)
                plan.fallbacks = _attempt_fallbacks(inp, pattern, curve, passes)
                att = _Attempt(plan, validate_plan(plan, inp.parcel_utm, inp.zones_utm, w), pattern, passes)
                attempts.append(att)
                logger.info("ladder attempt pattern=%s curve=%s passes=%s hard_ok=%s",
                            pattern, curve, passes, att.hard_ok)
                if att.hard_ok:
                    first_ok[pattern] = att
                    done = True
                    break
            if done or budget_hit:
                break
        if budget_hit or (done and inp.cfg.pattern != "auto"):
            break

    if first_ok:
        best = min(
            first_ok.values(),
            key=lambda a: (a.plan.metrics(w)["non_working_distance_m"],
                           AUTO_PATTERN_ORDER.index(a.pattern) if a.pattern in AUTO_PATTERN_ORDER else 0))
        if budget_hit:
            best.plan.fallbacks.append("time_budget")
            best.report.fallbacks_applied.append("time_budget")
        return _finish(inp, best.plan, best.report, best.passes, [])

    if not attempts:
        if last_error is None:
            raise RuntimeError("ladder produced no attempt and no error")
        raise last_error
    worst = min(attempts, key=lambda a: a.hard_score)
    fixed, manual = remove_violating_turns(worst.plan, inp.parcel_utm, inp.zones_utm, w)
    report = validate_plan(fixed, inp.parcel_utm, inp.zones_utm, w)
    _, _, _, to_wgs84 = project_polygon_to_utm(inp.wgs84_poly)
    ensure_swaths_clear(fixed, inp.parcel_utm, inp.zones_utm, w, to_wgs84)
    for c in report.checks:
        if c.id in _HARD_IDS and not c.ok:
            gj = mapping(transform(to_wgs84, c.geometry)) if c.geometry is not None else None
            raise ExclusionError(
                "route cannot be made to respect the parcel and the no-go zones",
                code="NO_DRIVABLE_AREA",
                params={"geometry": None if gj is None else
                        {"type": gj["type"], "coordinates": _to_lists(gj["coordinates"])}})
    return _finish(inp, fixed, report, worst.passes, manual)


def _finish(inp: LadderInput, plan: CoveragePlan, report: ValidationReport,
            applied: int, manual: list[Warning]) -> CoveragePlan:
    report.warnings.extend(manual)
    report.warnings.extend(_extra_warnings(inp, plan, applied))
    plan.validation = report
    logger.info("ladder result pattern=%s fallbacks=%s ok=%s",
                plan.pattern, report.fallbacks_applied, report.ok)
    return plan
