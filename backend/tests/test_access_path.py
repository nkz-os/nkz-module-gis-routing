import pytest
from shapely.geometry import LineString, Point, Polygon
from app.services.coverage.access import compute_access_path
from app.services.exclusion import build_working_polygon
from tests.fixtures_parcels import RECT, L_SHAPE, ZONE_CENTER, GATE


def test_straight_when_visible():
    path = compute_access_path(GATE, Point(20, 50), RECT)
    assert list(path.coords) == [(0.0, 50.0), (20.0, 50.0)]


def test_detours_around_zone():
    work = build_working_polygon(RECT, [ZONE_CENTER], 2.0)   # bloque 88..112 × 38..62
    path = compute_access_path(Point(50, 50), Point(150, 50), work)
    assert path is not None and len(path.coords) >= 3
    assert work.buffer(0.1).covers(path)
    assert path.length < 100 + 2 * 30


def test_detours_in_concave_parcel():
    # L_SHAPE: falta la esquina x∈[100,200], y∈[50,100]; de (150,25) a (50,75) no hay línea recta dentro
    path = compute_access_path(Point(150, 25), Point(50, 75), L_SHAPE)
    assert path is not None and L_SHAPE.buffer(0.1).covers(path)
    assert path.length < 160.0


def test_none_when_start_outside_area():
    assert compute_access_path(Point(-10, 50), Point(20, 50), RECT) is None


def test_none_when_unreachable():
    island = Polygon([(300, 300), (310, 300), (310, 310), (300, 310)])
    two = RECT.union(island)
    assert compute_access_path(Point(10, 10), Point(305, 305), two) is None


def test_simplify_m_must_be_below_clearance():
    with pytest.raises(ValueError):
        compute_access_path(GATE, Point(20, 50), RECT, simplify_m=0.5)
