"""Geometry of the machine that works the parcel: a tractor with an implement, or one
machine alone (self-propelled sprayer, harvester, robot).

Frame (ISO 11783-10): X forward, Y right, metres. Tractor origin: its turning reference
point (rear-axle centre for Ackermann steering). Implement origin: its hitch point.
Each figure comes from the machine that owns it: the turning from the tractor, the
working width and offsets from the implement. An absent attribute is a gap (reported),
a stored 0 is a value. Nothing is guessed: a gap gives d = 0 plus a warning.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.coverage.errors import PlanError


@dataclass(frozen=True)
class MachineGeometry:
    width: float | None            # working width (m)
    track: float | None            # tractor track width (m)
    radius: float | None           # tractor min turning radius (m)
    steering: str                  # tractor steeringType ("" when unknown)
    d: float                       # turning point -> working centre, along X (m); < 0 behind
    e: float                       # working centre lateral offset (m); > 0 right
    transport_width: float | None  # implement folded width (m)
    warnings: tuple[dict, ...]     # {"code", "params"}


def _num(machine: dict | None, key: str) -> float | None:
    if not machine or machine.get(key) is None or machine.get(key) == "":
        return None
    try:
        return float(machine[key])
    except (TypeError, ValueError):
        return None


def check_roles(tractor: dict | None, implement: dict | None, *,
                tractor_id: str | None, implement_id: str | None) -> None:
    """A machine picked as tractor must not be an implement, and the reverse.
    A machine without a known category is accepted (older entities carry none)."""
    if tractor is not None and tractor.get("category") == "implement":
        raise PlanError("MACHINE_ROLE_MISMATCH", "the machine picked as tractor is an implement",
                        {"tractor_id": tractor_id})
    if implement is not None and implement.get("category") == "tractor":
        raise PlanError("MACHINE_ROLE_MISMATCH", "the machine picked as implement is a tractor",
                        {"implement_id": implement_id})


def machine_geometry(tractor: dict | None, implement: dict | None) -> MachineGeometry:
    if tractor is None and implement is None:
        return MachineGeometry(width=None, track=None, radius=None, steering="", d=0.0, e=0.0,
                               transport_width=None, warnings=())
    working = implement if implement is not None else tractor
    missing: list[str] = []
    suspect: list[str] = []

    if implement is not None:
        front = str(implement.get("mountPosition") or "rear") == "front"
        hitch_key = "frontHitchOffsetX" if front else "hitchOffsetX"
        hitch = _num(tractor, hitch_key)
        if hitch is None:
            missing.append(hitch_key)
        elif (hitch < 0) if front else (hitch > 0):
            suspect.append(hitch_key)
    else:
        front, hitch = False, 0.0  # a machine alone: its working centre is measured from itself
    ox = _num(working, "implementOffsetX")
    if ox is None:
        missing.append("implementOffsetX")
    elif implement is not None and not front and ox > 0:
        suspect.append("implementOffsetX")
    d = hitch + ox if hitch is not None and ox is not None else 0.0

    # Tractor figures; an implement saved before the roles were split may still carry them.
    track = _num(tractor, "trackWidth")
    if track is None:
        track = _num(implement, "trackWidth")
    if tractor is not None and track is None:
        missing.append("trackWidth")

    warnings = []
    if missing:
        warnings.append({"code": "MACHINE_GEOMETRY_INCOMPLETE", "params": {"missing": missing}})
    if suspect:
        warnings.append({"code": "MACHINE_GEOMETRY_SUSPECT", "params": {"fields": suspect}})
    width = _num(implement, "implementWidth")
    if width is None:
        width = _num(tractor, "implementWidth")
    return MachineGeometry(
        width=width,
        track=track,
        radius=(_num(tractor, "minTurningRadius") if _num(tractor, "minTurningRadius") is not None
                else _num(implement, "minTurningRadius")),
        steering=str((tractor or {}).get("steeringType") or (implement or {}).get("steeringType") or ""),
        d=d,
        # Absent lateral offset = centred (nearly every implement): not reported as a gap.
        e=_num(working, "implementOffsetY") or 0.0,
        transport_width=_num(implement, "transportWidth"),
        warnings=tuple(warnings),
    )
