"""
Resolve in-progress AgriParcelOperation entities from Orion-LD (tenant scope).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.config import get_settings
from app.services.orion_client import OrionLDClient

logger = logging.getLogger(__name__)


def _property_str(entity: dict, key: str) -> str:
    val = entity.get(key) or {}
    raw = val.get("value")
    if isinstance(raw, dict) and "@value" in raw:
        return str(raw["@value"])
    return str(raw) if raw is not None else ""


def _relationship_target(entity: dict, key: str) -> str:
    rel = entity.get(key, {}) or {}
    return str(rel.get("object") or rel.get("value") or "")


async def find_in_progress_operations(tenant_id: str) -> list[dict[str, Any]]:
    """
    Return AgriParcelOperation entities whose status Property is in_progress.
    """
    settings = get_settings()
    orion = OrionLDClient(
        base_url=settings.context_broker_url,
        context_url=settings.ngsi_ld_context,
    )
    try:
        entities = await orion.query_entities(
            "AgriParcelOperation",
            tenant_id,
            attrs="status,operationType,refAgriParcel,startDate,name",
            limit=200,
        )
    finally:
        await orion.close()

    active: list[dict[str, Any]] = []
    for e in entities:
        st = _property_str(e, "status").lower().strip()
        if st == "in_progress":
            active.append(e)
    return active


async def find_other_active_operation_id(
    tenant_id: str, exclude_operation_id: Optional[str] = None
) -> Optional[str]:
    """
    If another operation is already in_progress, return its id (not exclude_operation_id).
    """
    for e in await find_in_progress_operations(tenant_id):
        eid = e.get("id") or ""
        if exclude_operation_id and eid == exclude_operation_id:
            continue
        return eid or None
    return None


def summarize_active(e: dict) -> dict[str, Any]:
    """Minimal DTO for web/mobile consumers."""
    started = _property_str(e, "startDate")
    return {
        "id": e.get("id", ""),
        "parcel_id": _relationship_target(e, "refAgriParcel"),
        "operation_type": _property_str(e, "operationType") or "spraying",
        "status": _property_str(e, "status") or "in_progress",
        "started_at": started or None,
        "name": _property_str(e, "name") or e.get("id", ""),
    }
