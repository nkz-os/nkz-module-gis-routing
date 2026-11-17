import pytest
pytest.importorskip("fields2cover")

from app.services.coverage.robot_model import RobotParams
from app.services.coverage.turn_fit import headland_need
from app.services.coverage.validation import min_headland_passes


def test_owner_implement_needs_four_passes():
    need = headland_need(RobotParams(width=3.0, cov_width=6.0, min_turning_radius=8.0, curve_type="dubins"))
    assert need.passes == 4
    assert 18.0 < need.needed_m <= 24.0


def test_wide_implement_needs_no_more_than_formula():
    need = headland_need(RobotParams(width=3.0, cov_width=20.0, min_turning_radius=6.0, curve_type="dubins"))
    assert need.passes == min_headland_passes(6.0, 20.0)


def test_reeds_shepp_measured_too():
    need = headland_need(RobotParams(width=3.0, cov_width=6.0, min_turning_radius=8.0, curve_type="reeds_shepp"))
    assert need.needed_m > 0
    assert need.passes >= min_headland_passes(8.0, 6.0)


def test_cached():
    robot = RobotParams(width=3.0, cov_width=6.0, min_turning_radius=8.0, curve_type="dubins")
    assert headland_need(robot) is headland_need(robot)


def test_numeric_noise_does_not_add_a_pass(monkeypatch):
    from app.services.coverage import turn_fit
    turn_fit._need.cache_clear()
    monkeypatch.setattr(turn_fit, "_turn_advance", lambda robot, spacing: 15.000004)
    need = headland_need(RobotParams(width=3.0, cov_width=6.0, min_turning_radius=1.0, curve_type="dubins"))
    turn_fit._need.cache_clear()
    assert need.passes == 3
