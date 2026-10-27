"""Shared: read a parcel's routing constraints (access point + no-go zones) from Orion."""
import logging

from shapely.geometry import MultiPolygon, Polygon, box, shape
from app.config import get_settings
from nkz_platform_sdk.orion import OrionClient

logger = logging.getLogger(__name__)

_PAGE_LIMIT = 500
_MAX_PAGES = 20


def _zone_polygons(fc: dict) -> list[Polygon]:
    """Polygons of a FeatureCollection; MultiPolygons are split. Unreadable geometry raises."""
    out: list[Polygon] = []
    for f in (fc or {}).get("features", []):
        geom = f.get("geometry") or {}
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        g = shape(geom)
        out.extend(g.geoms if isinstance(g, MultiPolygon) else [g])
    return out


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
    zones = _zone_polygons(fc)
    return {"access_point": access_point, "zones": zones}


async def fetch_tenant_zones_in_bbox(tenant_id: str, bbox: tuple[float, float, float, float]) -> list[Polygon]:
    """No-go zones (WGS84) of the tenant's AgriParcels whose location intersects bbox."""
    settings = get_settings()
    orion = OrionClient(tenant_id, base_url=settings.context_broker_url,
                        context_url=settings.ngsi_ld_context)
    entities: list[dict] = []
    try:
        for page in range(_MAX_PAGES):
            batch = await orion.query_entities(
                "AgriParcel", attrs="location,exclusionZones",
                limit=_PAGE_LIMIT, offset=page * _PAGE_LIMIT)
            entities.extend(batch or [])
            if len(batch or []) < _PAGE_LIMIT:
                break
        else:
            logger.warning("tenant zones: page cap reached tenant=%s pages=%d; later parcels ignored",
                           tenant_id, _MAX_PAGES)
    finally:
        await orion.close()
    area = box(*bbox)
    zones: list[Polygon] = []
    matched = 0
    for ent in entities:
        ent_id = ent.get("id")
        loc = (ent.get("location", {}) or {}).get("value")
        try:
            if not shape(loc).intersects(area):
                continue
        except Exception:
            # Cannot prove the parcel is outside the bbox: keep its zones (fail safe).
            logger.error("tenant zones: unreadable parcel location, including its zones: id=%s",
                         ent_id, exc_info=True)
        matched += 1
        fc = (ent.get("exclusionZones", {}) or {}).get("value") or {}
        try:
            zones.extend(_zone_polygons(fc))
        except Exception as exc:
            raise ValueError(f"unreadable exclusion zone geometry on {ent_id}: {exc}") from exc
    logger.info("tenant zones in bbox: tenant=%s parcels_total=%d parcels_in_bbox=%d zones=%d",
                tenant_id, len(entities), matched, len(zones))
    return zones
