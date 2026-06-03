"""Persistent per-parcel routing constraints (access point + no-go zones).

Stored as attributes on the AgriParcel entity in Orion-LD (source of truth).
NGSI-LD strict; writes go only through OrionLDClient (no direct DB writes).
"""
import logging
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.services.orion_client import OrionLDClient
from app.api.routing import _get_tenant_id

logger = logging.getLogger(__name__)
router = APIRouter(tags=["parcel-config"])


class ParcelConfig(BaseModel):
    accessPoint: dict | None = None
    exclusionZones: dict | None = None


def _orion() -> OrionLDClient:
    s = get_settings()
    return OrionLDClient(base_url=s.context_broker_url, context_url=s.ngsi_ld_context)


@router.get("/parcels/{parcel_id}/config")
async def get_parcel_config(request: Request, parcel_id: str):
    """Get the persistent routing constraints for a parcel (accessPoint + exclusionZones)."""
    tenant_id = _get_tenant_id(request)
    orion = _orion()
    try:
        entity = await orion.get_entity(parcel_id, tenant_id)
        if not entity:
            raise HTTPException(status_code=404, detail="Parcel not found")
        return {
            "accessPoint": (entity.get("accessPoint") or {}).get("value"),
            "exclusionZones": (entity.get("exclusionZones") or {}).get("value"),
        }
    finally:
        await orion.close()


@router.put("/parcels/{parcel_id}/config")
async def put_parcel_config(request: Request, parcel_id: str, body: ParcelConfig):
    """Persist routing constraints for a parcel into Orion-LD (source of truth)."""
    tenant_id = _get_tenant_id(request)
    attrs: dict = {}
    if body.accessPoint is not None:
        if body.accessPoint.get("type") != "Point":
            raise HTTPException(
                status_code=400,
                detail="accessPoint must be a GeoJSON Point",
            )
        attrs["accessPoint"] = {"type": "GeoProperty", "value": body.accessPoint}
    if body.exclusionZones is not None:
        if body.exclusionZones.get("type") != "FeatureCollection":
            raise HTTPException(
                status_code=400,
                detail="exclusionZones must be a GeoJSON FeatureCollection",
            )
        attrs["exclusionZones"] = {"type": "Property", "value": body.exclusionZones}
    if not attrs:
        raise HTTPException(status_code=400, detail="Nothing to update")
    orion = _orion()
    try:
        await orion.patch_entity(parcel_id, attrs, tenant_id)
        return {"success": True, "updated": list(attrs.keys())}
    finally:
        await orion.close()
