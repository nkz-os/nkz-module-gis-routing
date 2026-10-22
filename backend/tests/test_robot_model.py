import math
import pytest
from app.services.coverage.robot_model import build_robot, RobotParams


def test_build_robot_from_kinematics():
    machine = {
        "implementWidth": 6.0,
        "trackWidth": 2.0,
        "minTurningRadius": 4.5,
        "steeringType": "ackermann",
    }
    params = build_robot(machine, overlap_pct=0.0)
    assert params.cov_width == pytest.approx(6.0)
    assert params.width == pytest.approx(2.0)
    assert params.min_turning_radius == pytest.approx(4.5)
    assert params.curve_type == "dubins"


def test_overlap_reduces_coverage_width():
    machine = {"implementWidth": 10.0, "trackWidth": 2.0, "minTurningRadius": 3.0}
    params = build_robot(machine, overlap_pct=10.0)
    assert params.cov_width == pytest.approx(9.0)


@pytest.mark.parametrize("steering", ["articulated", "skid_steer", "differential"])
def test_reverse_capable_steering_uses_reeds_shepp(steering):
    # Entity Wizard steeringType vocabulary: ackermann | articulated |
    # skid_steer | differential. All but ackermann can pivot/reverse.
    machine = {"implementWidth": 4.0, "trackWidth": 2.0,
               "minTurningRadius": 3.0, "steeringType": steering}
    params = build_robot(machine, overlap_pct=0.0)
    assert params.curve_type == "reeds_shepp"


def test_ackermann_steering_uses_dubins():
    machine = {"implementWidth": 4.0, "trackWidth": 2.0,
               "minTurningRadius": 3.0, "steeringType": "ackermann"}
    params = build_robot(machine, overlap_pct=0.0)
    assert params.curve_type == "dubins"


def test_missing_turning_radius_uses_override_or_raises():
    machine = {"implementWidth": 4.0, "trackWidth": 2.0}
    with pytest.raises(ValueError, match="minTurningRadius"):
        build_robot(machine, overlap_pct=0.0)
    params = build_robot(machine, overlap_pct=0.0, turning_radius_override=5.0)
    assert params.min_turning_radius == pytest.approx(5.0)


def test_to_f2c_robot_sets_radius():
    machine = {"implementWidth": 6.0, "trackWidth": 2.0, "minTurningRadius": 4.5}
    params = build_robot(machine, overlap_pct=0.0)
    robot = params.to_f2c_robot()
    assert robot.getMinTurningRadius() == pytest.approx(4.5)
