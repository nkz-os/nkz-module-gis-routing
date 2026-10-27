import pytest
pytest.importorskip("fields2cover")
from shapely.geometry import Point
from app.services.coverage.f2c_engine import plan_coverage, CoverageConfig
from app.services.coverage.robot_model import RobotParams
from tests.fixtures_parcels import RECT, GATE, wgs84

ROBOT = RobotParams(width=2.0, cov_width=20.0, min_turning_radius=6.0, curve_type="dubins")


def _plan(**kw):
    cfg = CoverageConfig(pattern=kw.pop("pattern", "boustrophedon"), headland_passes=kw.pop("passes", 1), **kw)
    return plan_coverage(RECT, RECT, ROBOT, cfg, access_utm=GATE, wgs84_poly=wgs84(RECT))


def test_swaths_and_turns_are_split():
    p = _plan()
    work = [s for s in p.swaths if s.kind == "work"]
    heads = [s for s in p.swaths if s.kind == "headland"]
    assert len(work) >= 2 and len(heads) == 1
    assert len(p.turns) >= len(p.swaths) - 1
    assert [s.index for s in p.swaths] == list(range(len(p.swaths)))
    assert p.route.geom_type == "LineString" and p.route.length > 0


def test_headland_ring_sits_half_width_inside_fence():
    p = _plan(passes=2)
    heads = [s for s in p.swaths if s.kind == "headland"]
    assert len(heads) == 2
    outer = heads[-1].geometry           # el último es el exterior (k=0)
    assert RECT.exterior.distance(outer) == pytest.approx(10.0, abs=0.05)
    assert outer.is_closed


def test_route_is_oriented_to_access_and_access_path_exists():
    p = _plan()
    assert p.access_path is not None
    assert Point(p.access_path.coords[0]).distance(GATE) < 1e-6
    assert Point(p.access_path.coords[-1]).distance(Point(p.route.coords[0])) < 1e-6
    far = Point(200, 50)
    assert Point(p.route.coords[0]).distance(GATE) <= Point(p.route.coords[0]).distance(far)


def test_return_to_access_appends_final_turn():
    p = _plan(return_to_access=True)
    assert p.exit_point.distance(GATE) < 1e-6
    assert p.turns[-1].geometry.coords[-1] == (GATE.x, GATE.y)


def test_metrics_consistent():
    p = _plan()
    m = p.metrics(ROBOT.cov_width)
    assert m["worked_distance_m"] == pytest.approx(sum(s.geometry.length for s in p.swaths), abs=0.1)
    assert 0 < m["field_efficiency"] <= 1.0
    assert m["working_area_ha"] == pytest.approx(2.0, abs=0.01) and m["parcel_area_ha"] == pytest.approx(2.0, abs=0.01)
