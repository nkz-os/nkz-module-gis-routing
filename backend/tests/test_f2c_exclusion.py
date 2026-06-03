import pytest
from shapely.geometry import Polygon

pytest.importorskip("fields2cover")  # f2c only available in CI/server
from app.services.coverage.f2c_engine import generate_coverage, CoverageConfig
from app.services.coverage.robot_model import RobotParams


def _wgs_square(lon0, lat0, lon1, lat1):
    return Polygon([(lon0, lat0), (lon1, lat0), (lon1, lat1), (lon0, lat1)])


def _robot():
    return RobotParams(width=2.0, cov_width=3.0, min_turning_radius=6.0, curve_type="dubins")


def test_coverage_excludes_zone_from_route():
    parcel = _wgs_square(0.0000, 0.0000, 0.0020, 0.0020)   # ~220 m square
    zone = _wgs_square(0.0008, 0.0008, 0.0012, 0.0012)     # central no-go
    cfg = CoverageConfig(pattern="boustrophedon")
    res_open = generate_coverage(parcel, _robot(), cfg)
    res_excl = generate_coverage(parcel, _robot(), cfg,
                                 exclusion_zones_wgs84=[zone], exclusion_buffer_m=2.5)
    assert res_excl.covered_area_ha < res_open.covered_area_ha
    from shapely.geometry import Point
    for line in res_excl.geometry.geoms:
        for x, y in line.coords:
            assert not zone.contains(Point(x, y))


def test_route_starts_near_access_point():
    parcel = _wgs_square(0.0000, 0.0000, 0.0020, 0.0020)
    cfg = CoverageConfig(pattern="boustrophedon")
    gate = (0.0019, 0.0019)
    res = generate_coverage(parcel, _robot(), cfg, start_point_wgs84=gate)
    first = list(res.geometry.geoms)[0].coords[0]
    end = list(res.geometry.geoms)[-1].coords[-1]
    from math import dist
    assert dist(first, gate) <= dist(end, gate)
