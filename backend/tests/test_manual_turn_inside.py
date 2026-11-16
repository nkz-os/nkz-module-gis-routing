"""Manual turns are drawn inside the parcel; without a way through they get their own warning."""
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, MultiPolygon, Point, box

from app.services.coverage.access import CLEARANCE_M, InsidePaths, compute_access_path

# U-shaped parcel: two arms joined at the bottom; the notch between them is not ours.
U = box(0, 0, 100, 100).difference(box(30, 30, 70, 100))
A, B = Point(15, 90), Point(85, 90)          # top of the left arm, top of the right arm


def test_path_goes_around_the_notch():
    path = InsidePaths(U).path(A, B)
    assert path is not None
    assert U.buffer(CLEARANCE_M).covers(path)
    assert path.length > A.distance(B)
    assert Point(path.coords[0]).equals(A) and Point(path.coords[-1]).equals(B)


def test_straight_when_it_fits():
    a, b = Point(5, 50), Point(25, 95)
    assert list(InsidePaths(U).path(a, b).coords) == [(5, 50), (25, 95)]


def test_none_when_an_end_is_outside():
    assert InsidePaths(U).path(A, Point(50, 90)) is None


def test_one_graph_many_queries_match_single_calls():
    paths = InsidePaths(U)
    for a, b in [(A, B), (Point(5, 5), Point(95, 95)), (Point(85, 40), Point(15, 40))]:
        one = compute_access_path(a, b, U)
        assert paths.path(a, b).length == pytest.approx(one.length)


# --- ladder: the warnings themselves (needs the route engine module) ----------------------

def _plan(a: Point, b: Point):
    from app.services.coverage.plan import Swath
    return SimpleNamespace(swaths=[
        Swath(0, "work", LineString([(a.x, a.y - 20), (a.x, a.y)])),
        Swath(1, "work", LineString([(b.x, b.y), (b.x, b.y - 20)])),
    ])


def _turn():
    from app.services.coverage.plan import Turn
    return Turn(0, 0, 1, LineString([(15, 90), (85, 90)]))


def test_manual_turn_follows_the_parcel():
    pytest.importorskip("fields2cover")
    from app.services.coverage.f2c_engine import transit_parts
    from app.services.coverage.ladder import _manual_warnings
    from app.services.coverage.validation import check_inside_parcel
    w = 4.0
    transit = [InsidePaths(p) for p in transit_parts(U, w)]
    [warn] = _manual_warnings(_plan(A, B), [_turn()], transit)
    assert warn.code == "MANUAL_TURN"
    assert warn.params == {"from_swath": 0, "to_swath": 1}
    assert check_inside_parcel(warn.geometry, U, w).ok
    assert warn.geometry.length > A.distance(B)


def test_manual_turn_without_way_through_has_its_own_warning():
    pytest.importorskip("fields2cover")
    from app.services.coverage.f2c_engine import transit_parts
    from app.services.coverage.ladder import _manual_warnings
    w = 4.0
    two = MultiPolygon([box(0, 0, 30, 100), box(70, 0, 100, 100)])   # the arms, not joined
    transit = [InsidePaths(p) for p in transit_parts(two, w)]
    [warn] = _manual_warnings(_plan(A, B), [_turn()], transit)
    assert warn.code == "MANUAL_TURN_OUTSIDE"
    assert warn.params == {"from_swath": 0, "to_swath": 1}
    assert list(warn.geometry.coords) == [(15, 90), (85, 90)]


def test_without_piece_the_warning_is_the_straight_manual_turn():
    pytest.importorskip("fields2cover")
    from app.services.coverage.ladder import _manual_warnings
    [warn] = _manual_warnings(_plan(A, B), [_turn()], None)
    assert warn.code == "MANUAL_TURN"
    assert list(warn.geometry.coords) == [(15, 90), (85, 90)]

