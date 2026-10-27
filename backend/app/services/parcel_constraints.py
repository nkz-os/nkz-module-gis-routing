"""Shared: read a parcel's routing constraints (access point + no-go zones) from Orion."""
import logging

from shapely.geometry import Polygon, box, shape
from app.config import get_settings
from nkz_platform_sdk.orion import OrionClient

logger = logging.getLogger(__name__)


async def fetch_parcel_constraints(parcel_id: str, tenant_id: str) -> dict:
    """Return {"access_point": (lon,lat)|None, "zones": [shapely Polygon, ...]}.

    Reads the AgriParcel entity's accessPoint (GeoProperty Point) and
    exclusionZones (Property holding a GeoJSON FeatureCollection) from Orion-LD.
    """
    settings = get_settings()
    orion = OrionClient(tenant_id, base_url=settings.context_broker_url,
                       context_url=settings.ngsi_ld_context)
    try:
        entity = await orion.get_entity(parcel_id)
    finally:
        await orion.close()
    if not entity:
        return {"access_point": None, "zones": []}
    ap = (entity.get("accessPoint", {}) or {}).get("value")
    access_point = tuple(ap["coordinates"]) if ap and ap.get("coordinates") else None
    fc = (entity.get("exclusionZones", {}) or {}).get("value") or {}
    zones = [shape(f["geometry"]) for f in fc.get("features", [])
             if f.get("geometry", {}).get("type") == "Polygon"]
    return {"access_point": access_point, "zones": zones}


async def fetch_tenant_zones_in_bbox(tenant_id: str, bbox: tuple[float, float, float, float]) -> list[Polygon]:
    """No-go zones (WGS84) of the tenant's AgriParcels whose location intersects bbox."""
    settings = get_settings()
    orion = OrionClient(tenant_id, base_url=settings.context_broker_url,
                        context_url=settings.ngsi_ld_context)
    try:
        entities = await orion.query_entities(
            "AgriParcel", attrs="location,exclusionZones", limit=500)
    finally:
        await orion.close()
    area = box(*bbox)
    zones: list[Polygon] = []
    for ent in entities or []:
        loc = (ent.get("location", {}) or {}).get("value")
        if not loc or not shape(loc).intersects(area):
            continue
        fc = (ent.get("exclusionZones", {}) or {}).get("value") or {}
        zones.extend(shape(f["geometry"]) for f in fc.get("features", [])
                     if f.get("geometry", {}).get("type") == "Polygon")
    logger.info("tenant zones in bbox: tenant=%s parcels=%d zones=%d",
                tenant_id, len(entities or []), len(zones))
    return zones
