import pytest
from shapely.geometry import MultiPolygon, Point, Polygon
from app.services.exclusion import (
    build_working_polygon, validate_access_point, ExclusionError,
    rasterize_blocked_cells,
)


def _square(x0, y0, x1, y1):
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def test_build_working_polygon_punches_buffered_hole():
    # Treat coords as metres (planar). Parcel 100x100, zone 40..60 square.
    parcel = _square(0, 0, 100, 100)
    zone = _square(40, 40, 60, 60)
    work = build_working_polygon(parcel, [zone], buffer_m=5.0)
    # The buffered hole (35..65) is removed from the interior.
    assert work.area < parcel.area
    assert not work.contains(Point(50, 50))          # centre of the no-go
    assert work.contains(Point(10, 10))              # far corner still drivable
    # Buffer applied: a point just outside the raw zone but inside the buffer is excluded.
    assert not work.contains(Point(37, 50))


def test_zone_covering_parcel_raises():
    parcel = _square(0, 0, 100, 100)
    covering = _square(-10, -10, 110, 110)
    with pytest.raises(ExclusionError):
        build_working_polygon(parcel, [covering], buffer_m=1.0)


def test_access_point_inside_zone_raises():
    parcel = _square(0, 0, 100, 100)
    zone = _square(40, 40, 60, 60)
    with pytest.raises(ExclusionError):
        validate_access_point(Point(50, 50), parcel, [zone], buffer_m=5.0)


def test_access_point_outside_parcel_raises():
    parcel = _square(0, 0, 100, 100)
    with pytest.raises(ExclusionError):
        validate_access_point(Point(200, 200), parcel, [], buffer_m=5.0)


def test_access_point_on_boundary_passes():
    parcel = _square(0, 0, 100, 100)
    validate_access_point(Point(0, 50), parcel, [], buffer_m=5.0)  # gate on perimeter, no raise


def test_access_point_valid_passes():
    parcel = _square(0, 0, 100, 100)
    zone = _square(40, 40, 60, 60)
    validate_access_point(Point(5, 5), parcel, [zone], buffer_m=5.0)  # no raise


def test_zone_splitting_parcel_yields_multipolygon():
    parcel = _square(0, 0, 100, 20)
    wall = _square(48, -5, 52, 25)  # vertical wall splitting left/right
    work = build_working_polygon(parcel, [wall], buffer_m=1.0)
    assert isinstance(work, MultiPolygon)
    assert len(work.geoms) == 2


def test_rasterize_blocked_cells_marks_covered_centres():
    # 10x10 grid, origin (0,0), 1.0 deg pixels (planar test). Block the 3..5 box.
    block = _square(3.0, 3.0, 5.0, 5.0)
    blocked = rasterize_blocked_cells(
        block, origin_lon=0.0, origin_lat=0.0, pixel_size_deg=1.0, cols=10, rows=10,
    )
    assert (4, 4) in blocked      # cell centre (4,4) is inside the box
    assert (0, 0) not in blocked  # far cell free
    assert (9, 9) not in blocked


def test_route_enters_zones_detects_crossing():
    from shapely.geometry import LineString
    from app.services.exclusion import route_enters_zones
    zone = _square(40, 40, 60, 60)
    crossing = LineString([(0, 50), (100, 50)])   # passes through the zone
    clear = LineString([(0, 10), (100, 10)])      # below the zone
    assert route_enters_zones(crossing, [zone]) is True
    assert route_enters_zones(clear, [zone]) is False
    assert route_enters_zones(crossing, []) is False
