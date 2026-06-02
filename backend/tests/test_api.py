"""
Tests for GIS Routing Backend API structure.

Covers health check, OpenAPI schema, and endpoint availability.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Test client fixture."""
    return TestClient(app)


class TestHealth:
    """Health endpoint tests."""

    def test_health_check(self, client):
        """Test health endpoint returns healthy status."""
        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert "service" in data
        assert "version" in data


class TestAPI:
    """API endpoint tests."""

    def test_docs_available(self, client):
        """Test OpenAPI docs are available."""
        response = client.get("/api/routing/docs")
        # Should return HTML or redirect
        assert response.status_code in [200, 307]

    def test_openapi_schema(self, client):
        """Test OpenAPI schema is generated."""
        response = client.get("/api/routing/openapi.json")
        assert response.status_code == 200

        schema = response.json()
        assert "openapi" in schema
        assert "paths" in schema

    def test_ingest_external_zones_geojson_ok(self, client):
        response = client.post(
            "/api/routing/zones/external/ingest",
            json={
                "format": "geojson",
                "content": (
                    '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Polygon",'
                    '"coordinates":[[[0,0],[1,0],[1,1],[0,1],[0,0]]]},"properties":{"zone_id":"z1",'
                    '"zone_class":"high","prescription_rate":1.2}}]}'
                ),
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["count"] == 1
        assert data["data"]["zones"][0]["properties"]["zone_id"] == "z1"

    def test_ingest_external_zones_csv_invalid_geometry(self, client):
        response = client.post(
            "/api/routing/zones/external/ingest",
            json={
                "format": "csv",
                "content": "zone_id,geometry,prescription_rate\nz1,not_json,1.1\n",
            },
        )
        assert response.status_code == 400


class TestPatternsFailOpen:
    """Pattern listing must fail-open when the (currently unreachable) pattern
    store cannot be contacted, so the UI loads instead of 500ing."""

    def test_list_patterns_empty_when_store_unreachable(self, client, monkeypatch):
        async def _boom(self, tenant_id, parcel_id):
            raise ConnectionError("[Errno 111] Connection refused")

        monkeypatch.setattr(
            "app.api.patterns_router.PatternStore.list_for_parcel", _boom
        )
        response = client.get(
            "/api/routing/patterns",
            params={"parcel_id": "urn:ngsi-ld:AgriParcel:p1"},
            headers={"X-Tenant-ID": "tenant-a"},
        )
        assert response.status_code == 200
        assert response.json() == {"success": True, "data": []}
