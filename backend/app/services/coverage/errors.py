"""Coded plan errors: a stable machine-readable code plus parameters.

The HTTP layer renders them as ``{code, detail, params}`` so clients can
localise the message; ``detail`` is neutral English for logs and fallbacks.
"""
from __future__ import annotations

CODES = (
    "NO_DRIVABLE_AREA",
    "ACCESS_OUTSIDE_PARCEL",
    "ACCESS_IN_ZONE",
    "MACHINE_WIDTH_MISSING",
    "TURNING_RADIUS_MISSING",
    "INVALID_GEOMETRY",
    "ENGINE_FAILURE",
)


class PlanError(ValueError):
    """A planning failure with a code from CODES."""

    def __init__(self, code: str, detail: str, params: dict | None = None) -> None:
        if code not in CODES:
            raise ValueError(f"Unknown plan error code: {code!r}")
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.params = dict(params) if params else {}

    @property
    def status(self) -> int:
        if self.code == "INVALID_GEOMETRY":
            return 400
        if self.code == "ENGINE_FAILURE":
            return 500
        return 422

    def to_body(self) -> dict:
        return {"code": self.code, "detail": self.detail, "params": self.params}
