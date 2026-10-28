"""SDM Alert raised when an operation is saved, per the tenant's setting."""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from app.services.tenant_settings import dispatch_setting

logger = logging.getLogger(__name__)

ALERT_TYPE = "route_planned"
SEVERITY = {"immediate": "high", "digest": "medium"}


def build_alert(*, tenant_id: str, module_id: str, severity: str, operation_id: str,
                description: str) -> dict:
    return {
        "id": f"urn:ngsi-ld:Alert:{tenant_id}:{uuid.uuid4().hex}",
        "type": "Alert",
        "alertSource": {"type": "Property", "value": module_id},
        "category": {"type": "Property", "value": "agriculture"},
        "dateIssued": {"type": "Property", "value": {
            "@type": "DateTime", "@value": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}},
        # notifications watches `status` and routes by `alertType`.
        "status": {"type": "Property", "value": "active"},
        "alertType": {"type": "Property", "value": ALERT_TYPE},
        "severity": {"type": "Property", "value": severity},
        "description": {"type": "Property", "value": description},
        "refEntity": {"type": "Relationship", "object": operation_id},
    }


async def parcel_label(orion, parcel_id: Optional[str]) -> str:
    """Parcel name for the notice text; empty when it cannot be read (never an id)."""
    if not parcel_id:
        return ""
    try:
        entity = await orion.get_entity(parcel_id)
        node = (entity or {}).get("name")
        name = node.get("value") if isinstance(node, dict) else None
        return name if isinstance(name, str) else ""
    except Exception:
        return ""


async def notify_operation(orion_factory, *, tenant_id: str, module_id: str, operation_id: str,
                           operation_type: str, parcel_id: Optional[str]) -> str:
    """Returns "sent", "skipped" (setting none) or "failed". Never raises: the
    operation is already stored and the outcome is reported, not hidden."""
    orion = None
    try:
        setting = await dispatch_setting(tenant_id)
        severity = SEVERITY.get(setting)
        if severity is None:
            return "skipped"
        orion = orion_factory()
        label = await parcel_label(orion, parcel_id)
        description = f"Nueva ruta planificada: {operation_type}" + (f" · {label}" if label else "")
        await orion.create_entity(build_alert(
            tenant_id=tenant_id, module_id=module_id, severity=severity,
            operation_id=operation_id, description=description))
        return "sent"
    except Exception:
        logger.exception("Alert failed: operation_id=%s tenant_id=%s", operation_id, tenant_id)
        return "failed"
    finally:
        if orion is not None:
            try:
                await orion.close()
            except Exception:
                logger.warning("Orion client close failed", exc_info=True)
