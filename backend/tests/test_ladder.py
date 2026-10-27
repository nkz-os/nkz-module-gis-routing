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


def test_manual_turns_when_turn_radius_cannot_fit():
    # Radio enorme frente a una parcela pequeña: los giros no caben ni con 3+2 cabeceras → giros manuales, nunca recorte.
    small = Polygon([(0, 0), (60, 0), (60, 40), (0, 40)])
    robot = RobotParams(width=2.0, cov_width=4.0, min_turning_radius=25.0, curve_type="dubins")
    try:
        plan = plan_with_fallbacks(_inp(parcel=small, access=Point(0, 20), robot=robot))
    except ExclusionError as e:
        assert e.code == "NO_DRIVABLE_AREA"
        return
    manual = [w for w in plan.validation.warnings if w.code == "MANUAL_TURN"]
    assert manual and plan.route.geom_type == "MultiLineString"
    assert any(f.startswith("manual_turns:") for f in plan.validation.fallbacks_applied)
    assert _hard_ok(plan)
    for s in plan.swaths:
        assert small.buffer(-ROBOT.cov_width / 2 + 0.5).covers(s.geometry)


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
