import pytest
from fastapi.testclient import TestClient

from app.main import create_app

URL = "/api/routing/settings"
ADMIN = {"X-User-Roles": "TenantAdmin"}


@pytest.fixture
def client():
    return TestClient(create_app())


def test_tenant_without_row_gets_immediate(client):
    r = client.get(URL)
    assert r.status_code == 200 and r.json() == {"dispatch_notification": "immediate"}


def test_admin_can_set_and_read_back(client, settings_store):
    r = client.put(URL, json={"dispatch_notification": "digest"}, headers=ADMIN)
    assert r.status_code == 200 and r.json() == {"dispatch_notification": "digest"}
    assert client.get(URL).json() == {"dispatch_notification": "digest"}
    assert settings_store.rows == {"tenant-a": "digest"}


def test_platform_admin_allowed(client):
    r = client.put(URL, json={"dispatch_notification": "none"},
                   headers={"X-User-Roles": "Farmer,PlatformAdmin"})
    assert r.status_code == 200


@pytest.mark.parametrize("roles", ["", "Farmer", "TechnicalConsultant"])
def test_non_admin_forbidden(client, settings_store, roles):
    r = client.put(URL, json={"dispatch_notification": "none"}, headers={"X-User-Roles": roles})
    assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN"
    assert settings_store.rows == {}


def test_invalid_value_rejected(client, settings_store):
    r = client.put(URL, json={"dispatch_notification": "sms"}, headers=ADMIN)
    assert r.status_code == 422 and r.json()["code"] == "INVALID_SETTING"
    assert settings_store.rows == {}


def test_settings_are_per_tenant(client):
    client.put(URL, json={"dispatch_notification": "none"}, headers=ADMIN)
    other = client.get(URL, headers={"X-Tenant-ID": "tenant-b"})
    assert other.json() == {"dispatch_notification": "immediate"}


def test_get_settings_db_failure_is_503_coded(client, settings_store):
    settings_store.fail = True
    r = client.get(URL)
    assert r.status_code == 503 and r.json()["code"] == "SETTINGS_UNAVAILABLE"


def test_put_settings_db_failure_is_503_coded(client, settings_store):
    settings_store.fail = True
    r = client.put(URL, json={"dispatch_notification": "none"}, headers=ADMIN)
    assert r.status_code == 503 and r.json()["code"] == "SETTINGS_UNAVAILABLE"


def test_lifespan_closes_the_settings_pool(settings_store, monkeypatch):
    import asyncio
    from app import main

    async def idle(*a, **k):
        await asyncio.sleep(3600)
    monkeypatch.setattr(main, "run_subscription_reconciler", idle)

    async def run():
        async with main.lifespan(main.app):
            assert settings_store.closed is False
    asyncio.run(run())
    assert settings_store.closed is True
