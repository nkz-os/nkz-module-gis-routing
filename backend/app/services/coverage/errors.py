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
    "INVALID_VRA",
    "ZONES_FILE_INVALID",
    "ZONES_NO_VALUE",
    "ZONES_FILE_TOO_LARGE",
    "PLAN_TOO_LARGE",
    "ZONES_UNAVAILABLE",
    "AREA_TOO_LARGE",
    "BBOX_INVALID",
    "PLAN_EXPIRED",
    "PARCEL_REQUIRED",
    "JOB_NOT_READY",
    "EXPORT_NOT_SUPPORTED",
    "PERSIST_FAILED",
    "ALTERNATIVE_NOT_FOUND",
    "JOB_NOT_FOUND",
    "INVALID_DATES",
    "PARCEL_NOT_FOUND",
    "JOBS_LIMIT",
    "OPERATION_NOT_FOUND",
    "FORBIDDEN",
    "INVALID_SETTING",
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
        if self.code in ("INVALID_GEOMETRY", "ZONES_FILE_INVALID", "ZONES_NO_VALUE"):
            return 400
        if self.code == "ZONES_FILE_TOO_LARGE":
            return 413
        if self.code == "ENGINE_FAILURE":
            return 500
        if self.code in ("ZONES_UNAVAILABLE", "PERSIST_FAILED"):
            return 502
        if self.code in ("JOB_NOT_FOUND", "PARCEL_NOT_FOUND", "OPERATION_NOT_FOUND"):
            return 404
        if self.code == "FORBIDDEN":
            return 403
        if self.code == "JOBS_LIMIT":
            return 429
        if self.code == "PLAN_EXPIRED":
            return 410
        if self.code == "JOB_NOT_READY":
            return 409
        return 422

    def to_body(self) -> dict:
        return {"code": self.code, "detail": self.detail, "params": self.params}
