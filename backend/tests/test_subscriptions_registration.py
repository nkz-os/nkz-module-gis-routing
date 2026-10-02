"""The module registers its own Orion-LD subscriptions and converges stale ones.

Regression: subscriptions created by the old manual script kept a retired auth
header after the notify endpoint switched to X-Internal-Service-Secret. Every
notification was rejected and Orion paused them; nothing ever corrected them.
"""

import inspect
import json
import re

import pytest
import respx
from httpx import Response

from app.api import routing
from app.config import get_settings
from app.services import subscriptions

ORION = "http://orion-ld-service:1026"
SECRET = "test-internal-secret"
SUB_IDS = {
    f"urn:ngsi-ld:Subscription:gis-routing:{t}"
    for t in ("AgriParcel", "ManufacturingMachine", "AgriParcelOperation")
}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", SECRET)
    monkeypatch.setenv("CONTEXT_BROKER_URL", ORION)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_declared_types_are_exactly_the_ones_the_handler_materializes():
    handled = set(re.findall(r'etype == "(\w+)"', inspect.getsource(routing.on_ngsild_notification)))
    assert set(subscriptions.ENTITY_TYPES) == handled


def test_subscription_ids_keep_the_existing_broker_identity():
    """Same ids the script created, so existing subscriptions are converged, not duplicated."""
    registrar = subscriptions.build_registrar()
    assert {registrar._subscription_id(s) for s in registrar._subs} == SUB_IDS


def test_subscriptions_carry_the_internal_secret_and_notify_uri():
    registrar = subscriptions.build_registrar()
    for sub in registrar._subs:
        endpoint = registrar._body(sub)["notification"]["endpoint"]
        assert endpoint["uri"] == get_settings().notify_url
        assert endpoint["receiverInfo"] == [{"key": "X-Internal-Service-Secret", "value": SECRET}]


def test_no_registration_without_the_secret(monkeypatch):
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET")
    assert subscriptions.build_registrar() is None


async def _tenants():
    return ["tenant-a"]


@respx.mock
async def test_existing_stale_subscriptions_are_patched_and_rearmed(monkeypatch):
    monkeypatch.setattr(subscriptions, "installed_tenants", _tenants)
    post = respx.post(f"{ORION}/ngsi-ld/v1/subscriptions").mock(
        return_value=Response(409, json={"title": "AlreadyExists"})
    )
    patch = respx.patch(url__regex=rf"{ORION}/ngsi-ld/v1/subscriptions/.+").mock(
        return_value=Response(204)
    )

    result = await subscriptions.reconcile_once(subscriptions.build_registrar())

    assert result["converged"] == 3 and result["errors"] == []
    assert len(post.calls) == 3
    patched = {}
    for call in patch.calls:
        sub_id = call.request.url.path.rsplit("/", 1)[-1]
        patched[sub_id] = json.loads(call.request.content)
        assert call.request.headers["NGSILD-Tenant"] == "tenant-a"
    assert set(patched) == SUB_IDS
    for body in patched.values():
        assert body["isActive"] is True
        assert body["notification"]["endpoint"]["receiverInfo"] == [
            {"key": "X-Internal-Service-Secret", "value": SECRET}
        ]


@respx.mock
async def test_tenant_lookup_failure_touches_nothing(monkeypatch):
    async def boom():
        raise OSError("db down")

    monkeypatch.setattr(subscriptions, "installed_tenants", boom)
    route = respx.route(url__startswith=ORION)

    assert await subscriptions.reconcile_once(subscriptions.build_registrar()) is None
    assert not route.calls


async def test_installed_tenants_only_enabled_installs_of_this_module(monkeypatch):
    seen = {}

    class FakeConn:
        async def fetch(self, sql, *args):
            seen["sql"], seen["args"] = sql, args
            return [{"tenant_id": "tenant-b"}, {"tenant_id": "tenant-a"}]

        async def close(self):
            seen["closed"] = True

    async def fake_connect(dsn):
        return FakeConn()

    monkeypatch.setenv("DATABASE_URL", "postgresql://u@db/x")
    get_settings.cache_clear()
    monkeypatch.setattr(subscriptions.asyncpg, "connect", fake_connect)

    assert await subscriptions.installed_tenants() == ["tenant-a", "tenant-b"]
    assert "tenant_installed_modules" in seen["sql"]
    assert "is_enabled" in seen["sql"]
    assert seen["args"] == ("nkz-module-gis-routing",)
    assert seen["closed"]
