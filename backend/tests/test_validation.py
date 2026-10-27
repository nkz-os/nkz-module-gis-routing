import pytest
from shapely.geometry import LineString, Point, Polygon, MultiPolygon
from app.services.coverage.validation import (
    min_headland_passes, split_working_area, check_inside_parcel, check_outside_zones,
    check_starts_at_access, validate_plan, TOL_INSIDE_M)
from app.services.coverage.plan import CoveragePlan, Swath, Turn
from app.services.exclusion import ExclusionError, build_working_polygon
from tests.fixtures_parcels import RECT, WITH_HOLE, ZONE_CENTER, ZONE_SPLIT, GATE


@pytest.mark.parametrize("r,w,expected", [(6.0, 20.0, 1), (6.0, 3.0, 3), (10.0, 6.0, 3), (0.5, 20.0, 1)])
def test_min_headland_passes(r, w, expected):
    assert min_headland_passes(r, w) == expected


def test_split_prefers_gate_piece_and_reports_rest():
    work = build_working_polygon(RECT, [ZONE_SPLIT], 1.5)
    piece, rest = split_working_area(work, GATE)
    assert piece.covers(GATE) and len(rest) == 1
    assert rest[0].area > piece.area * 0.8   # la pieza oriental, no descartada en silencio


def test_split_without_gate_takes_largest():
    piece, rest = split_working_area(MultiPolygon([Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
                                                   Polygon([(20, 0), (50, 0), (50, 10), (20, 10)])]), None)
    assert piece.area == 300 and len(rest) == 1


def test_split_gate_in_no_piece_is_no_drivable_area():
    work = build_working_polygon(RECT, [ZONE_SPLIT], 1.5)
    with pytest.raises(ExclusionError) as e:
        split_working_area(work, Point(100, 50))
    assert e.value.code == "NO_DRIVABLE_AREA" and e.value.params["point"]["coordinates"] == [100.0, 50.0]


def test_inside_check_accepts_route_half_width_from_fence():
    route = LineString([(10, 10), (190, 10)])          # a 10 m del borde sur con w=20 → justo en el límite
    assert check_inside_parcel(route, RECT, 20.0).ok


def test_inside_check_rejects_route_too_close_to_fence():
    route = LineString([(10, 5), (190, 5)])
    c = check_inside_parcel(route, RECT, 20.0)
    assert not c.ok and c.value > 4.0 and c.geometry is not None


def test_inside_check_rejects_route_through_hole():
    route = LineString([(10, 50), (190, 50)])          # cruza el agujero central de WITH_HOLE
    assert not check_inside_parcel(route, WITH_HOLE, 4.0).ok


def test_access_path_check_uses_unbuffered_parcel():
    path = LineString([(0, 50), (10, 50)])             # arranca en la valla
    assert not check_inside_parcel(path, RECT, 4.0).ok
    assert check_inside_parcel(path, RECT, 4.0, erode=False).ok


def test_zone_check_margin():
    w = 4.0
    ok_line = LineString([(10, 10), (10, 90)])                      # lejos de la zona (x∈[90,110])
    assert check_outside_zones(ok_line, [ZONE_CENTER], w).ok
    grazing = LineString([(100, 0), (100, 100)])                   # cruza la zona central
    c = check_outside_zones(grazing, [ZONE_CENTER], w)
    assert not c.ok and c.value >= 20.0 and c.geometry is not None
    x = 90 - w / 2 + 0.05                                            # a w/2−0.05 del borde oeste de la zona: dentro de la tolerancia 0,1
    edge = LineString([(x, 0), (x, 100)])
    assert check_outside_zones(edge, [ZONE_CENTER], w).ok


def test_starts_at_access():
    assert check_starts_at_access(Point(0.5, 50), GATE).ok
    assert not check_starts_at_access(Point(5, 50), GATE).ok
    assert check_starts_at_access(Point(5, 50), None).ok


def _plan(route, swaths, access_path=None, unreached=(), access_leg=None, return_path=None):
    return CoveragePlan(pattern="boustrophedon", curve_type="dubins", headland_passes=1,
                        swaths=swaths, turns=[], route=route, working_area=RECT, unreached=list(unreached),
                        parcel_area_m2=RECT.area, access_point=GATE, access_path=access_path,
                        exit_point=Point(route.coords[-1]), exclusion_zones=[],
                        access_leg=access_leg, return_path=return_path)


