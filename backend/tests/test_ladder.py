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
    pat = [f for f in plan.validation.fallbacks_applied if f.startswith("pattern:")]
    assert pat == ([] if plan.pattern == "boustrophedon" else [f"pattern:{plan.pattern}"])


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


# ---- deterministic ladder tests: plan_coverage replaced by hand-built plans ----
from shapely.geometry import LineString, MultiLineString  # noqa: E402
from app.services.coverage import ladder as ladder_mod  # noqa: E402
from app.services.coverage.plan import CoveragePlan, Swath, Turn  # noqa: E402

SW_A = LineString([(10, 10), (190, 10)])
SW_B = LineString([(190, 20), (10, 20)])
TURN_OK = LineString([(190, 10), (195, 15), (190, 20)])
TURN_BAD = LineString([(190, 10), (100, 50), (190, 20)])     # crosses ZONE_CENTER


def _fake_plan(cfg, robot, swaths=(SW_A, SW_B), turn=TURN_OK, access_path=None):
    coords = list(swaths[0].coords) + list(turn.coords)[1:] + list(swaths[1].coords)[1:]
    route = LineString(coords)
    return CoveragePlan(
        pattern=cfg.pattern, curve_type=robot.curve_type, headland_passes=cfg.headland_passes,
        swaths=[Swath(0, "work", swaths[0]), Swath(1, "work", swaths[1])],
        turns=[Turn(0, 0, 1, turn)], route=route, working_area=RECT, unreached=[],
        parcel_area_m2=RECT.area, access_point=None, access_path=access_path,
        exit_point=Point(route.coords[-1]), exclusion_zones=[])


def _patch(monkeypatch, builder):
    calls = []

    def fake(piece, parcel, robot, cfg, *, access_utm, wgs84_poly, swath_cache=None):
        calls.append((cfg.pattern, robot.curve_type, cfg.headland_passes))
        return builder(cfg, robot)

    monkeypatch.setattr(ladder_mod, "plan_coverage", fake)
    return calls


def test_step5_manual_turn_end_to_end(monkeypatch):
    calls = _patch(monkeypatch, lambda c, r: _fake_plan(c, r, turn=TURN_BAD))
    inp = LadderInput(RECT, [ZONE_CENTER], ROBOT, CoverageConfig("boustrophedon", headland_passes=1),
                      access_utm=None, wgs84_poly=wgs84(RECT))
    plan = plan_with_fallbacks(inp)
    assert len(calls) == 6                       # 1 pattern x 2 curves x 3 passes
    assert isinstance(plan.route, MultiLineString) and len(plan.route.geoms) == 2
    assert len([w for w in plan.validation.warnings if w.code == "MANUAL_TURN"]) == 1
    assert "manual_turns:1" in plan.validation.fallbacks_applied
    assert _hard_ok(plan)


def test_step5_swath_through_zone_raises(monkeypatch):
    through = LineString([(10, 50), (190, 50)])
    _patch(monkeypatch, lambda c, r: _fake_plan(c, r, swaths=(through, SW_B), turn=TURN_OK))
    inp = LadderInput(RECT, [ZONE_CENTER], ROBOT, CoverageConfig("boustrophedon", headland_passes=1),
                      access_utm=None, wgs84_poly=wgs84(RECT))
    with pytest.raises(ExclusionError) as e:
        plan_with_fallbacks(inp)
    assert e.value.code == "NO_DRIVABLE_AREA"


def test_curve_fallback_reeds_shepp(monkeypatch):
    calls = _patch(monkeypatch, lambda c, r: _fake_plan(
        c, r, turn=TURN_BAD if r.curve_type == "dubins" else TURN_OK))
    inp = LadderInput(RECT, [ZONE_CENTER], ROBOT, CoverageConfig("boustrophedon", headland_passes=2),
                      access_utm=None, wgs84_poly=wgs84(RECT))
    plan = plan_with_fallbacks(inp)
    assert plan.validation.fallbacks_applied == ["curve:reeds_shepp"]
    assert len(calls) == 4 and plan.curve_type == "reeds_shepp"


def _turn_by_pattern(lengths):
    shapes = {p: LineString([(190, 10), (190 + x, 15), (190, 20)]) for p, x in lengths.items()}
    return lambda c, r: _fake_plan(c, r, turn=shapes[c.pattern])


def test_auto_selects_shortest_non_working_pattern(monkeypatch):
    _patch(monkeypatch, _turn_by_pattern({"boustrophedon": 5, "snake": 2, "spiral": 7}))
    plan = plan_with_fallbacks(_inp(pattern="auto", access=None))
    assert plan.pattern == "snake" and "pattern:snake" in plan.validation.fallbacks_applied


def test_auto_tie_goes_to_boustrophedon(monkeypatch):
    _patch(monkeypatch, _turn_by_pattern({"boustrophedon": 5, "snake": 5, "spiral": 5}))
    plan = plan_with_fallbacks(_inp(pattern="auto", access=None))
    assert plan.pattern == "boustrophedon"
    assert not [f for f in plan.validation.fallbacks_applied if f.startswith("pattern:")]


