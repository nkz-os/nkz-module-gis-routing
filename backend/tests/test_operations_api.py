from fastapi.testclient import TestClient

from app.main import create_app
from app.middleware import TenantStateMiddleware


def _tenant_dispatch(_tenant_id: str):
    async def dispatch(self, request, call_next):
        request.state.tenant_id = _tenant_id
        request.state.user_id = "test-user"
        return await call_next(request)

    return dispatch


async def _no_other_active(*_args, **_kwargs):
    return None


def test_close_operation_session_ok(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("tenant-a"))
    client = TestClient(create_app())

    response = client.post(
        "/api/routing/operations/session/close",
        json={
            "operation_id": "urn:ngsi-ld:AgriParcelOperation:tenant-a:op-1",
            "end_date": "2026-05-06T14:00:00Z",
            "status": "ended",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "marked for closure" in payload["message"]


def test_start_operation_session_ok(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("tenant-a"))
    monkeypatch.setattr(
        "app.api.operations.find_other_active_operation_id",
        _no_other_active,
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/routing/operations/session/start",
        json={
            "operation_id": "urn:ngsi-ld:AgriParcelOperation:tenant-a:op-10",
            "start_date": "2026-05-06T14:00:00Z",
            "status": "in_progress",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "marked as started" in payload["message"]


async def _other_active(*_args, **_kwargs):
    return "urn:ngsi-ld:AgriParcelOperation:tenant-a:existing-active"


def test_start_operation_session_conflict(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("tenant-a"))
    monkeypatch.setattr(
        "app.api.operations.find_other_active_operation_id",
        _other_active,
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/routing/operations/session/start",
        json={
            "operation_id": "urn:ngsi-ld:AgriParcelOperation:tenant-a:op-new",
            "start_date": "2026-05-06T14:00:00Z",
            "status": "in_progress",
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"]["code"] == "ACTIVE_OPERATION_CONFLICT"


async def _empty_in_progress(*_args, **_kwargs):
    return []


def test_get_active_operation_none(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("tenant-a"))
    monkeypatch.setattr(
        "app.api.operations.find_in_progress_operations",
        _empty_in_progress,
    )
    client = TestClient(create_app())

    response = client.get("/api/routing/operations/active")

    assert response.status_code == 200
    assert response.json()["data"]["operation"] is None


async def _one_in_progress(*_args, **_kwargs):
    return [
        {
            "id": "urn:ngsi-ld:AgriParcelOperation:tenant-a:op-active",
            "type": "AgriParcelOperation",
            "status": {"type": "Property", "value": "in_progress"},
            "operationType": {"type": "Property", "value": "spraying"},
            "hasAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:tenant-a:p1"},
            "startDate": {
                "type": "Property",
                "value": {"@type": "DateTime", "@value": "2026-05-06T10:00:00Z"},
            },
            "name": {"type": "Property", "value": "Test op"},
        }
    ]


def test_get_active_operation_ok(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("tenant-a"))
    monkeypatch.setattr(
        "app.api.operations.find_in_progress_operations",
        _one_in_progress,
    )
    client = TestClient(create_app())

    response = client.get("/api/routing/operations/active")

    assert response.status_code == 200
    op = response.json()["data"]["operation"]
    assert op["id"].endswith("op-active")
    assert op["status"] == "in_progress"
    assert "p1" in op["parcel_id"]


def test_close_after_start_ok(monkeypatch):
    """Close remains allowed after a start ack (background patch)."""
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("tenant-a"))
    monkeypatch.setattr(
        "app.api.operations.find_other_active_operation_id",
        _no_other_active,
    )
    client = TestClient(create_app())

    start = client.post(
        "/api/routing/operations/session/start",
        json={
            "operation_id": "urn:ngsi-ld:AgriParcelOperation:tenant-a:op-seq",
            "start_date": "2026-05-06T14:00:00Z",
            "status": "in_progress",
        },
    )
    assert start.status_code == 200

    close = client.post(
        "/api/routing/operations/session/close",
        json={
            "operation_id": "urn:ngsi-ld:AgriParcelOperation:tenant-a:op-seq",
            "end_date": "2026-05-06T16:00:00Z",
            "status": "ended",
        },
    )
    assert close.status_code == 200


def test_get_operation_coverage_not_found(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("tenant-a"))

    async def fake_get_coverage(self, operation_id: str, tenant_id: str):
        assert operation_id == "urn:ngsi-ld:AgriParcelOperation:tenant-a:op-2"
        assert tenant_id == "tenant-a"
        return None

    monkeypatch.setattr(
        "app.services.coverage_service.CoverageService.get_operation_coverage",
        fake_get_coverage,
    )

    client = TestClient(create_app())
    response = client.get(
        "/api/routing/operations/coverage/urn%3Angsi-ld%3AAgriParcelOperation%3Atenant-a%3Aop-2"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "No telemetry coverage found for this operation."


def test_get_operation_coverage_ok(monkeypatch):
    monkeypatch.setattr(TenantStateMiddleware, "dispatch", _tenant_dispatch("tenant-a"))

    async def fake_get_coverage(self, operation_id: str, tenant_id: str):
        assert operation_id == "urn:ngsi-ld:AgriParcelOperation:tenant-a:op-3"
        assert tenant_id == "tenant-a"
        return {
            "type": "LineString",
            "coordinates": [[-1.0, 42.0], [-1.0005, 42.0005]],
        }

    monkeypatch.setattr(
        "app.services.coverage_service.CoverageService.get_operation_coverage",
        fake_get_coverage,
    )

    client = TestClient(create_app())
    response = client.get(
        "/api/routing/operations/coverage/urn%3Angsi-ld%3AAgriParcelOperation%3Atenant-a%3Aop-3"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["properties"]["layer_type"] == "actual_coverage"
    assert payload["data"]["geometry"]["type"] == "LineString"