ROUTE = LineString([(10, 10), (190, 10), (190, 30), (10, 30)])
SWATHS = [Swath(0, "work", LineString([(10, 10), (190, 10)])), Swath(1, "work", LineString([(190, 30), (10, 30)]))]
LEG = LineString([(0, 50), (10, 50)])               # fence gate -> eroded area (w=20: 9.5 m in)
PATH = LineString([(10, 50), (10, 10)])             # eroded area -> route start


def _ids(rep):
    return [c.id for c in rep.checks]


def _check(rep, cid):
    return [c for c in rep.checks if c.id == cid][0]


def test_validate_plan_ok_and_warnings():
    plan = _plan(ROUTE, SWATHS, access_path=PATH, access_leg=LEG,
                 unreached=[Polygon([(150, 40), (190, 40), (190, 90), (150, 90)])])
    rep = validate_plan(plan, RECT, [], 20.0)
    assert rep.ok
    assert _ids(rep) == ["inside_parcel", "outside_zones", "inside_parcel:access_leg", "outside_zones:access_leg",
                         "inside_parcel:access_path", "outside_zones:access_path", "starts_at_access",
                         "access_reaches_route"]
    assert rep.warnings[0].code == "UNREACHED_AREA" and rep.warnings[0].params["area_ha"] == pytest.approx(0.2)
    d = rep.to_dict(lambda x, y: (x, y))
    assert d["ok"] is True and d["warnings"][0]["geometry"]["type"] == "Polygon"


def test_access_path_is_checked_against_eroded_parcel():
    hugging = LineString([(10, 50), (3, 50), (3, 10), (10, 10)])   # 3 m from the fence with w=20
    rep = validate_plan(_plan(ROUTE, SWATHS, access_path=hugging, access_leg=LEG), RECT, [], 20.0)
    c = _check(rep, "inside_parcel:access_path")
    assert not c.ok and c.value == pytest.approx(6.5, abs=0.05)
    assert _check(rep, "inside_parcel:access_leg").ok


def test_starts_at_access_measures_gate_to_leg_start():
    rep = validate_plan(_plan(ROUTE, SWATHS, access_path=PATH, access_leg=LineString([(5, 50), (10, 50)])),
                        RECT, [], 20.0)
    c = _check(rep, "starts_at_access")
    assert not c.ok and c.value == pytest.approx(5.0)


def test_access_reaches_route_measures_path_end_to_route_start():
    short = LineString([(10, 50), (10, 15)])
    rep = validate_plan(_plan(ROUTE, SWATHS, access_path=short, access_leg=LEG), RECT, [], 20.0)
    c = _check(rep, "access_reaches_route")
    assert not c.ok and c.value == pytest.approx(5.0) and c.limit == 1.0
    assert _check(rep, "starts_at_access").ok


def test_return_path_checks_are_eroded():
    back = LineString([(10, 30), (10, 50)])
    rep = validate_plan(_plan(ROUTE, SWATHS, access_path=PATH, access_leg=LEG, return_path=back), RECT, [], 20.0)
    assert {"inside_parcel:return_path", "outside_zones:return_path"} <= set(_ids(rep))
    assert rep.ok
    bad = LineString([(10, 30), (2, 30), (2, 50)])
    rep2 = validate_plan(_plan(ROUTE, SWATHS, access_path=PATH, access_leg=LEG, return_path=bad), RECT, [], 20.0)
    assert not _check(rep2, "inside_parcel:return_path").ok


def test_leg_through_zone_fails_outside_zones():
    zone = Polygon([(4, 45), (6, 45), (6, 55), (4, 55)])
    rep = validate_plan(_plan(ROUTE, SWATHS, access_path=PATH, access_leg=LEG), RECT, [zone], 4.0)
    assert not _check(rep, "outside_zones:access_leg").ok


def test_validate_plan_fails_when_route_touches_zone():
    route = LineString([(10, 50), (190, 50)])
    plan = _plan(route, [Swath(0, "work", route)])
    rep = validate_plan(plan, RECT, [ZONE_CENTER], 4.0)
    assert not rep.ok and not [c for c in rep.checks if c.id == "outside_zones"][0].ok