def test_headland_widened_warning(monkeypatch):
    calls = _patch(monkeypatch, lambda c, r: _fake_plan(c, r))
    robot = RobotParams(width=2.0, cov_width=4.0, min_turning_radius=20.0, curve_type="dubins")
    plan = plan_with_fallbacks(_inp(access=None, robot=robot))
    used = calls[-1][2]
    assert used == 6
    w = [w for w in plan.validation.warnings if w.code == "HEADLAND_WIDENED"]
    assert len(w) == 1 and w[0].params == {"requested": 1, "applied": used}


def test_access_path_unavailable_warning(monkeypatch):
    _patch(monkeypatch, lambda c, r: _fake_plan(c, r, access_path=None))
    plan = plan_with_fallbacks(_inp(access=GATE))
    w = [w for w in plan.validation.warnings if w.code == "ACCESS_PATH_UNAVAILABLE"]
    assert len(w) == 1 and w[0].geometry.equals(GATE)


def test_headland_only_is_validated_single_attempt(monkeypatch):
    from app.services.coverage import ladder as lm
    real = lm.plan_coverage
    calls = []

    def spy(*a, **k):
        calls.append(a[3].pattern)
        return real(*a, **k)
    monkeypatch.setattr(lm, "plan_coverage", spy)
    plan = plan_with_fallbacks(_inp(pattern="headland-only", passes=2))
    assert calls == ["headland-only"]
    assert plan.swaths and all(s.kind == "headland" for s in plan.swaths)
    assert _hard_ok(plan) and plan.validation.ok
    dists = sorted(RECT.exterior.distance(s.geometry) for s in plan.swaths)
    assert dists == [pytest.approx(2.0, abs=0.05), pytest.approx(6.0, abs=0.05)]


def test_bowtie_zone_both_lobes_avoided():
    from app.services.parcel_constraints import _zone_polygons
    bowtie = Polygon([(60, 30), (140, 70), (140, 30), (60, 70)])
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [list(bowtie.exterior.coords)]}}]}
    zones = _zone_polygons(fc, entity_id="urn:ngsi-ld:AgriParcel:p1")
    plan = plan_with_fallbacks(_inp(zones=zones, passes=2))
    left = Polygon([(60, 30), (60, 70), (100, 50)])
    right = Polygon([(140, 30), (140, 70), (100, 50)])
    for lobe in (left, right):
        assert plan.route.intersection(lobe.buffer(ROBOT.cov_width / 2 - 0.1)).length == 0.0



def test_time_budget_stops_auto_after_first_ok(monkeypatch, caplog):
    import logging
    calls = _patch(monkeypatch, _turn_by_pattern({"boustrophedon": 5, "snake": 2, "spiral": 7}))
    ticks = iter(range(0, 10000, 100))
    monkeypatch.setattr(ladder_mod, "monotonic", lambda: next(ticks))
    with caplog.at_level(logging.INFO, logger="app.services.coverage.ladder"):
        plan = plan_with_fallbacks(_inp(pattern="auto", access=None), time_budget_s=50.0)
    assert [c[0] for c in calls] == ["boustrophedon"]
    assert plan.pattern == "boustrophedon" and plan.validation.fallbacks_applied[-1] == "time_budget"
    assert "time_budget" in plan.fallbacks
    assert len([r for r in caplog.records if "time budget" in r.getMessage()]) == 1


def test_time_budget_ignored_for_concrete_pattern(monkeypatch):
    calls = _patch(monkeypatch, lambda c, r: _fake_plan(c, r, turn=TURN_BAD if r.curve_type == "dubins" else TURN_OK))
    ticks = iter(range(0, 10000, 100))
    monkeypatch.setattr(ladder_mod, "monotonic", lambda: next(ticks))
    inp = LadderInput(RECT, [ZONE_CENTER], ROBOT, CoverageConfig("boustrophedon", headland_passes=2),
                      access_utm=None, wgs84_poly=wgs84(RECT))
    plan = plan_with_fallbacks(inp, time_budget_s=0.0)
    assert len(calls) == 4 and "time_budget" not in plan.validation.fallbacks_applied


def test_time_budget_not_applied_without_an_ok_plan(monkeypatch):
    calls = _patch(monkeypatch, lambda c, r: _fake_plan(c, r, turn=TURN_BAD))
    ticks = iter(range(0, 100000, 100))
    monkeypatch.setattr(ladder_mod, "monotonic", lambda: next(ticks))
    inp = LadderInput(RECT, [ZONE_CENTER], ROBOT, CoverageConfig("auto", headland_passes=1),
                      access_utm=None, wgs84_poly=wgs84(RECT))
    plan = plan_with_fallbacks(inp, time_budget_s=0.0)
    assert len(calls) == 18 and "time_budget" not in plan.validation.fallbacks_applied


def test_ladder_reuses_swaths_per_passes(monkeypatch):
    seen = []
    real = ladder_mod.plan_coverage

    def spy(*a, swath_cache=None, **k):
        seen.append(id(swath_cache))
        return real(*a, swath_cache=swath_cache, **k)
    monkeypatch.setattr(ladder_mod, "plan_coverage", spy)
    plan_with_fallbacks(_inp(pattern="auto", passes=2))
    assert len(seen) >= 3 and len(set(seen)) == 1 and seen[0] != id(None)
