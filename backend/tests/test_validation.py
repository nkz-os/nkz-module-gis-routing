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


def _plan(route, swaths, access_path=None, unreached=()):
    return CoveragePlan(pattern="boustrophedon", curve_type="dubins", headland_passes=1,
                        swaths=swaths, turns=[], route=route, working_area=RECT, unreached=list(unreached),
                        parcel_area_m2=RECT.area, access_point=GATE, access_path=access_path,
                        exit_point=Point(route.coords[-1]), exclusion_zones=[])


def test_validate_plan_ok_and_warnings():
    route = LineString([(10, 10), (190, 10), (190, 30), (10, 30)])
    plan = _plan(route, [Swath(0, "work", LineString([(10, 10), (190, 10)])), Swath(1, "work", LineString([(190, 30), (10, 30)]))],
                 access_path=LineString([(0, 50), (10, 10)]), unreached=[Polygon([(150, 40), (190, 40), (190, 90), (150, 90)])])
    rep = validate_plan(plan, RECT, [], 20.0)
    assert rep.ok
    assert [c.id for c in rep.checks] == ["inside_parcel", "outside_zones", "inside_parcel:access_path",
                                          "outside_zones:access_path", "starts_at_access"]
    assert rep.warnings[0].code == "UNREACHED_AREA" and rep.warnings[0].params["area_ha"] == pytest.approx(0.2)
    d = rep.to_dict(lambda x, y: (x, y))
    assert d["ok"] is True and d["warnings"][0]["geometry"]["type"] == "Polygon"


def test_validate_plan_fails_when_route_touches_zone():
    route = LineString([(10, 50), (190, 50)])
    plan = _plan(route, [Swath(0, "work", route)])
    rep = validate_plan(plan, RECT, [ZONE_CENTER], 4.0)
    assert not rep.ok and not [c for c in rep.checks if c.id == "outside_zones"][0].ok
