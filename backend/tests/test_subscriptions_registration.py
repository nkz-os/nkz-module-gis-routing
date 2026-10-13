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


EM = "http://entity-manager-service:5000"
EM_TENANTS = f"{EM}/api/internal/modules/nkz-module-gis-routing/tenants"


def _installs(states, status=200):
    return respx.get(EM_TENANTS).mock(return_value=Response(
        status, json={"module_id": "nkz-module-gis-routing", "tenants": states}))


@respx.mock
async def test_existing_stale_subscriptions_are_patched_and_rearmed(monkeypatch):
    _installs({"tenant-a": "enabled"})
    post = respx.post(f"{ORION}/ngsi-ld/v1/subscriptions").mock(
        return_value=Response(409, json={"title": "AlreadyExists"})
    )
    patch = respx.patch(url__regex=rf"{ORION}/ngsi-ld/v1/subscriptions/.+").mock(
        return_value=Response(204)
    )

    result = await subscriptions.reconcile_once(subscriptions.build_registrar())

    assert result["ensured"]["converged"] == 3 and result["ensured"]["errors"] == []
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
async def test_platform_unavailable_touches_nothing():
    _installs({}, status=503)
    route = respx.route(url__startswith=ORION)

    result = await subscriptions.reconcile_once(subscriptions.build_registrar())

    assert result["skipped"] == "unavailable"
    assert not route.calls


@respx.mock
async def test_uninstalled_tenant_loses_only_these_subscriptions():
    _installs({"tenant-b": "disabled"})
    respx.get(f"{ORION}/ngsi-ld/v1/subscriptions").mock(return_value=Response(200, json=[]))
    delete = respx.delete(url__startswith=f"{ORION}/ngsi-ld/v1/subscriptions/").mock(
        return_value=Response(204)
    )

    result = await subscriptions.reconcile_once(subscriptions.build_registrar())

    assert {c.request.url.path.rsplit("/", 1)[-1] for c in delete.calls} == SUB_IDS
    assert result["removed"]["removed"] == 3


def test_tenants_come_from_the_platform_not_the_database():
    assert not hasattr(subscriptions, "installed_tenants")
    assert "tenant_installed_modules" not in inspect.getsource(subscriptions)


def test_registrar_is_one_per_process(monkeypatch):
    monkeypatch.setattr(subscriptions, "_registrar", None)
    assert subscriptions.get_registrar() is subscriptions.get_registrar()


def test_lifecycle_hint_route_requires_auth():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.post("/api/routing/internal/lifecycle").status_code == 401
    r = client.post("/api/routing/internal/lifecycle", headers={"X-Internal-Service-Secret": SECRET})
    assert r.status_code == 202


def test_subscriptions_carry_derived_tokens_when_flag_on(monkeypatch):
    """With NKZ_NOTIFY_DERIVED_TOKENS on, the broker stores a per-tenant token, not the master."""
    monkeypatch.setenv("NKZ_NOTIFY_DERIVED_TOKENS", "true")
    registrar = subscriptions.build_registrar()
    for sub in registrar._subs:
        info = registrar._body(sub, "tenant-a")["notification"]["endpoint"]["receiverInfo"]
        assert [i["key"] for i in info] == ["X-Notification-Token"]
        assert info[0]["value"] != SECRET
