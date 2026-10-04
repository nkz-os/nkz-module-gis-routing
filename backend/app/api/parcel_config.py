from nkz_platform_sdk.auth import require_auth, AuthContext
"""Persistent per-parcel routing constraints (access point + no-go zones).

Stored as attributes on the AgriParcel entity in Orion-LD (source of truth).
NGSI-LD strict; writes go only through OrionClient (no direct DB writes).
"""
import logging
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from nkz_platform_sdk.orion import OrionClient


logger = logging.getLogger(__name__)
router = APIRouter(tags=["parcel-config"])


class ParcelConfig(BaseModel):
    accessPoint: dict | None = None
    exclusionZones: dict | None = None


def _orion(tenant_id: str) -> OrionClient:
    s = get_settings()
    return OrionClient(tenant_id=tenant_id)


@router.get("/parcels/{parcel_id}/config")
async def get_parcel_config(request: Request, parcel_id: str, auth: AuthContext = require_auth()):
    """Get the persistent routing constraints for a parcel (accessPoint + exclusionZones)."""
    tenant_id = auth.tenant_id
    if not parcel_id.startswith("urn:ngsi-ld:"):
        raise HTTPException(status_code=400, detail="parcel_id must be an NGSI-LD URN")
    orion = _orion(auth.tenant_id)
    try:
        try:
            entity = await orion.get_entity(parcel_id)
        except Exception as exc:
            logger.error("Orion-LD get_entity failed for %s: %s", parcel_id, exc)
            raise HTTPException(status_code=502, detail="Orion-LD error")
        if not entity:
            raise HTTPException(status_code=404, detail="Parcel not found")
        return {
            "accessPoint": (entity.get("accessPoint") or {}).get("value"),
            "exclusionZones": (entity.get("exclusionZones") or {}).get("value"),
        }
    finally:
        await orion.close()


@router.put("/parcels/{parcel_id}/config")
async def put_parcel_config(request: Request, parcel_id: str, body: ParcelConfig, auth: AuthContext = require_auth()):
    """Persist routing constraints for a parcel into Orion-LD (source of truth)."""
    tenant_id = auth.tenant_id
    if not parcel_id.startswith("urn:ngsi-ld:"):
        raise HTTPException(status_code=400, detail="parcel_id must be an NGSI-LD URN")
    attrs: dict = {}
    if body.accessPoint is not None:
        if body.accessPoint.get("type") != "Point":
            raise HTTPException(
                status_code=400,
                detail="accessPoint must be a GeoJSON Point",
            )
        if "coordinates" not in body.accessPoint:
            raise HTTPException(
                status_code=400,
                detail="accessPoint must include coordinates",
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
    orion = _orion(auth.tenant_id)
    try:
        try:
            await orion.update_entity_attrs(parcel_id, attrs)
        except Exception as exc:
            logger.error("Orion-LD patch_entity failed for %s: %s", parcel_id, exc)
            raise HTTPException(status_code=502, detail="Orion-LD error")
        return {"success": True, "updated": list(attrs.keys())}
    finally:
        await orion.close()
