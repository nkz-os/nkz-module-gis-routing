"""Contract: the Orion-LD notification endpoint must answer 204 with no body.

Orion-LD validates a notification response by looking for the literal string
``Content-Length:`` with a **case-sensitive** ``strstr`` and only skips that check
when the status is exactly 204::

    char* contentLenP = strstr(headers, "Content-Length:");
    if (contentLenP == NULL) { if (httpStatus != 204) -> notificationFailure(...) }

uvicorn/h11 emits response headers lower-cased (``content-length:``) — legal per
RFC 7230, invisible to that ``strstr``. So a 200 + body is counted as a failed
notification, and Orion deactivates the subscription after 3 consecutive failures.

The ``ManufacturingMachine`` subscription pointing at this service was already showing
``notification.status = failed`` (2/2 sent/failed) before this endpoint was fixed.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

EMPTY_NOTIFICATION = {
    "id": "urn:ngsi-ld:Notification:contract-test",
    "type": "Notification",
    "subscriptionId": "urn:ngsi-ld:subscription:contract-test",
    "notifiedAt": "2026-09-01T00:00:00Z",
    "data": [],
}


@pytest.fixture
def client():
    return TestClient(app)


def test_notification_endpoint_answers_204_without_body(client):
    response = client.post(
        "/api/routing/notify",
        json=EMPTY_NOTIFICATION,
        headers={"NGSILD-Tenant": "contract-test"},
    )

    assert response.status_code == 204, (
        f"/notify answered {response.status_code}; Orion-LD counts anything other than "
        "204 as a notification failure unless the response carries a capitalised "
        "'Content-Length:' header, which uvicorn never emits. Three consecutive "
        "failures deactivate the subscription."
    )
    assert response.content == b"", (
        f"/notify returned a body with 204: {response.content!r}. "
        "A body forces a content-length header and defeats the purpose."
    )


def test_notification_without_tenant_header_is_rejected(client):
    """Anonymous notifications must fail closed, never fall back to a fake tenant.

    Orion-LD conveys the tenant via NGSILD-Tenant. Before this contract the
    endpoint fell back to a literal "default" tenant and every notification
    from every tenant was materialized inside it, mixing tenants in the sync
    tables (7 parcels landed under 'default' in production while the real
    tenants were acmefarm/newtenant).
    """
    response = client.post("/api/routing/notify", json=EMPTY_NOTIFICATION)

    assert response.status_code == 400, (
        f"/notify without tenant answered {response.status_code}; a silent "
        "fallback tenant mixes tenants inside the sync tables."
    )


def test_notification_with_legacy_fiware_service_still_accepted(client):
    """Fiware-Service remains a supported fallback during the header transition."""
    response = client.post(
        "/api/routing/notify",
        json=EMPTY_NOTIFICATION,
        headers={"FIWARE-Service": "contract-test"},
    )

    assert response.status_code == 204


def test_derived_token_is_accepted_once_master_is_refused(client, monkeypatch):
    """The token bound to this tenant and host passes after the master is contracted;
    the master and a token of another tenant do not."""
    from nkz_platform_sdk.notify_auth import TOKEN_HEADER, notification_token

    monkeypatch.setenv("NOTIFY_REQUIRE_INTERNAL_SECRET", "true")
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "test-secret")
    monkeypatch.setenv("NKZ_NOTIFY_ACCEPT_MASTER", "false")
    url = "/api/routing/notify"
    # Starlette's TestClient sends Host: testserver; the token binds to that host.
    token = notification_token("test-secret", "tenant-a", "testserver")

    assert client.post(
        url, json=EMPTY_NOTIFICATION, headers={"NGSILD-Tenant": "tenant-a", TOKEN_HEADER: token}
    ).status_code == 204
    assert client.post(
        url, json=EMPTY_NOTIFICATION, headers={"NGSILD-Tenant": "tenant-b", TOKEN_HEADER: token}
    ).status_code == 401
    assert client.post(
        url, json=EMPTY_NOTIFICATION,
        headers={"NGSILD-Tenant": "tenant-a", "X-Internal-Service-Secret": "test-secret"},
    ).status_code == 401
