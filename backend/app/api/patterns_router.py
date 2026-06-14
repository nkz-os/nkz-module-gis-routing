# backend/app/api/patterns_router.py
"""Route templates as AgriParcelOperation(isTemplate=true) in Orion-LD."""

import logging
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.config import get_settings
from app.services.orion_client import OrionLDClient, OrionLDError
from app.services import operation_store

logger = logging.getLogger(__name__)
router = APIRouter(tags=["patterns"])


def _get_tenant(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("x-tenant-id")
    if not tid or tid == "default":
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tid


def _orion() -> OrionLDClient:
    s = get_settings()
    return OrionLDClient(s.context_broker_url, s.ngsi_ld_context)


class SavePatternRequest(BaseModel):
    parcel_id: str
    name: str
    pattern_type: str
    pattern_config: dict
    route_geojson: str
    vra_prescription_map: Optional[dict] = None
    equipment_tractor_id: Optional[str] = None
    equipment_implement_id: Optional[str] = None
    source_operation_id: Optional[str] = None


@router.get("/patterns")
async def list_patterns(request: Request, parcel_id: str):
    tenant = _get_tenant(request)
    orion = _orion()
    try:
        data = await operation_store.list_templates(orion, tenant, parcel_id)
    except OrionLDError as exc:
        if exc.status_code == 404:
            # Tenant has no operations yet — this is not an error
            logger.info("No templates found for tenant %s (Orion 404)", tenant)
            data = []
        else:
            logger.error("Orion-LD error for tenant %s: %s", tenant, exc)
            raise HTTPException(status_code=502, detail="Template store unavailable")
    except Exception as exc:
        logger.error("Failed to list templates for tenant %s: %s", tenant, exc)
        raise HTTPException(status_code=502, detail="Template store unavailable")
    finally:
        await orion.close()
    return {"success": True, "data": data}


@router.get("/patterns/{pattern_id}")
async def get_pattern(request: Request, pattern_id: str):
    tenant = _get_tenant(request)
    orion = _orion()
    try:
        entity = await orion.get_entity(pattern_id, tenant)
    except Exception as exc:
        logger.error("Failed to get template %s: %s", pattern_id, exc)
        raise HTTPException(status_code=502, detail="Template store unavailable")
    finally:
        await orion.close()
    if not entity or not operation_store.is_template_entity(entity):
        raise HTTPException(status_code=404, detail="Pattern not found")
    return {"success": True, "data": operation_store.template_to_dict(entity)}


@router.post("/patterns")
async def save_pattern(request: Request, body: SavePatternRequest):
    tenant = _get_tenant(request)
    op_id = operation_store.new_operation_id(tenant)
    entity = operation_store.build_template_entity(
        op_id=op_id, parcel_id=body.parcel_id, name=body.name,
        pattern_type=body.pattern_type, pattern_config=body.pattern_config,
        route_geojson=body.route_geojson, vra_prescription_map=body.vra_prescription_map,
        equipment_tractor_id=body.equipment_tractor_id,
        equipment_implement_id=body.equipment_implement_id,
        source_operation_id=body.source_operation_id,
    )
    orion = _orion()
    try:
        await orion.create_entity(entity, tenant)
    except Exception as exc:
        logger.error("Failed to save template for tenant %s: %s", tenant, exc)
        raise HTTPException(status_code=502, detail="Template store unavailable")
    finally:
        await orion.close()
    return {"success": True, "data": {"id": op_id}}


@router.delete("/patterns/{pattern_id}")
async def delete_pattern(request: Request, pattern_id: str):
    tenant = _get_tenant(request)
    orion = _orion()
    try:
        entity = await orion.get_entity(pattern_id, tenant)
        if not entity or not operation_store.is_template_entity(entity):
            raise HTTPException(status_code=404, detail="Pattern not found")
        await orion.delete_entity(pattern_id, tenant)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to delete template %s: %s", pattern_id, exc)
        raise HTTPException(status_code=502, detail="Template store unavailable")
    finally:
        await orion.close()
    return {"success": True}
