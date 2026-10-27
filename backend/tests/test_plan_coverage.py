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


# ---- fix round 1: continuity, reversal, rings, ring-only, NO_DRIVABLE_AREA ----
import logging
from shapely.geometry import Polygon
from app.services.exclusion import ExclusionError

STRIP = Polygon([(0, 0), (200, 0), (200, 30), (0, 30)])


def _plan_at(access, poly=RECT, **kw):
    cfg = CoverageConfig(pattern=kw.pop("pattern", "boustrophedon"),
                         headland_passes=kw.pop("passes", 1), **kw)
    return plan_coverage(poly, poly, ROBOT, cfg, access_utm=access, wgs84_poly=wgs84(poly))


@pytest.mark.parametrize("pattern", ["boustrophedon", "snake", "spiral"])
def test_route_is_continuous_and_lengths_add_up(pattern):
    p = _plan_at(GATE, pattern=pattern)
    total = sum(s.geometry.length for s in p.swaths) + sum(t.geometry.length for t in p.turns)
    assert p.route.length == pytest.approx(total, abs=0.01)
    # every swath/turn vertex chain is contiguous along the route
    coords = list(p.route.coords)
    for s in p.swaths:
        assert Point(s.geometry.coords[0]).distance(p.route) < 1e-6
        assert Point(s.geometry.coords[-1]).distance(p.route) < 1e-6
    assert len(coords) >= 2


@pytest.mark.parametrize("access", [Point(0, 0), Point(200, 100), Point(0, 50), Point(200, 50)])
def test_orientation_start_is_nearer_end_and_indices_adjacent(access):
    p = _plan_at(access)
    start = Point(p.route.coords[0])
    work = [sw for sw in p.swaths if sw.kind == "work"]
    assert start.distance(access) <= Point(work[-1].geometry.coords[-1]).distance(access) + 1e-6
    assert [s.index for s in p.swaths] == list(range(len(p.swaths)))
    assert [t.index for t in p.turns] == list(range(len(p.turns)))
    for t in p.turns:
        assert t.to_swath == t.from_swath + 1
    # route is continuous
    total = sum(s.geometry.length for s in p.swaths) + sum(t.geometry.length for t in p.turns)
    assert p.route.length == pytest.approx(total, abs=0.01)


def test_far_corner_access_reverses_route_toward_it():
    a = _plan_at(Point(0, 0))
    b = _plan_at(Point(200, 100))
    for plan, acc in ((a, Point(0, 0)), (b, Point(200, 100))):
        first = Point(plan.route.coords[0])
        # first interior swath endpoint is nearer to the access than the route's last interior end
        work = [s for s in plan.swaths if s.kind == "work"]
        w0, w1 = Point(work[0].geometry.coords[0]), Point(work[-1].geometry.coords[-1])
        assert first.distance(acc) == pytest.approx(w0.distance(acc))
        assert w0.distance(acc) <= w1.distance(acc) + 1e-6
    # the two plans must differ (a reversal happened for at least one)
    assert Point(a.route.coords[0]).distance(Point(b.route.coords[0])) > 1.0


def test_inner_ring_offset_is_three_halves_width():
    p = _plan(passes=2)
    heads = [s for s in p.swaths if s.kind == "headland"]
    assert RECT.exterior.distance(heads[0].geometry) == pytest.approx(30.0, abs=0.05)
    assert RECT.exterior.distance(heads[1].geometry) == pytest.approx(10.0, abs=0.05)


def test_return_uses_access_path_back_and_closes_at_access():
    p = _plan(return_to_access=True)
    last = p.turns[-1]
    assert last.from_swath == last.to_swath == p.swaths[-1].index
    assert Point(last.geometry.coords[0]).distance(Point(p.swaths[-1].geometry.coords[-1])) < 1e-6
    assert Point(p.route.coords[-1]).distance(GATE) < 1e-6
    total = sum(s.geometry.length for s in p.swaths) + sum(t.geometry.length for t in p.turns)
    assert p.route.length == pytest.approx(total, abs=0.01)


def test_ring_only_plan_when_no_interior(caplog):
    with caplog.at_level(logging.WARNING):
        p = _plan_at(Point(0, 15), poly=STRIP, passes=1)
    assert p.swaths and all(s.kind == "headland" for s in p.swaths)
    assert p.access_path is not None
    ring = p.swaths[0].geometry
    assert ring.is_closed
    assert p.route.length == pytest.approx(sum(s.geometry.length for s in p.swaths)
                                           + sum(t.geometry.length for t in p.turns), abs=0.01)


def test_ring_shortfall_is_logged(caplog):
    with caplog.at_level(logging.WARNING):
        p = _plan_at(Point(0, 15), poly=STRIP, passes=2)
    assert len([s for s in p.swaths if s.kind == "headland"]) < 2
    assert any("fewer than requested" in r.getMessage() for r in caplog.records)


def test_no_drivable_area_raises():
    tiny = Polygon([(0, 0), (8, 0), (8, 8), (0, 8)])   # narrower than cov_width: no ring, no interior
    with pytest.raises(ExclusionError) as e:
        _plan_at(Point(0, 4), poly=tiny)
    assert e.value.code == "NO_DRIVABLE_AREA"


def test_split_path_adds_connector_between_adjacent_swaths():
    import fields2cover as f2c
    from app.services.coverage.f2c_engine import _split_path

    class _P:  # minimal stand-in for a PathState
        def __init__(self, t, x, y, ang=0.0, ln=0.0):
            self.type, self.angle, self.len = t, ang, ln
            self.point = type("Pt", (), {"getX": lambda _s: x, "getY": lambda _s: y})()

    class _S(list):
        def size(self):
            return len(self)

    class _Path:
        def getStates(self):
            sw = f2c.PathSectionType_SWATH
            return _S([_P(sw, 0, 0, 0.0, 10.0), _P(sw, 0, 5, 0.0, 10.0)])

    parts = _split_path(_Path())
    assert [k for k, _ in parts] == ["swath", "turn", "swath"]
    assert parts[1][1].coords[0] == (10.0, 0.0) and parts[1][1].coords[-1] == (0.0, 5.0)
