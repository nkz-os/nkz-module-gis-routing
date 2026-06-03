from shapely.geometry import Polygon, Point
from app.services.exclusion import (
    build_working_polygon, validate_access_point, ExclusionError,
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
