"""
Tests for OrionLDClient -- NGSI-LD Context Broker client.

Covers tenant isolation headers, NGSI-LD @context injection,
and CRUD operation routing.
"""

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from app.services.orion_client import OrionLDClient, OrionLDError


@pytest.fixture
def orion_client():
    """OrionLDClient fixture with test URLs."""
    return OrionLDClient(
        base_url="http://orion:1026",
        context_url="http://api-gateway:5000/ngsi-ld-context.json",
    )


def _mock_response(status_code=200, json_data=None):
    """Create a MagicMock that behaves like httpx.Response.

    httpx.Response.json() and .raise_for_status() are synchronous, but
    when the return_value of an AsyncMock patch is itself an AsyncMock,
    those attributes become coroutines.  Using MagicMock for the response
    object keeps them as regular Mock calls.
    """
    resp = MagicMock()
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
    resp.raise_for_status = Mock()
    return resp


class TestOrionLDClientHeaders:
    """Verify NGSI-LD mandatory headers are always sent."""

    @pytest.mark.asyncio
    async def test_query_entities_includes_ngsild_headers(self, orion_client):
        """The Link header with @context must be present on every request."""
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _mock_response(json_data=[])

            await orion_client.query_entities("AgriParcel", "test_tenant")

            call_args = mock_get.call_args
            headers = call_args[1]["headers"]
            assert "Link" in headers
            assert "ngsi-ld-context" in headers["Link"]

    @pytest.mark.asyncio
    async def test_query_entities_injects_fiware_service(self, orion_client):
        """NGSILD-Tenant and FIWARE-Service must match the tenant_id."""
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _mock_response(json_data=[])

            await orion_client.query_entities("AgriParcel", "test_tenant")

            headers = mock_get.call_args[1]["headers"]
            assert headers["NGSILD-Tenant"] == "test_tenant"
            assert headers["FIWARE-Service"] == "test_tenant"

    @pytest.mark.asyncio
    async def test_headers_rejects_newlines_in_tenant_id(self, orion_client):
        """tenant_id with newline characters must raise ValueError."""
        with pytest.raises(ValueError, match="Invalid tenant_id"):
            orion_client._headers("test\ntenant")

        with pytest.raises(ValueError, match="Invalid tenant_id"):
            orion_client._headers("test\rtenant")

    @pytest.mark.asyncio
    async def test_headers_accepts_valid_tenant_id(self, orion_client):
        """Valid tenant_id must not raise."""
        headers = orion_client._headers("valid_tenant_123")
        assert headers["NGSILD-Tenant"] == "valid_tenant_123"


