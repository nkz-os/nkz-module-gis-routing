import pytest
pytest.importorskip("fields2cover")
from dataclasses import replace
from shapely.geometry import Point, Polygon
from app.services.coverage.ladder import plan_with_fallbacks, LadderInput
from app.services.coverage.f2c_engine import CoverageConfig
from app.services.coverage.robot_model import RobotParams
from app.services.exclusion import ExclusionError
from tests.fixtures_parcels import RECT, WITH_HOLE, ZONE_CENTER, ZONE_SPLIT, GATE, wgs84

ROBOT = RobotParams(width=2.0, cov_width=4.0, min_turning_radius=6.0, curve_type="dubins")


def _inp(parcel=RECT, zones=(), pattern="boustrophedon", passes=1, access=GATE, robot=ROBOT):
    return LadderInput(parcel_utm=parcel, zones_utm=list(zones), robot=robot,
                       cfg=CoverageConfig(pattern=pattern, headland_passes=passes),
                       access_utm=access, wgs84_poly=wgs84(parcel))


def _hard_ok(plan):
    return all(c.ok for c in plan.validation.checks if c.id in ("inside_parcel", "outside_zones"))


def test_headland_minimum_is_applied_and_reported():
    plan = plan_with_fallbacks(_inp())            # R=6, w=4 → min 2
    assert plan.headland_passes >= 2
    assert any(f.startswith("headland_passes:1->") for f in plan.validation.fallbacks_applied)
    assert _hard_ok(plan)


def test_open_parcel_is_valid_without_manual_turns():
    plan = plan_with_fallbacks(_inp(passes=2))
    assert plan.validation.ok and plan.route.geom_type == "LineString"
    assert not [w for w in plan.validation.warnings if w.code == "MANUAL_TURN"]


def test_central_zone_never_touched():
    plan = plan_with_fallbacks(_inp(zones=[ZONE_CENTER]))
    assert _hard_ok(plan)
    forbidden = ZONE_CENTER.buffer(ROBOT.cov_width / 2 - 0.1)
    assert plan.route.intersection(forbidden).length == 0.0


def test_ladder_split_parcel_routes_gate_piece():
    plan = plan_with_fallbacks(_inp(zones=[ZONE_SPLIT]))
    assert plan.working_area.covers(GATE)
    assert len(plan.unreached) == 1
    w = [w for w in plan.validation.warnings if w.code == "UNREACHED_AREA"]
    assert len(w) == 1 and w[0].params["area_ha"] == pytest.approx(0.95, abs=0.1)
    assert _hard_ok(plan)


def test_hole_is_respected():
    plan = plan_with_fallbacks(_inp(parcel=WITH_HOLE))
    hole = Polygon(WITH_HOLE.interiors[0])
    assert plan.route.intersection(hole.buffer(ROBOT.cov_width / 2 - 0.1)).length == 0.0


def test_auto_picks_a_pattern_and_reports_it():
    plan = plan_with_fallbacks(_inp(pattern="auto"))
    assert plan.pattern in ("boustrophedon", "snake", "spiral") and _hard_ok(plan)


# Turns bulge into the headland strip, <2 m from neighbouring swaths/turns: with the real
# 4 m implement a zone on one turn would also be within clearance of its neighbours, so the
# clearance used to isolate a single turn is 2 m.
CHECK_W = 2.0


def _real_plan():
    from app.services.coverage.f2c_engine import plan_coverage
    return plan_coverage(RECT.buffer(-ROBOT.cov_width / 2), RECT, ROBOT, CoverageConfig("boustrophedon", headland_passes=4),
                         access_utm=GATE, wgs84_poly=wgs84(RECT))


def _zone_on(geom):
    return Point(geom.interpolate(0.5, normalized=True)).buffer(0.6, cap_style="square")


def test_remove_violating_turns_makes_manual_turn():
    from shapely.geometry import MultiLineString
    from app.services.coverage.ladder import remove_violating_turns
    from app.services.coverage.validation import check_outside_zones
    plan = _real_plan()
    by = {s.index: s for s in plan.swaths}
    work = [t for t in plan.turns if by[t.from_swath].kind == by[t.to_swath].kind == "work"]
    turn = work[len(work) // 2]    # interior U-turn between work swaths
    # zone on the point of the turn farthest from every swath and other turn: only it is hit
    others = [sw.geometry for sw in plan.swaths] + [t.geometry for t in plan.turns if t is not turn]
    pts = [turn.geometry.interpolate(i / 50, normalized=True) for i in range(1, 50)]
    far = max(pts, key=lambda p: min(g.distance(p) for g in others))
    zone = far.buffer(0.6, cap_style="square")
    res, warns = remove_violating_turns(plan, RECT, [zone], CHECK_W)
    assert isinstance(res.route, MultiLineString) and len(res.route.geoms) == 2
    manual = [w for w in warns if w.code == "MANUAL_TURN"]
    assert len(manual) == 1
    assert manual[0].params == {"from_swath": turn.from_swath, "to_swath": turn.to_swath}
    assert list(manual[0].geometry.coords) == [by[turn.from_swath].geometry.coords[-1],
                                               by[turn.to_swath].geometry.coords[0]]
    assert "manual_turns:1" in res.fallbacks
    assert len(res.turns) == len(plan.turns) - 1
    for g in [t.geometry for t in res.turns] + [s.geometry for s in res.swaths]:
        assert check_outside_zones(g, [zone], CHECK_W).ok


def test_swath_violation_raises_no_drivable_area():
    from app.services.coverage.ladder import ensure_swaths_clear
    from app.services.routing.base import project_polygon_to_utm
    plan = _real_plan()
    zone = _zone_on(plan.swaths[0].geometry)
    with pytest.raises(ExclusionError) as e:
        ensure_swaths_clear(plan, RECT, [zone], 4.0, project_polygon_to_utm(wgs84(RECT))[3])
    assert e.value.code == "NO_DRIVABLE_AREA"
    assert e.value.params["geometry"]["type"] == "LineString"


def test_ladder_narrow_parcel_headland_only_or_error():
    narrow = Polygon([(0, 0), (200, 0), (200, 12), (0, 12)])   # 12 m de ancho, w=4, R=6 → min 2 cabeceras = 8 m por lado
    try:
        plan = plan_with_fallbacks(_inp(parcel=narrow, access=Point(0, 6)))
    except ExclusionError as e:
        assert e.code == "NO_DRIVABLE_AREA"
        return
    assert all(s.kind == "headland" for s in plan.swaths) or _hard_ok(plan)


def test_gate_in_zone_is_rejected_before_planning():
    from app.services.exclusion import validate_access_point
    with pytest.raises(ExclusionError) as e:
        validate_access_point(Point(100, 50), RECT, [ZONE_CENTER], ROBOT.cov_width / 2)
    assert e.value.code == "ACCESS_IN_ZONE"
