import os
import pytest
from unittest.mock import patch

os.environ["REQUIRE_HMAC_SIGNATURE"] = "false"
os.environ["POSTGRES_URL"] = "postgresql://test:test@localhost:5432/test"

import fastapi.testclient

original_request = fastapi.testclient.TestClient.request

_PORTALS = []


def _keep_event_loop_alive(client):
    """A-B jobs are background tasks that hop to worker threads. With one portal per request the
    loop is torn down as soon as the response is sent and an unfinished job is abandoned; one
    portal for the client's lifetime lets jobs finish between the polls (like the real server).
    No lifespan is run (it would start the Orion reconciler)."""
    if client.portal is None:
        import anyio.from_thread
        cm = anyio.from_thread.start_blocking_portal(**client.async_backend)
        client.portal = cm.__enter__()
        _PORTALS.append(cm)


def pytest_sessionfinish(session, exitstatus):
    while _PORTALS:
        _PORTALS.pop().__exit__(None, None, None)


def patched_request(self, method, url, **kwargs):
    _keep_event_loop_alive(self)
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


class MemorySettingsStore:
    """In-memory tenant_settings store; no Postgres in unit tests."""

    def __init__(self):
        self.rows = {}
        self.fail = False

    async def get_dispatch(self, tenant_id):
        if self.fail:
            raise RuntimeError("db down")
        return self.rows.get(tenant_id)

    async def put_dispatch(self, tenant_id, value, user_id):
        self.rows[tenant_id] = value


@pytest.fixture(autouse=True)
def settings_store():
    from app.services import tenant_settings
    store = MemorySettingsStore()
    tenant_settings.set_store(store)
    yield store
    tenant_settings.set_store(None)
