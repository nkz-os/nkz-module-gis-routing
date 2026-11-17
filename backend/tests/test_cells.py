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
