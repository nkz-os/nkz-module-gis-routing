import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import Point, Polygon
from app.services.coverage.errors import PlanError, CODES
from app.services.exclusion import ExclusionError, validate_access_point
from app.services.coverage.robot_model import build_robot


def test_status_by_code():
    assert PlanError("INVALID_GEOMETRY", "x").status == 400
    assert PlanError("ENGINE_FAILURE", "x").status == 500
    assert PlanError("NO_DRIVABLE_AREA", "x").status == 422
    with pytest.raises(ValueError):
        PlanError("NOT_A_CODE", "x")


def test_to_body_shape():
    body = PlanError("ACCESS_IN_ZONE", "gate in zone", {"point": {"type": "Point", "coordinates": [0, 0]}}).to_body()
    assert body == {"code": "ACCESS_IN_ZONE", "detail": "gate in zone",
                    "params": {"point": {"type": "Point", "coordinates": [0, 0]}}}
    assert PlanError("ENGINE_FAILURE", "x").to_body()["params"] == {}


def test_exclusion_error_is_plan_error_with_default_code():
    err = ExclusionError("nothing left")
    assert isinstance(err, PlanError) and err.code == "NO_DRIVABLE_AREA" and err.status == 422


def test_robot_errors_carry_codes():
    with pytest.raises(PlanError) as e1:
        build_robot({"minTurningRadius": 5}, overlap_pct=0)
    assert e1.value.code == "MACHINE_WIDTH_MISSING"
    with pytest.raises(PlanError) as e2:
        build_robot({"implementWidth": 6}, overlap_pct=0)
    assert e2.value.code == "TURNING_RADIUS_MISSING"


def test_access_point_errors_carry_point():
    parcel = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    zone = Polygon([(40, 40), (60, 40), (60, 60), (40, 60)])
    with pytest.raises(ExclusionError) as e1:
        validate_access_point(Point(150, 50), parcel, [zone], 1.5)
    assert e1.value.code == "ACCESS_OUTSIDE_PARCEL"
    assert e1.value.params["point"]["coordinates"] == [150.0, 50.0]
    with pytest.raises(ExclusionError) as e2:
        validate_access_point(Point(50, 50), parcel, [zone], 1.5,
                              to_wgs84=lambda x, y: (x / 1000.0, y / 1000.0))
    assert e2.value.code == "ACCESS_IN_ZONE"
    assert e2.value.params["point"]["coordinates"] == [0.05, 0.05]


def test_http_handler_returns_flat_body():
    from app.main import create_app
    app = create_app()

    @app.get("/boom")
    async def boom():
        raise PlanError("ACCESS_OUTSIDE_PARCEL", "outside", {"point": {"type": "Point", "coordinates": [1, 2]}})

    resp = TestClient(app).get("/boom")
    assert resp.status_code == 422
    assert resp.json() == {"code": "ACCESS_OUTSIDE_PARCEL", "detail": "outside",
                           "params": {"point": {"type": "Point", "coordinates": [1, 2]}}}
