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


def test_implement_behind_the_turning_point_deepens_the_headland_by_that_distance():
    base = headland_need(RobotParams(width=3.0, cov_width=6.0, min_turning_radius=8.0, curve_type="dubins"))
    lag = headland_need(RobotParams(width=3.0, cov_width=6.0, min_turning_radius=8.0, curve_type="dubins", lag_m=-3.0))
    assert lag.needed_m == pytest.approx(base.needed_m + 3.0)
    lead = headland_need(RobotParams(width=3.0, cov_width=6.0, min_turning_radius=8.0, curve_type="dubins", lag_m=2.0))
    assert lead.needed_m == pytest.approx(base.needed_m + 2.0)


def test_a_tractor_wider_than_the_implement_sets_the_floor():
    narrow = headland_need(RobotParams(width=3.0, cov_width=2.0, min_turning_radius=4.0, curve_type="dubins"))
    wide_body = headland_need(RobotParams(width=3.0, cov_width=2.0, min_turning_radius=4.0, curve_type="dubins",
                                          body_half_width=1.5))
    assert wide_body.needed_m == pytest.approx(narrow.needed_m - 1.0 + 1.5)


def test_side_offset_tightens_one_of_the_turns_and_never_makes_the_headland_shallower():
    base = headland_need(RobotParams(width=3.0, cov_width=6.0, min_turning_radius=8.0, curve_type="dubins"))
    side = headland_need(RobotParams(width=3.0, cov_width=6.0, min_turning_radius=8.0, curve_type="dubins",
                                     lateral_m=1.5))
    assert side.needed_m >= base.needed_m
