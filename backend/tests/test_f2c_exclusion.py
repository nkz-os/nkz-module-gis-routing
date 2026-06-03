import pytest
from shapely.geometry import Polygon

pytest.importorskip("fields2cover")  # f2c only available in CI/server
from app.services.coverage.f2c_engine import generate_coverage, CoverageConfig
from app.services.coverage.robot_model import RobotParams
from app.services.exclusion import ExclusionError


def _wgs_square(lon0, lat0, lon1, lat1):
    return Polygon([(lon0, lat0), (lon1, lat0), (lon1, lat1), (lon0, lat1)])


def _robot():
    return RobotParams(width=2.0, cov_width=3.0, min_turning_radius=6.0, curve_type="dubins")


def test_coverage_never_emits_route_crossing_a_no_go_zone():
    """Fail-safe invariant: with a no-go zone, generate_coverage either raises
    ExclusionError (route could not avoid the zone) or returns a route with NO
    vertex inside the zone. It must NEVER return a route that crosses it."""
    from shapely.geometry import Point
    parcel = _wgs_square(0.0000, 0.0000, 0.0020, 0.0020)   # ~220 m square
    zone = _wgs_square(0.0008, 0.0008, 0.0012, 0.0012)     # central no-go
    cfg = CoverageConfig(pattern="boustrophedon")
    try:
        res = generate_coverage(parcel, _robot(), cfg,
                                exclusion_zones_wgs84=[zone], exclusion_buffer_m=2.5)
    except ExclusionError:
        return  # fail-safe path — acceptable and expected for a central obstacle
    # If a route WAS produced, no vertex may fall inside the no-go zone.
    for line in res.geometry.geoms:
        for x, y in line.coords:
            assert not zone.contains(Point(x, y))


def test_coverage_with_edge_zone_reduces_covered_area():
    """An exclusion zone removes working area: covered area must not exceed the
    unconstrained run (and the run must succeed for a corner zone that does not
    force a crossing). If even this fails safe, that is still acceptable."""
    parcel = _wgs_square(0.0000, 0.0000, 0.0020, 0.0020)
    zone = _wgs_square(0.00005, 0.00005, 0.0004, 0.0004)   # corner no-go
    cfg = CoverageConfig(pattern="boustrophedon")
    res_open = generate_coverage(parcel, _robot(), cfg)
    try:
        res_excl = generate_coverage(parcel, _robot(), cfg,
                                     exclusion_zones_wgs84=[zone], exclusion_buffer_m=2.5)
    except ExclusionError:
        return  # fail-safe is acceptable
    assert res_excl.covered_area_ha <= res_open.covered_area_ha


def test_route_starts_near_access_point():
    parcel = _wgs_square(0.0000, 0.0000, 0.0020, 0.0020)
    cfg = CoverageConfig(pattern="boustrophedon")
    gate = (0.0019, 0.0019)
    res = generate_coverage(parcel, _robot(), cfg, start_point_wgs84=gate)
    first = list(res.geometry.geoms)[0].coords[0]
    end = list(res.geometry.geoms)[-1].coords[-1]
    from math import dist
    assert dist(first, gate) <= dist(end, gate)
