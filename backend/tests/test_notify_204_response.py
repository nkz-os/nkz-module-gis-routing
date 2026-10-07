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
    tenants were montiko/intiasa).
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
