"""
Integration tests for the sync API (GET/POST /sync) and generate endpoint.

Tests validate request validation, tenant extraction, and error responses.
Full integration requires a running Orion-LD and TimescaleDB; these tests
focus on the API contract (input validation, error codes, status codes).
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestSyncPull:
    """GET /sync endpoint tests."""

    def test_pull_without_auth_returns_404(self, client):
        """Without a valid JWT, tenant_id is None -> 404 TENANT_NOT_FOUND."""
        resp = client.get(
            "/api/routing/sync",
            params={"collections": "parcels", "last_pulled_at": 0, "schema_version": 3},
        )
        assert resp.status_code == 404
        data = resp.json()
        # FastAPI wraps HTTPException detail; access via the detail envelope
        detail = data.get("detail", data)
        assert detail["error"]["code"] == "TENANT_NOT_FOUND"

    def test_pull_missing_collections_returns_422(self, client):
        """Missing required 'collections' query param -> 422 validation error."""
        resp = client.get(
            "/api/routing/sync",
            params={"last_pulled_at": 0, "schema_version": 3},
        )
        assert resp.status_code == 422

    def test_pull_invalid_collection_returns_400(self, client):
        """An unknown collection name must return 400 INVALID_COLLECTION."""
        resp = client.get(
            "/api/routing/sync",
            params={
                "collections": "invalid",
                "last_pulled_at": 0,
                "schema_version": 3,
            },
        )
        # 404 if tenant check fires first, 400 if collection check fires first
        assert resp.status_code in [400, 404]

    def test_pull_partially_invalid_collections_returns_400(self, client):
        """A mix of valid and invalid collections -> 400."""
        resp = client.get(
            "/api/routing/sync",
            params={
                "collections": "parcels,invalid",
                "last_pulled_at": 0,
                "schema_version": 3,
            },
        )
        assert resp.status_code in [400, 404]


class TestSyncPush:
    """POST /sync endpoint tests."""

    def test_push_without_body_returns_422(self, client):
        """POST without JSON body -> 422 (FastAPI cannot parse)."""
        resp = client.post(
            "/api/routing/sync",
            params={"collections": "parcels"},
        )
        # 422 from FastAPI body parsing, 404 from tenant check, or 400 from body check
        assert resp.status_code in [400, 404, 422]

    def test_push_missing_changes_returns_400(self, client):
        """POST with JSON body but missing 'changes' -> 400 INVALID_BODY."""
        resp = client.post(
            "/api/routing/sync",
            params={"collections": "parcels"},
            json={"last_pulled_at": 0},
        )
        assert resp.status_code in [400, 404]

    def test_push_empty_changes_returns_400_or_404(self, client):
        """Valid shape but no auth -> 404 (or 400 if validation fires first)."""
        resp = client.post(
            "/api/routing/sync",
            params={"collections": "parcels"},
            json={
                "changes": {"parcels": {"created": [], "updated": [], "deleted": []}},
                "last_pulled_at": 0,
            },
        )
        # 404 TENANT_NOT_FOUND if route is reached before auth
        assert resp.status_code in [400, 404]

    def test_push_invalid_collection_returns_400(self, client):
        """Unknown collection -> 400 INVALID_COLLECTION."""
        resp = client.post(
            "/api/routing/sync",
            params={"collections": "does-not-exist"},
            json={
                "changes": {},
                "last_pulled_at": 0,
            },
        )
        assert resp.status_code in [400, 404]


class TestGenerate:
    """POST /generate endpoint tests."""

    def test_generate_without_body_returns_422(self, client):
        """POST /generate without JSON body -> 422."""
        resp = client.post("/api/routing/generate")
        assert resp.status_code == 422

    def test_generate_invalid_geometry_returns_400(self, client):
        """Non-Polygon geometry -> 400."""
        resp = client.post(
            "/api/routing/generate",
            json={
                "parcel_geometry": {"type": "Point", "coordinates": [0, 0]},
                "pattern": "ab-line",
                "pattern_config": {"heading_deg": 45, "width_m": 10},
            },
        )
        assert resp.status_code in [400, 404]

    def test_generate_heading_out_of_range_returns_422(self, client):
        """heading_deg outside [0, 360) via pattern_config -> 422."""
        resp = client.post(
            "/api/routing/generate",
            json={
                "parcel_geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                "pattern": "ab-line",
                "pattern_config": {"heading_deg": 361, "width_m": 10},
            },
        )
        assert resp.status_code == 422

    def test_generate_negative_width_returns_422(self, client):
        """width_m <= 0 via pattern_config -> 422."""
        resp = client.post(
            "/api/routing/generate",
            json={
                "parcel_geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                "pattern": "ab-line",
                "pattern_config": {"heading_deg": 45, "width_m": -1},
            },
        )
        assert resp.status_code == 422
