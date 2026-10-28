import pytest

from app.services import alerts
from tests.test_operations_save_api import (  # noqa: F401  (fixtures and helpers)
    PARCEL, URL, _Orion, _job, _plan, client)


def _alerts():
    return list(_Orion.alerts)


def _ops():
    return [e for e in _Orion.created if e["type"] == "AgriParcelOperation"]


def test_build_alert_matches_sdm_shape():
    a = alerts.build_alert(tenant_id="tenant-a", module_id="mod", severity="high",
                           operation_id="urn:ngsi-ld:AgriParcelOperation:x", description="d")
    assert a["id"].startswith("urn:ngsi-ld:Alert:tenant-a:") and a["type"] == "Alert"
    assert a["alertSource"]["value"] == "mod" and a["category"]["value"] == "agriculture"
    assert a["dateIssued"]["value"]["@value"].endswith("Z")
    assert a["severity"]["value"] == "high"
    assert a["refEntity"] == {"type": "Relationship",
                              "object": "urn:ngsi-ld:AgriParcelOperation:x"}
    assert "subCategory" not in a


def test_default_setting_sends_high_alert(client):
    r = client.post(URL, json={"kind": "plan", "plan_id": _plan(client)})
    b = r.json()
    assert b["alert"] == "sent"
    (a,) = _alerts()
    assert a["severity"]["value"] == "high"
    assert a["refEntity"]["object"] == b["operation_id"]
    assert a["description"]["value"].startswith("Nueva ruta planificada: ")


def test_digest_is_medium(client, settings_store):
    settings_store.rows["tenant-a"] = "digest"
    assert client.post(URL, json={"kind": "plan", "plan_id": _plan(client)}).json()["alert"] == "sent"
    assert _alerts()[0]["severity"]["value"] == "medium"


def test_none_skips(client, settings_store):
    settings_store.rows["tenant-a"] = "none"
    b = client.post(URL, json={"kind": "plan", "plan_id": _plan(client)}).json()
    assert b["alert"] == "skipped" and _alerts() == [] and len(_ops()) == 1


def test_idempotent_repeat_emits_one_alert(client):
    body = {"kind": "plan", "plan_id": _plan(client)}
    a = client.post(URL, json=body).json()
    b = client.post(URL, json=body).json()
    assert a == b and len(_alerts()) == 1


def test_orion_failure_on_alert_keeps_operation(client, monkeypatch):
    real = _Orion.create_entity

    async def flaky(self, entity):
        if entity["type"] == "Alert":
            raise RuntimeError("down")
        return await real(self, entity)
    monkeypatch.setattr(_Orion, "create_entity", flaky)
    r = client.post(URL, json={"kind": "plan", "plan_id": _plan(client)})
    b = r.json()
    assert r.status_code == 200 and b["persisted"] is True and b["alert"] == "failed"
    assert len(_ops()) == 1


def test_settings_store_failure_reports_failed(client, settings_store):
    settings_store.fail = True
    b = client.post(URL, json={"kind": "plan", "plan_id": _plan(client)}).json()
    assert b["persisted"] is True and b["alert"] == "failed" and len(_ops()) == 1


def test_transit_save_alerts_once(client):
    body = {"kind": "transit", "job_id": _job(), "alternative_id": "fastest", "parcel_id": PARCEL}
    a = client.post(URL, json=body).json()
    b = client.post(URL, json=body).json()
    assert a["alert"] == "sent" and a == b and len(_alerts()) == 1


def test_generate_persist_alerts(client):
    r = client.post("/api/routing/generate", json={
        "parcel_geometry": {"type": "Polygon", "coordinates": [[
            [-2.0, 43.0], [-1.99754, 43.0], [-1.99754, 43.0009], [-2.0, 43.0009], [-2.0, 43.0]]]},
        "parcel_id": PARCEL, "pattern": "boustrophedon",
        "pattern_config": {"width_m": 20, "headland_passes": 1, "turning_radius_m": 6.0},
        "persist": True})
    b = r.json()
    assert b["persisted"] is True and b["alert"] == "sent" and len(_alerts()) == 1


def test_generate_without_persist_has_no_alert(client):
    _plan(client)
    assert _alerts() == []
