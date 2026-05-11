"""Pattern CRUD endpoints."""

import logging
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.config import get_settings
from app.services.timescale_client import TimescaleDBClient
from app.services.pattern_store import PatternStore

logger = logging.getLogger(__name__)
router = APIRouter(tags=["patterns"])


def _get_tenant(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("x-tenant-id")
    if not tid or tid == "default":
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tid


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
    settings = get_settings()
    ts = TimescaleDBClient(dsn=settings.database_url)
    store = PatternStore(ts)
    patterns = await store.list_for_parcel(tenant, parcel_id)
    return {"success": True, "data": patterns}


@router.get("/patterns/{pattern_id}")
async def get_pattern(request: Request, pattern_id: str):
    tenant = _get_tenant(request)
    settings = get_settings()
    ts = TimescaleDBClient(dsn=settings.database_url)
    store = PatternStore(ts)
    pattern = await store.get(tenant, pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return {"success": True, "data": pattern}


@router.post("/patterns")
async def save_pattern(request: Request, body: SavePatternRequest):
    tenant = _get_tenant(request)
    settings = get_settings()
    ts = TimescaleDBClient(dsn=settings.database_url)
    store = PatternStore(ts)
    pattern_id = await store.save(
        tenant_id=tenant, parcel_id=body.parcel_id, name=body.name,
        pattern_type=body.pattern_type, pattern_config=body.pattern_config,
        route_geojson=body.route_geojson,
        vra_prescription_map=body.vra_prescription_map,
        equipment_tractor_id=body.equipment_tractor_id,
        equipment_implement_id=body.equipment_implement_id,
        source_operation_id=body.source_operation_id,
    )
    return {"success": True, "data": {"id": pattern_id}}


@router.delete("/patterns/{pattern_id}")
async def delete_pattern(request: Request, pattern_id: str):
    tenant = _get_tenant(request)
    settings = get_settings()
    ts = TimescaleDBClient(dsn=settings.database_url)
    store = PatternStore(ts)
    deleted = await store.delete(tenant, pattern_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return {"success": True}
