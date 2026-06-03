"""Shared: read a parcel's routing constraints (access point + no-go zones) from Orion."""
from shapely.geometry import shape
from app.config import get_settings
from app.services.orion_client import OrionLDClient


async def fetch_parcel_constraints(parcel_id: str, tenant_id: str) -> dict:
    """Return {"access_point": (lon,lat)|None, "zones": [shapely Polygon, ...]}.

    Reads the AgriParcel entity's accessPoint (GeoProperty Point) and
    exclusionZones (Property holding a GeoJSON FeatureCollection) from Orion-LD.
    """
    settings = get_settings()
    orion = OrionLDClient(base_url=settings.context_broker_url,
                          context_url=settings.ngsi_ld_context)
    try:
        entity = await orion.get_entity(parcel_id, tenant_id)
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
