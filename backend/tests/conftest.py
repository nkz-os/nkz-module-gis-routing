import os
import pytest
from unittest.mock import patch

os.environ["REQUIRE_HMAC_SIGNATURE"] = "false"
os.environ["POSTGRES_URL"] = "postgresql://test:test@localhost:5432/test"

import fastapi.testclient

original_request = fastapi.testclient.TestClient.request

def patched_request(self, method, url, **kwargs):
    headers = kwargs.get("headers") or {}
    headers.setdefault("X-Tenant-ID", "tenant-a")
    headers.setdefault("X-User-ID", "user-1")
    kwargs["headers"] = headers
    return original_request(self, method, url, **kwargs)

fastapi.testclient.TestClient.request = patched_request



@pytest.fixture(autouse=True)
def _no_tenant_parcels(monkeypatch):
    """A-B reads the tenant's gated parcels from Orion; no broker in tests."""
    from app.api import pathfinding_router as pr

    async def none(tenant_id, bbox):
        return []

    monkeypatch.setattr(pr, "fetch_tenant_parcels_in_bbox", none, raising=False)


@pytest.fixture(autouse=True)
def _fresh_search_lock(monkeypatch):
    """A job abandoned with its event loop would keep the global search lock held."""
    import asyncio
    from app.api import pathfinding_router as pr

    monkeypatch.setattr(pr, "_SEARCH_LOCK", asyncio.Semaphore(1))
