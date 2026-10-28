"""Shared: read a parcel's routing constraints (access point + no-go zones) from Orion."""
import logging

import httpx
import shapely
from shapely.geometry import Polygon, box, shape
from app.config import get_settings
from nkz_platform_sdk.orion import OrionClient

logger = logging.getLogger(__name__)

_NKZ_NS = "https://nkz-os.org/ns/"
# Orion returns a term outside the @context as its full IRI; a writer may also use the nkz: prefix.
_ATTR_FORMS = ("{n}", "nkz:{n}", _NKZ_NS + "{n}")
_PAGE_LIMIT = 500
_MAX_PAGES = 20


def _attr_value(entity: dict, name: str):
    """Value of the module's own attribute `name`, whichever form Orion returns it in
    (short, nkz: prefixed, full IRI). None when absent."""
    for form in _ATTR_FORMS:
        node = entity.get(form.format(n=name))
        if isinstance(node, dict) and node.get("value") is not None:
            return node["value"]
    return None


def _flatten_polygons(geom) -> list[Polygon]:
    """Non-empty Polygon parts of a geometry (lines and points dropped)."""
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if hasattr(geom, "geoms"):
        return [p for g in geom.geoms for p in _flatten_polygons(g)]
    return []


def _zone_polygons(fc, entity_id: str | None = None) -> list[Polygon]:
    """Polygons of an exclusionZones FeatureCollection; MultiPolygons are split.

    An absent value ({} / None) means no zones. Anything else that is not a
    FeatureCollection, a feature without geometry or unreadable geometry raises
    ValueError naming the entity: a zone is never dropped silently. Invalid
    polygons (e.g. self-intersecting) are repaired with make_valid, which keeps
    all of their area (fail safe).
    """
    if not fc:
        return []
    if (not isinstance(fc, dict) or fc.get("type") != "FeatureCollection"
            or not isinstance(fc.get("features"), list)):
        raise ValueError(f"exclusionZones is not a GeoJSON FeatureCollection on {entity_id}")
    out: list[Polygon] = []
    for n, f in enumerate(fc["features"]):
        geom = f.get("geometry") if isinstance(f, dict) else None
        if not isinstance(geom, dict):
            raise ValueError(f"exclusion zone feature {n} has no geometry on {entity_id}")
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            logger.warning("exclusion zone feature ignored, not a polygon: id=%s feature=%d type=%s",
                           entity_id, n, geom.get("type"))
            continue
        try:
            g = shape(geom)
        except Exception as exc:
            raise ValueError(f"unreadable exclusion zone geometry on {entity_id}: {exc}") from exc
        if not g.is_valid:
            reason = shapely.is_valid_reason(g)
            parts = _flatten_polygons(shapely.make_valid(g))
            logger.warning("exclusion zone repaired with make_valid: id=%s feature=%d reason=%s parts=%d",
                           entity_id, n, reason, len(parts))
            out.extend(parts)
            continue
        out.extend(_flatten_polygons(g))
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
    ap = _attr_value(entity, "accessPoint")
    access_point = tuple(ap["coordinates"]) if ap and ap.get("coordinates") else None
    fc = _attr_value(entity, "exclusionZones") or {}
    zones = _zone_polygons(fc, entity_id=entity.get("id") or parcel_id)
    return {"access_point": access_point, "zones": zones}


async def _read_tenant_parcels(tenant_id: str) -> list[dict]:
    """All AgriParcel entities of the tenant (paginated), every attribute.

    No `attrs` filter on purpose: the gate and zone terms can arrive under several
    names that expand to the same IRI, and Orion-LD answers an `attrs` list that
    names one IRI twice with zero entities (200, no error) -- which would silently
    drop every no-go zone and fence from A-B.
    """
    settings = get_settings()
    orion = OrionClient(tenant_id, base_url=settings.context_broker_url,
                        context_url=settings.ngsi_ld_context)
    entities: list[dict] = []
    try:
        for page in range(_MAX_PAGES):
            batch = await orion.query_entities(
                "AgriParcel",
                limit=_PAGE_LIMIT, offset=page * _PAGE_LIMIT)
            entities.extend(batch or [])
            if len(batch or []) < _PAGE_LIMIT:
                break
        else:
            logger.warning("tenant parcels: page cap reached tenant=%s pages=%d; later parcels ignored",
                           tenant_id, _MAX_PAGES)
    except httpx.HTTPStatusError as exc:
        # A tenant with no entities yet is unknown to the broker: it has no parcels.
        if exc.response.status_code == 404 or (
                exc.response.status_code == 400 and "NonExistingTenant" in exc.response.text):
            logger.info("tenant parcels: tenant unknown to the broker, no parcels: tenant=%s", tenant_id)
            return []
        raise
    finally:
        await orion.close()
    return entities


async def fetch_tenant_parcels_in_bbox(tenant_id: str, bbox: tuple[float, float, float, float]) -> list[dict]:
    """The tenant's AgriParcels intersecting bbox.

    Each item: {id, name, polygon (shapely, WGS84), geometry (GeoJSON), access_point
    (lon, lat)|None, zones (shapely Polygons)}. A parcel whose location cannot be
    read is kept with polygon/geometry None: it cannot be drawn or fenced, but its
    no-go zones still count (fail safe).
    """
    entities = await _read_tenant_parcels(tenant_id)
    area = box(*bbox)
    out: list[dict] = []
    for ent in entities:
        ent_id = ent.get("id")
        loc = (ent.get("location", {}) or {}).get("value")
        try:
            geom = shape(loc)
            if geom.is_empty or not geom.intersects(area):
                continue
        except Exception:
            logger.error("tenant parcels: unreadable parcel location, keeping its zones only: id=%s",
                         ent_id, exc_info=True)
            geom, loc = None, None
        ap = _attr_value(ent, "accessPoint")
        access_point = None
        if isinstance(ap, dict) and isinstance(ap.get("coordinates"), (list, tuple)) and len(ap["coordinates"]) >= 2:
            access_point = (float(ap["coordinates"][0]), float(ap["coordinates"][1]))
        fc = _attr_value(ent, "exclusionZones") or {}
        try:
            zones = _zone_polygons(fc, entity_id=ent_id)
        except Exception as exc:
            raise ValueError(f"unreadable exclusion zone geometry on {ent_id}: {exc}") from exc
        out.append({
            "id": ent_id,
            "name": (ent.get("name", {}) or {}).get("value", ""),
            "polygon": geom,
            "geometry": loc,
            "access_point": access_point,
            "zones": zones,
        })
    logger.info("tenant parcels in bbox: tenant=%s parcels_total=%d parcels_in_bbox=%d",
                tenant_id, len(entities), len(out))
    return out


async def fetch_tenant_zones_in_bbox(tenant_id: str, bbox: tuple[float, float, float, float]) -> list[Polygon]:
    """No-go zones (WGS84) of the tenant's AgriParcels whose location intersects bbox."""
    parcels = await fetch_tenant_parcels_in_bbox(tenant_id, bbox)
    return [z for p in parcels for z in p["zones"]]
