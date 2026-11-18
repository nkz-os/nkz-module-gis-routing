"""How deep a headland the implement's turn needs.

The closed-form minimum (validation.min_headland_passes) assumes a turn that
fits in a radius. With a working width under twice the turning radius, the
turn between neighbouring passes loops out ("omega" turn) and runs well past
the end of the pass. The depth is measured here with the same engine, curve
and discretization the planner uses, instead of estimated.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import fields2cover as f2c

from app.services.coverage.robot_model import RobotParams
from app.services.coverage.validation import min_headland_passes

_PASS_LEN_M = 100.0


@dataclass(frozen=True)
class HeadlandNeed:
    needed_m: float   # headland depth the turn needs, implement half width included
    passes: int       # headland passes that give at least needed_m


def headland_need(robot: RobotParams) -> HeadlandNeed:
    return _need(robot.width, robot.cov_width, robot.min_turning_radius, robot.curve_type,
                 robot.lag_m, robot.body_half_width)


@lru_cache(maxsize=64)
def _need(width: float, cov_width: float, radius: float, curve_type: str,
          lag_m: float = 0.0, body_half_width: float = 0.0) -> HeadlandNeed:
    robot = RobotParams(width=width, cov_width=cov_width, min_turning_radius=radius, curve_type=curve_type)
    # Next pass (boustrophedon) and the one after (snake): the deeper turn wins.
    advance = max(_turn_advance(robot, cov_width), _turn_advance(robot, 2 * cov_width))
    # The implement lifts at the pass end with the turning point |lag| further on (or, for
    # a front implement, |lag| behind while the implement leads): either way the turn runs
    # |lag| deeper. The wider of implement and tractor sets the side extent.
    needed_m = abs(lag_m) + advance + max(cov_width / 2.0, body_half_width)
    # Centimetre rounding: discretization noise (18.00003 m) must not cost a whole pass.
    passes = max(math.ceil(round(needed_m, 2) / cov_width), min_headland_passes(radius, cov_width))
    return HeadlandNeed(needed_m=needed_m, passes=passes)


def _turn_advance(robot: RobotParams, spacing: float) -> float:
    """Farthest the turn between two opposite passes `spacing` apart runs past their ends."""
    from app.services.coverage.f2c_engine import TURN_DISCRETIZATION_M  # avoid an import cycle

    swaths = f2c.Swaths()
    swaths.emplace_back(f2c.LineString(f2c.VectorPoint(
        [f2c.Point(0.0, 0.0), f2c.Point(0.0, _PASS_LEN_M)])), robot.cov_width, 0)
    swaths.emplace_back(f2c.LineString(f2c.VectorPoint(
        [f2c.Point(spacing, _PASS_LEN_M), f2c.Point(spacing, 0.0)])), robot.cov_width, 1)
    curve = f2c.PP_ReedsSheppCurves() if robot.curve_type == "reeds_shepp" else f2c.PP_DubinsCurves()
    curve.setDiscretization(TURN_DISCRETIZATION_M)
    path = f2c.PP_PathPlanning().planPath(robot.to_f2c_robot(), swaths, curve)
    ys = [path.getState(i).point.getY() for i in range(path.size())
          if path.getState(i).type == f2c.PathSectionType_TURN]
    return max(0.0, max(ys, default=_PASS_LEN_M) - _PASS_LEN_M)
