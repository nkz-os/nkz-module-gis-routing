"""
NGSI-LD client for Orion-LD Context Broker.

All operations inject tenant isolation headers (NGSILD-Tenant, FIWARE-Service)
as required by the platform architecture. The @context is sent via Link header
for application/json content type.

Usage:
    client = OrionLDClient(
        base_url="http://orion-service:1026",
        context_url="http://api-gateway:5000/ngsi-ld-context.json",
    )
    entities = await client.query_entities("AgriParcel", tenant_id="my_tenant")
    await client.close()
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class OrionLDError(Exception):
    """Orion-LD operation error."""


class OrionLDClient:
    """Async HTTP client for Orion-LD Context Broker with NGSI-LD compliance."""

    def __init__(self, base_url: str, context_url: str):
        self.base_url = base_url.rstrip("/")
        self.context_url = context_url
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-initialized HTTP client with timeout."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        return self._client

    def _headers(self, tenant_id: str) -> dict:
        """Build NGSI-LD mandatory headers for tenant isolation."""
        import re
        if '\n' in tenant_id or '\r' in tenant_id:
            raise ValueError("Invalid tenant_id: contains newline characters")
        n = tenant_id.lower().strip().replace('-', '_').replace(' ', '_')
        n = re.sub(r'[^a-z0-9_]', '', n)
        n = n.strip('_') or tenant_id
        return {
            "Content-Type": "application/json",
            "Link": (
                f'<{self.context_url}>; '
                'rel="http://www.w3.org/ns/json-ld#context"; '
                'type="application/ld+json"'
            ),
            "NGSILD-Tenant": n,
            "FIWARE-Service": n,
            "Fiware-ServicePath": "/",
        }

    async def query_entities(
        self,
        entity_type: str,
        tenant_id: str,
        q: Optional[str] = None,
        attrs: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict]:
        """Query entities by type with optional filtering.

        Args:
            entity_type: FIWARE entity type (e.g. AgriParcel).
            tenant_id: Tenant identifier for isolation headers.
            q: NGSI-LD query string (e.g. "name==test*").
            attrs: Comma-separated attribute names to return.
            limit: Maximum number of entities (default 1000).
            offset: Pagination offset.

        Returns:
            List of entity dicts.
        """
        client = await self._get_client()
        url = f"{self.base_url}/ngsi-ld/v1/entities"
        params: dict = {
            "type": entity_type,
            "limit": limit,
            "offset": offset,
        }
        if q:
            params["q"] = q
        if attrs:
            params["attrs"] = attrs

        try:
            resp = await client.get(
                url, headers=self._headers(tenant_id), params=params
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            body = ""
            if 'resp' in dir() and hasattr(resp, 'text'):
                try:
                    body = resp.text[:1000]
                except Exception:
                    pass
            logger.error(
                "Orion-LD query entities failed [status=%s]: %s",
                getattr(resp, 'status_code', '?'), body,
            )
            raise OrionLDError(f"Query entities failed: {e}") from e

    async def get_entity(
        self, entity_id: str, tenant_id: str
    ) -> Optional[dict]:
        """Get a single entity by its ID.

        Args:
            entity_id: Full entity URN (e.g. urn:ngsi-ld:AgriParcel:001).
            tenant_id: Tenant identifier for isolation headers.

        Returns:
            Entity dict, or None if 404.
        """
        client = await self._get_client()
        url = f"{self.base_url}/ngsi-ld/v1/entities/{entity_id}"

        try:
            resp = await client.get(url, headers=self._headers(tenant_id))
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            body = ""
            if 'resp' in dir() and hasattr(resp, 'text'):
                try:
                    body = resp.text[:1000]
                except Exception:
                    pass
            logger.error(
                "Orion-LD get entity failed [status=%s]: %s",
                getattr(resp, 'status_code', '?'), body,
            )
            raise OrionLDError(f"Get entity failed: {e}") from e

    async def create_entity(
        self, entity: dict, tenant_id: str
    ) -> str:
        """Create a new NGSI-LD entity.

        Args:
            entity: Full NGSI-LD entity payload.
            tenant_id: Tenant identifier for isolation headers.

        Returns:
            Entity ID string extracted from the Location header.

        Raises:
            ValueError: If entity dict is missing 'id' or 'type'.
            OrionLDError: On HTTP failure.
        """
        if 'id' not in entity:
            raise ValueError("Entity payload must contain 'id' field")
        if 'type' not in entity:
            raise ValueError("Entity payload must contain 'type' field")

        client = await self._get_client()
        url = f"{self.base_url}/ngsi-ld/v1/entities"

        try:
            resp = await client.post(
                url, json=entity, headers=self._headers(tenant_id)
            )
            resp.raise_for_status()
            location = resp.headers.get("Location", "")
            if location:
                return location.rsplit("/", 1)[-1]
            return entity["id"]
        except httpx.HTTPError as e:
            body = ""
            if 'resp' in dir() and hasattr(resp, 'text'):
                try:
                    body = resp.text[:1000]
                except Exception:
                    pass
            logger.error(
                "Orion-LD create entity failed [status=%s]: %s",
                getattr(resp, 'status_code', '?'), body,
            )
            raise OrionLDError(f"Create entity failed: {e}") from e

    async def patch_entity(
        self, entity_id: str, attrs: dict, tenant_id: str
    ) -> None:
        """Partial update of entity attributes.

        Args:
            entity_id: Full entity URN.
            attrs: NGSI-LD attribute fragment (e.g. {"temperature": {"type": "Property", "value": 25}}).
            tenant_id: Tenant identifier for isolation headers.
        """
        client = await self._get_client()
        url = f"{self.base_url}/ngsi-ld/v1/entities/{entity_id}/attrs"

        try:
            resp = await client.patch(
                url, json=attrs, headers=self._headers(tenant_id)
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            body = ""
            if 'resp' in dir() and hasattr(resp, 'text'):
                try:
                    body = resp.text[:1000]
                except Exception:
                    pass
            logger.error(
                "Orion-LD patch entity failed [status=%s]: %s",
                getattr(resp, 'status_code', '?'), body,
            )
            raise OrionLDError(f"Patch entity failed: {e}") from e

    async def delete_entity(self, entity_id: str, tenant_id: str) -> None:
        """Delete an entity by ID.

        Args:
            entity_id: Full entity URN.
            tenant_id: Tenant identifier for isolation headers.
        """
        client = await self._get_client()
        url = f"{self.base_url}/ngsi-ld/v1/entities/{entity_id}"

        try:
            resp = await client.delete(
                url, headers=self._headers(tenant_id)
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            body = ""
            if 'resp' in dir() and hasattr(resp, 'text'):
                try:
                    body = resp.text[:1000]
                except Exception:
                    pass
            logger.error(
                "Orion-LD delete entity failed [status=%s]: %s",
                getattr(resp, 'status_code', '?'), body,
            )
            raise OrionLDError(f"Delete entity failed: {e}") from e

    async def close(self):
        """Close the underlying HTTP client session."""
        if self._client:
            await self._client.aclose()
            self._client = None