class TestOrionLDClientCRUD:
    """CRUD operation routing and response handling."""

    @pytest.mark.asyncio
    async def test_create_entity_posts_to_ngsild(self, orion_client):
        """POST must go to /ngsi-ld/v1/entities and return entity ID."""
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.headers = {
                "Location": "/ngsi-ld/v1/entities/urn:ngsi-ld:Test:001"
            }
            mock_post.return_value = mock_resp

            entity = {
                "id": "urn:ngsi-ld:Test:001",
                "type": "Test",
                "name": {"type": "Property", "value": "test"},
            }
            entity_id = await orion_client.create_entity(entity, "test_tenant")

            assert entity_id == "urn:ngsi-ld:Test:001"
            call_url = mock_post.call_args[0][0]
            assert "/ngsi-ld/v1/entities" in call_url

    @pytest.mark.asyncio
    async def test_get_entity_returns_parsed_json(self, orion_client):
        """GET must return parsed entity JSON."""
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _mock_response(
                json_data={"id": "urn:x", "type": "AgriParcel"}
            )

            entity = await orion_client.get_entity("urn:x", "test_tenant")

            assert entity["type"] == "AgriParcel"

    @pytest.mark.asyncio
    async def test_get_entity_returns_none_for_404(self, orion_client):
        """GET with 404 should return None (not raise)."""
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _mock_response(status_code=404)

            entity = await orion_client.get_entity("urn:missing", "test_tenant")

            assert entity is None

    @pytest.mark.asyncio
    async def test_patch_entity_sends_patch_to_attrs(self, orion_client):
        """PATCH must go to /ngsi-ld/v1/entities/{id}/attrs."""
        with patch("httpx.AsyncClient.patch", new_callable=AsyncMock) as mock_patch:
            mock_resp = MagicMock()
            mock_resp.status_code = 204
            mock_patch.return_value = mock_resp

            attrs = {"temperature": {"type": "Property", "value": 25.5}}
            await orion_client.patch_entity("urn:x", attrs, "test_tenant")

            call_url = mock_patch.call_args[0][0]
            assert "/ngsi-ld/v1/entities/urn:x/attrs" in call_url

    @pytest.mark.asyncio
    async def test_delete_entity_sends_delete(self, orion_client):
        """DELETE must go to /ngsi-ld/v1/entities/{id}."""
        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_resp = MagicMock()
            mock_resp.status_code = 204
            mock_delete.return_value = mock_resp

            await orion_client.delete_entity("urn:x", "test_tenant")

            call_url = mock_delete.call_args[0][0]
            assert "/ngsi-ld/v1/entities/urn:x" in call_url

    @pytest.mark.asyncio
    async def test_query_entities_raises_orion_error_on_http_failure(self, orion_client):
        """HTTP errors must raise OrionLDError (wrapping httpx.HTTPError)."""
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            mock_resp.raise_for_status.side_effect = httpx.HTTPError(
                "400 Bad Request"
            )
            mock_get.return_value = mock_resp

            with pytest.raises(OrionLDError) as exc_info:
                await orion_client.query_entities("AgriParcel", "test_tenant")

            assert "Query entities failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_query_entities_passes_params(self, orion_client):
        """Query params (q, attrs, limit, offset) must be sent correctly."""
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _mock_response(json_data=[])

            await orion_client.query_entities(
                "AgriParcel", "test_tenant",
                q="name==test*", attrs="name,location", limit=50, offset=10,
            )

            params = mock_get.call_args[1]["params"]
            assert params["q"] == "name==test*"
            assert params["attrs"] == "name,location"
            assert params["limit"] == 50
            assert params["offset"] == 10
            assert params["type"] == "AgriParcel"

    @pytest.mark.asyncio
    async def test_create_entity_validates_required_fields(self, orion_client):
        """create_entity must raise ValueError on missing 'id' or 'type'."""
        with pytest.raises(ValueError, match="'id' field"):
            await orion_client.create_entity(
                {"type": "Test", "name": {"type": "Property", "value": "x"}},
                "test_tenant",
            )

        with pytest.raises(ValueError, match="'type' field"):
            await orion_client.create_entity(
                {"id": "urn:test", "name": {"type": "Property", "value": "x"}},
                "test_tenant",
            )

    @pytest.mark.asyncio
    async def test_create_entity_raises_orion_error_on_http_failure(self, orion_client):
        """HTTP errors on create must raise OrionLDError."""
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            mock_resp.raise_for_status.side_effect = httpx.HTTPError(
                "400 Bad Request"
            )
            mock_post.return_value = mock_resp

            entity = {
                "id": "urn:ngsi-ld:Test:001",
                "type": "Test",
                "name": {"type": "Property", "value": "test"},
            }
            with pytest.raises(OrionLDError) as exc_info:
                await orion_client.create_entity(entity, "test_tenant")

            assert "Create entity failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_patch_entity_raises_orion_error_on_http_failure(self, orion_client):
        """HTTP errors on patch must raise OrionLDError."""
        with patch("httpx.AsyncClient.patch", new_callable=AsyncMock) as mock_patch:
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            mock_resp.raise_for_status.side_effect = httpx.HTTPError(
                "400 Bad Request"
            )
            mock_patch.return_value = mock_resp

            with pytest.raises(OrionLDError) as exc_info:
                await orion_client.patch_entity(
                    "urn:x",
                    {"temp": {"type": "Property", "value": 25}},
                    "test_tenant",
                )

            assert "Patch entity failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_delete_entity_raises_orion_error_on_http_failure(self, orion_client):
        """HTTP errors on delete must raise OrionLDError."""
        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            mock_resp.raise_for_status.side_effect = httpx.HTTPError(
                "400 Bad Request"
            )
            mock_delete.return_value = mock_resp

            with pytest.raises(OrionLDError) as exc_info:
                await orion_client.delete_entity("urn:x", "test_tenant")

            assert "Delete entity failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_close_cleans_up_client(self, orion_client):
        """close() must clean up the internal HTTP client."""
        mock_client = AsyncMock()
        orion_client._client = mock_client

        await orion_client.close()

        mock_client.aclose.assert_awaited_once()
        assert orion_client._client is None
