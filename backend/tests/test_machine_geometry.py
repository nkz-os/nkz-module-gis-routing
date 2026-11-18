"""Tractor + implement geometry: which machine gives each figure, and the warnings."""
import pytest

from app.services.coverage.errors import PlanError
from app.services.coverage.machine_geometry import MachineGeometry, check_roles, machine_geometry

TRACTOR = {"category": "tractor", "minTurningRadius": 5.0, "trackWidth": 1.9, "steeringType": "ackermann",
           "hitchOffsetX": -1.2, "frontHitchOffsetX": 2.8}
DRILL = {"category": "implement", "implementWidth": 4.0, "implementOffsetX": -2.0, "mountPosition": "rear",
         "transportWidth": 3.0}


def codes(g: MachineGeometry) -> dict:
    return {w["code"]: w["params"] for w in g.warnings}


def test_pair_takes_width_from_implement_and_turning_from_tractor():
    g = machine_geometry(TRACTOR, DRILL)
    assert (g.width, g.radius, g.track, g.steering) == (4.0, 5.0, 1.9, "ackermann")
    assert g.d == pytest.approx(-3.2)  # rear hitch -1.2 + working centre -2.0
    assert g.e == 0.0
    assert g.transport_width == 3.0
    assert g.warnings == ()


def test_front_implement_uses_the_front_hitch():
    mower = {"category": "implement", "implementWidth": 3.0, "implementOffsetX": 0.5, "mountPosition": "front"}
    assert machine_geometry(TRACTOR, mower).d == pytest.approx(3.3)


def test_side_mower_offset_comes_from_the_implement():
    mower = {**DRILL, "implementOffsetY": 1.6}
    assert machine_geometry(TRACTOR, mower).e == 1.6


def test_self_propelled_machine_alone_uses_its_own_working_centre():
    sprayer = {"category": "tractor", "minTurningRadius": 6.0, "trackWidth": 2.0, "implementWidth": 36.0,
               "implementOffsetX": -4.0, "implementOffsetY": 0.0}
    g = machine_geometry(sprayer, None)
    assert (g.width, g.radius, g.d, g.e) == (36.0, 6.0, -4.0, 0.0)
    assert g.warnings == ()


def test_a_stored_zero_is_a_value_not_a_gap():
    g = machine_geometry({**TRACTOR, "hitchOffsetX": 0.0}, {**DRILL, "implementOffsetX": 0.0})
    assert g.d == 0.0 and g.warnings == ()


def test_missing_geometry_gives_d_zero_and_names_the_fields():
    tractor = {k: v for k, v in TRACTOR.items() if k not in ("hitchOffsetX", "trackWidth")}
    drill = {k: v for k, v in DRILL.items() if k != "implementOffsetX"}
    g = machine_geometry(tractor, drill)
    assert g.d == 0.0 and g.track is None
    assert sorted(codes(g)["MACHINE_GEOMETRY_INCOMPLETE"]["missing"]) == ["hitchOffsetX", "implementOffsetX", "trackWidth"]


def test_implement_without_tractor_has_no_hitch_and_no_radius():
    g = machine_geometry(None, DRILL)
    assert g.radius is None and g.d == 0.0
    assert "hitchOffsetX" in codes(g)["MACHINE_GEOMETRY_INCOMPLETE"]["missing"]


def test_machine_alone_without_working_centre_warns():
    g = machine_geometry({k: v for k, v in TRACTOR.items()}, None)
    assert codes(g)["MACHINE_GEOMETRY_INCOMPLETE"]["missing"] == ["implementOffsetX"]


def test_signs_that_contradict_the_mounting_are_flagged_not_fixed():
    g = machine_geometry({**TRACTOR, "hitchOffsetX": 1.2}, {**DRILL, "implementOffsetX": 2.0})
    assert sorted(codes(g)["MACHINE_GEOMETRY_SUSPECT"]["fields"]) == ["hitchOffsetX", "implementOffsetX"]
    assert g.d == pytest.approx(3.2)  # used as stored
    front = machine_geometry({**TRACTOR, "frontHitchOffsetX": -2.0},
                             {**DRILL, "mountPosition": "front", "implementOffsetX": 0.3})
    assert codes(front)["MACHINE_GEOMETRY_SUSPECT"]["fields"] == ["frontHitchOffsetX"]


def test_no_machines_means_no_geometry_and_no_warning():
    g = machine_geometry(None, None)
    assert g == MachineGeometry(width=None, track=None, radius=None, steering="", d=0.0, e=0.0,
                                transport_width=None, warnings=())


def test_crossed_roles_are_an_error_and_unknown_roles_pass():
    with pytest.raises(PlanError) as exc:
        check_roles({"category": "implement"}, None, tractor_id="urn:t", implement_id=None)
    assert exc.value.code == "MACHINE_ROLE_MISMATCH" and exc.value.params == {"tractor_id": "urn:t"}
    with pytest.raises(PlanError) as exc:
        check_roles(None, {"category": "tractor"}, tractor_id=None, implement_id="urn:i")
    assert exc.value.params == {"implement_id": "urn:i"}
    check_roles({}, {"category": "harvester"}, tractor_id="a", implement_id="b")  # no error


def test_legacy_implement_radius_is_used_when_the_tractor_has_none():
    legacy = {**DRILL, "minTurningRadius": 7.0, "trackWidth": 2.1, "steeringType": "articulated"}
    g = machine_geometry(None, legacy)
    assert (g.radius, g.track, g.steering) == (7.0, 2.1, "articulated")
    assert machine_geometry(TRACTOR, legacy).radius == 5.0  # the tractor's wins


def test_an_empty_string_is_a_gap_not_zero():
    g = machine_geometry({**TRACTOR, "hitchOffsetX": ""}, DRILL)
    assert g.d == 0.0
    assert "hitchOffsetX" in codes(g)["MACHINE_GEOMETRY_INCOMPLETE"]["missing"]
