import math
from dataclasses import replace

import pytest
pytest.importorskip("fields2cover")
from shapely.geometry import Point, Polygon

from app.services.coverage import f2c_engine
from app.services.coverage.f2c_engine import CoverageConfig
from app.services.coverage.ladder import LadderInput, plan_with_fallbacks
from app.services.coverage.robot_model import RobotParams
from tests.fixtures_parcels import GATE, HOOK, RECT, _shift_project, wgs84

OWNER = RobotParams(width=3.0, cov_width=6.0, min_turning_radius=8.0, curve_type="dubins")
SMALL = RobotParams(width=2.0, cov_width=4.0, min_turning_radius=6.0, curve_type="dubins")
HOOK_GATE = Point(70, 0)


def _inp(parcel=HOOK, robot=OWNER, pattern="auto", access=HOOK_GATE, zones=(), **cfg):
    return LadderInput(parcel_utm=parcel, zones_utm=list(zones), robot=robot,
                       cfg=CoverageConfig(pattern=pattern, headland_passes=1, **cfg),
                       access_utm=access, wgs84_poly=wgs84(parcel))


def _manual(plan):
    return [w for w in plan.validation.warnings if w.code.startswith("MANUAL_TURN")]


def _hard_ok(plan):
    return all(c.ok for c in plan.validation.checks if c.id.split(":")[0] in ("inside_parcel", "outside_zones"))


@pytest.mark.parametrize("pattern", ["boustrophedon", "snake", "spiral"])
def test_convex_route_identical_to_single_cell(pattern):
    with_cells = plan_with_fallbacks(_inp(parcel=RECT, robot=SMALL, pattern=pattern, access=GATE))
    without = plan_with_fallbacks(_inp(parcel=RECT, robot=SMALL, pattern=pattern, access=GATE, cells=False))
    assert with_cells.cells == 1
    assert with_cells.as_api_dict(_shift_project, 4.0) == without.as_api_dict(_shift_project, 4.0)


def test_hook_old_path_had_manual_turns():
    assert _manual(plan_with_fallbacks(_inp(cells=False), time_budget_s=60))


def test_hook_has_no_manual_turns():
    plan = plan_with_fallbacks(_inp(), time_budget_s=60)
    assert not _manual(plan)
    assert _hard_ok(plan)
    assert plan.cells > 1
    assert f"cells:{plan.cells}" in plan.validation.fallbacks_applied


def test_explicit_snake_on_hook_reports_boustrophedon():
    plan = plan_with_fallbacks(_inp(pattern="snake"))
    assert plan.pattern == "boustrophedon"
    assert "pattern:boustrophedon" in plan.validation.fallbacks_applied


def test_cells_route_failure_falls_back_to_single_cell(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("route planner failed")
    monkeypatch.setattr(f2c_engine, "_cells_path", boom)
    plan = plan_with_fallbacks(_inp(), time_budget_s=60)
    assert plan.cells == 1
    assert _hard_ok(plan)


def test_fixed_heading_is_split_angle():
    plan = plan_with_fallbacks(_inp(pattern="boustrophedon", heading_deg=30.0))
    for s in plan.swaths:
        if s.kind != "work":
            continue
        (x0, y0), (x1, y1) = s.geometry.coords[0], s.geometry.coords[-1]
        az = math.degrees(math.atan2(x1 - x0, y1 - y0)) % 180
        assert az == pytest.approx(30.0, abs=0.5)


def test_concave_with_zone_keeps_zone_manual_turns():
    zone = Polygon([(200, 300), (230, 300), (230, 330), (200, 330)])
    plan = plan_with_fallbacks(_inp(zones=[zone]), time_budget_s=60)
    assert _hard_ok(plan)
    assert plan.route.intersection(zone.buffer(OWNER.cov_width / 2 - 0.1)).length == 0.0


def test_auto_cell_route_is_never_reported_as_snake_or_spiral():
    plan = plan_with_fallbacks(_inp(), time_budget_s=60)
    assert plan.cells > 1
    assert not [f for f in plan.validation.fallbacks_applied if f.startswith("pattern:")]


def test_strip_never_returns_rings_only_when_a_turn_fits():
    # Dubins needs 4 passes and leaves nothing inside; Reeds-Shepp fits: use it, not rings only.
    strip = Polygon([(0, 0), (200, 0), (200, 40), (0, 40)])
    plan = plan_with_fallbacks(_inp(parcel=strip, access=Point(0, 20)), time_budget_s=60)
    assert [s for s in plan.swaths if s.kind == "work"]
    assert plan.curve_type == "reeds_shepp"


def test_engine_error_while_sizing_the_headland_is_one_failed_rung(monkeypatch):
    real = f2c_engine._generate_swath_set

    def flaky(piece, w, passes, angle, decompose=True):
        if passes == 4:
            raise RuntimeError("engine hiccup")
        return real(piece, w, passes, angle, decompose)
    monkeypatch.setattr(f2c_engine, "_generate_swath_set", flaky)
    plan = plan_with_fallbacks(_inp(), time_budget_s=60)
    assert plan.headland_passes != 4 and _hard_ok(plan)


def test_convex_interior_is_never_decomposed(monkeypatch):
    import fields2cover as f2c

    class NoDecomp:
        def __init__(self):
            raise AssertionError("decomposition called on a convex interior")
    monkeypatch.setattr(f2c, "DECOMP_Boustrophedon", NoDecomp)
    plan = plan_with_fallbacks(_inp(parcel=RECT, robot=SMALL, access=GATE), time_budget_s=60)
    assert plan.cells == 1


def test_both_lobes_worked_when_the_headland_splits_the_interior():
    # Two 120 m squares joined by a 36 m neck: a 4-pass (24 m) headland cuts the interior in two.
    dumbbell = Polygon([(0, 0), (120, 0), (120, 42), (180, 42), (180, 0), (300, 0), (300, 120),
                        (180, 120), (180, 78), (120, 78), (120, 120), (0, 120)])
    plan = plan_with_fallbacks(_inp(parcel=dumbbell, access=Point(0, 60)), time_budget_s=60)
    xs = [s.geometry.centroid.x for s in plan.swaths if s.kind == "work"]
    assert any(x < 120 for x in xs) and any(x > 180 for x in xs)
    assert _hard_ok(plan)
