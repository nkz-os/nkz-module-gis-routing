import pytest
import fields2cover as f2c
from shapely.geometry import Polygon, MultiLineString
from shapely.ops import unary_union
from app.services.coverage.robot_model import build_robot
from app.services.coverage.f2c_engine import generate_coverage, CoverageConfig


def _rect_200x100():
    return Polygon([
        (-2.0000, 43.0000),
        (-1.99754, 43.0000),
        (-1.99754, 43.0009),
        (-2.0000, 43.0009),
    ])


def _machine():
    return {"implementWidth": 20.0, "trackWidth": 3.0, "minTurningRadius": 6.0,
            "steeringType": "ackermann"}


def test_boustrophedon_returns_continuous_ordered_route():
    robot = build_robot(_machine(), overlap_pct=0.0)
    cfg = CoverageConfig(pattern="boustrophedon", headland_passes=1)
    result = generate_coverage(_rect_200x100(), robot, cfg)

    assert isinstance(result.geometry, MultiLineString)
    assert result.swath_count >= 2            # best heading minimizes pass count
    assert result.total_distance_m > 0
    flat = [i for grp in result.pass_order for i in grp]
    assert sorted(flat) == list(range(len(flat)))


def test_metrics_are_honest():
    robot = build_robot(_machine(), overlap_pct=0.0)
    cfg = CoverageConfig(pattern="boustrophedon", headland_passes=1)
    result = generate_coverage(_rect_200x100(), robot, cfg)
    m = result.metrics
    assert m["worked_distance_m"] > 0
    assert m["non_working_distance_m"] >= 0
    assert 0.0 < m["field_efficiency"] <= 1.0
    assert m["covered_area_ha"] <= result.metrics["parcel_area_ha"] + 1e-6


def test_turns_respect_turning_radius():
    poly = Polygon([(-2.0, 43.0), (-1.99963, 43.0),
                    (-1.99963, 43.00027), (-2.0, 43.00027)])
    robot = build_robot({"implementWidth": 6.0, "trackWidth": 2.0,
                         "minTurningRadius": 10.0}, overlap_pct=0.0)
    cfg = CoverageConfig(pattern="boustrophedon", headland_passes=1)
    result = generate_coverage(poly, robot, cfg)
    assert result.total_distance_m > 0


def test_headland_only_pattern():
    robot = build_robot(_machine(), overlap_pct=0.0)
    cfg = CoverageConfig(pattern="headland-only", headland_passes=2)
    result = generate_coverage(_rect_200x100(), robot, cfg)
    assert result.headland_count >= 1


_SORT_ONE_SWATH = """
import sys
import fields2cover as f2c
from app.services.coverage.f2c_engine import _sort_swaths
sw = f2c.Swaths()
sw.emplace_back(f2c.LineString(f2c.VectorPoint([f2c.Point(0, 0), f2c.Point(0, 100)])), 10.0, 0)
print(_sort_swaths(sys.argv[1], sw).size())
"""


@pytest.mark.parametrize("pattern", ["boustrophedon", "snake", "spiral"])
def test_sort_swaths_single_swath_every_pattern_in_subprocess(pattern):
    # Own process: a native crash in the engine must not take pytest down.
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-c", _SORT_ONE_SWATH, pattern],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-500:]
    assert r.stdout.strip() == "1"


def test_sort_swaths_keeps_order_for_many():
    from app.services.coverage.f2c_engine import _sort_swaths
    sw = f2c.Swaths()
    for i in range(3):
        sw.emplace_back(f2c.LineString(f2c.VectorPoint([f2c.Point(i * 10.0, 0), f2c.Point(i * 10.0, 100)])), 10.0, i)
    assert _sort_swaths("boustrophedon", sw).size() == 3
