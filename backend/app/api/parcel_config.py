from nkz_platform_sdk.auth import require_auth, AuthContext
"""Persistent per-parcel routing constraints (access point + no-go zones).

Stored as attributes on the AgriParcel entity in Orion-LD (source of truth).
NGSI-LD strict; writes go only through OrionClient (no direct DB writes).
"""
import logging
import httpx
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.services.parcel_constraints import _attr_value
from nkz_platform_sdk.orion import OrionClient


logger = logging.getLogger(__name__)
router = APIRouter(tags=["parcel-config"])


class ParcelConfig(BaseModel):
    accessPoint: dict | None = None
    exclusionZones: dict | None = None


def _orion(tenant_id: str) -> OrionClient:
    s = get_settings()
    return OrionClient(
        tenant_id=tenant_id,
        base_url=s.context_broker_url,
        context_url=s.ngsi_ld_context,
    )


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
        # Orion may return the module's terms as nkz: or full-IRI names.
        return {
            "accessPoint": _attr_value(entity, "accessPoint"),
            "exclusionZones": _attr_value(entity, "exclusionZones"),
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
    # Explicit null (present in the body) removes the attribute; absent leaves it.
    remove_access = "accessPoint" in body.model_fields_set and body.accessPoint is None
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
    if not attrs and not remove_access:
        raise HTTPException(status_code=400, detail="Nothing to update")
    orion = _orion(auth.tenant_id)
    try:
        if attrs:
            try:
                await orion.append_entity_attrs(parcel_id, attrs)
            except Exception as exc:
                logger.error("Orion-LD append_entity_attrs failed for %s: %s", parcel_id, exc)
                raise HTTPException(status_code=502, detail="Orion-LD error")
        removed: list[str] = []
        if remove_access:
            try:
                await orion.delete_entity_attr(parcel_id, "accessPoint")
                removed.append("accessPoint")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:  # already absent is fine
                    logger.error("Orion-LD delete accessPoint failed for %s: %s", parcel_id, exc)
                    raise HTTPException(status_code=502, detail="Orion-LD error")
            except Exception as exc:
                logger.error("Orion-LD delete accessPoint failed for %s: %s", parcel_id, exc)
                raise HTTPException(status_code=502, detail="Orion-LD error")
        return {"success": True, "updated": list(attrs.keys()), "removed": removed}
    finally:
        await orion.close()
