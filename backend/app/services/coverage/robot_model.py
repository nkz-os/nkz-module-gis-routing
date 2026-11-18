"""Map a ManufacturingMachine entity to a Fields2Cover Robot.

Single point of translation between platform kinematics and the F2C engine
(Engine Isolation). Missing required data is an explicit error (No Guessing)
rather than a silent default.
"""
from __future__ import annotations

from dataclasses import dataclass

try:
    import fields2cover as f2c
except ImportError:  # engine only present in the CI/runtime image
    f2c = None

from app.services.coverage.errors import PlanError

# steeringType values that imply reverse-capable / pivoting curves
# (Reeds-Shepp). Canonical Entity Wizard vocabulary is articulated / skid_steer
# / differential; the rest are robustness aliases from other sources. Ackermann
# (and anything unrecognized) falls back to forward-only Dubins.
_REEDS_SHEPP_STEERING = {
    "articulated", "skid_steer", "differential",
    "tracked", "crawler", "skid",
}


@dataclass(frozen=True)
class RobotParams:
    width: float            # track width (m)
    cov_width: float        # effective coverage width (m)
    min_turning_radius: float  # m
    curve_type: str         # "dubins" | "reeds_shepp"
    # Turning point -> working centre along the travel (m; < 0 behind). The headland
    # needs that much more depth: the machine runs it past the pass end before turning.
    lag_m: float = 0.0
    # Half the tractor track (m), 0 when unknown: the turn must keep the tractor inside too.
    body_half_width: float = 0.0
    # Working centre lateral offset (m; > 0 right): the tractor runs |lateral| to the other
    # side, so neighbouring passes are cov_width +/- 2|lateral| apart for the tractor.
    lateral_m: float = 0.0

    def to_f2c_robot(self) -> "f2c.Robot":
        robot = f2c.Robot(self.width, self.cov_width)
        robot.setMinTurningRadius(self.min_turning_radius)
        return robot


def _num(value, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_robot(
    machine: dict,
    *,
    overlap_pct: float,
    turning_radius_override: float | None = None,
    lag_m: float = 0.0,
    lateral_m: float = 0.0,
) -> RobotParams:
    """Build robot params from a ManufacturingMachine attr dict.

    `machine` keys mirror the /equipment response (implementWidth, trackWidth,
    minTurningRadius, steeringType). `turning_radius_override` wins when the SDM
    field is absent (the Entity Wizard field is a separate-repo handoff).
    """
    impl_width = _num(machine.get("implementWidth"))
    if impl_width is None or impl_width <= 0:
        raise PlanError("MACHINE_WIDTH_MISSING", "implementWidth is required and must be > 0")

    known_track = _num(machine.get("trackWidth"))
    track = known_track or impl_width

    radius = turning_radius_override
    if radius is None:
        radius = _num(machine.get("minTurningRadius"))
    if radius is None or radius <= 0:
        raise PlanError(
            "TURNING_RADIUS_MISSING",
            "minTurningRadius missing — provide it on the ManufacturingMachine "
            "entity or pass an override in the request",
        )

    if overlap_pct < 0 or overlap_pct >= 100:
        raise ValueError(f"overlap_pct must be in [0,100), got {overlap_pct}")
    cov_width = impl_width * (1.0 - overlap_pct / 100.0)

    steering = str(machine.get("steeringType", "") or "").strip().lower()
    curve_type = "reeds_shepp" if steering in _REEDS_SHEPP_STEERING else "dubins"

    return RobotParams(
        width=track,
        cov_width=cov_width,
        min_turning_radius=radius,
        curve_type=curve_type,
        lag_m=lag_m,
        lateral_m=lateral_m,
        body_half_width=(known_track / 2.0) if known_track else 0.0,
    )
