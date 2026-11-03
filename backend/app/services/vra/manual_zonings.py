"""Manual zonings: polygons uploaded (KML/KMZ/GeoJSON/shapefile/ISOXML) or drawn on the map.

A manual zoning is saved as one run of AgriManagementZone entities with
``zoningMethod: manual``. It never becomes the VRA default (see zones.select_zoning);
it is used only when chosen, with one rate per zone.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.validation import make_valid

from app.config import get_settings
from app.services.coverage.errors import PlanError
from app.services.vra import external as ext
from app.services.vra.zones import ZONE_TYPE, area_ha, list_zonings
from nkz_platform_sdk.gis import GeoFileError, read_geofile
from nkz_platform_sdk.orion import OrionClient

logger = logging.getLogger(__name__)

FORMATS = ("kml", "kmz", "geojson", "shapefile", "isoxml", "drawn")
MAX_ZONES = 50
MAX_LABEL = 80
LABEL_KEYS = ("zoneLabel", "zone_label", "label", "name", "Name", "NAME", "treatment", "zone_id")


def _invalid(detail: str, **params) -> PlanError:
    return PlanError("ZONES_FILE_INVALID", detail, params)


def parse(fmt: str, content: str) -> tuple[list[dict], list[str]]:
    """Raw GeoJSON features (any geometry) and parser warnings, in file order."""
    if fmt not in FORMATS:
        raise _invalid("unsupported format", format=fmt)
    if fmt == "drawn":
        try:
            data = json.dumps(json.loads(content)).encode()
        except (TypeError, ValueError) as exc:
            raise _invalid("drawn zones are not valid GeoJSON") from exc
        fmt = "geojson"
    else:
        data = ext.decode_content(content)
    if fmt == "shapefile":
        return ext.parse_shapefile(data, require_value=False)
    if fmt == "isoxml":
        return ext.parse_isoxml(data)
    try:
        result = read_geofile(data, f"zones.{fmt}")
    except GeoFileError as exc:
        raise _invalid(str(exc)) from exc
    return list(result.features), list(result.warnings)


def _label(props: dict) -> str | None:
    for key in LABEL_KEYS:
        v = props.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()[:MAX_LABEL]
    return None


def _polygonal(geom):
    if geom.is_empty:
        return None
    if not geom.is_valid:
        geom = make_valid(geom)
    parts = [g for g in getattr(geom, "geoms", [geom]) if isinstance(g, (Polygon, MultiPolygon))]
    polys = [p for g in parts for p in (g.geoms if isinstance(g, MultiPolygon) else [g]) if not p.is_empty]
    if not polys:
        return None
    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


def preview(features: list[dict], parcel, warnings: list[str]) -> dict:
    """Accepted zones (rank = order among accepted) and rejected features with a reason.

    ``parcel`` is the parcel's WGS84 shapely polygon. A polygon is kept when its
    centroid lies in the parcel. Self-intersections are repaired, not reported.
    """
    zones, rejected = [], []
    for i, f in enumerate(features):
        geom = (f or {}).get("geometry") or {}
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            rejected.append({"index": i, "reason": "not_polygon"})
            continue
        try:
            g = _polygonal(shape(geom))
        except Exception:
            g = None
        if g is None:
            rejected.append({"index": i, "reason": "invalid_geometry"})
            continue
        if not parcel.covers(g.centroid):
            rejected.append({"index": i, "reason": "outside_parcel"})
            continue
        rank = len(zones) + 1
        zones.append({"rank": rank, "label": _label(f.get("properties") or {}) or f"Z{rank}",
                      "geometry": mapping(g), "area_m2": round(area_ha(g) * 10000.0, 1)})
    if len(zones) > MAX_ZONES:
        raise _invalid("too many zones", count=len(zones), max=MAX_ZONES)
    return {"zones": zones, "rejected": rejected, "warnings": warnings}


def zone_entities(tenant_id: str, parcel_id: str, zones: list[dict], labels: dict[int, str],
                  run_hex: str, now: datetime) -> tuple[str, list[dict]]:
    """Entities of one manual run; ids never collide with vegetation's ``{parcel}:Z`` prefix."""
    run_id = f"manual-{run_hex}"
    short = parcel_id.split(":")[-1]
    date = {"@type": "DateTime", "@value": now.astimezone(timezone.utc).isoformat()}
    out = []
    for z in zones:
        label = (labels.get(z["rank"]) or "").strip()[:MAX_LABEL] or z["label"]
        out.append({
            "id": f"urn:ngsi-ld:{ZONE_TYPE}:{tenant_id}:{short}:manual-{run_hex[:8]}-{z['rank']}",
            "type": ZONE_TYPE,
            "hasAgriParcel": {"type": "Relationship", "object": parcel_id},
            "location": {"type": "GeoProperty", "value": z["geometry"]},
            "zoningMethod": {"type": "Property", "value": "manual"},
            "zoningRunId": {"type": "Property", "value": run_id},
            "dateZoned": {"type": "Property", "value": date},
            "zoneLabel": {"type": "Property", "value": label},
            "zoneRank": {"type": "Property", "value": z["rank"]},
            "area": {"type": "Property", "value": z["area_m2"], "unitCode": "MTK"},
        })
    return run_id, out


def _client(tenant_id: str) -> OrionClient:
    settings = get_settings()
    return OrionClient(tenant_id, base_url=settings.context_broker_url,
                       context_url=settings.ngsi_ld_context)


async def save(tenant_id: str, parcel_id: str, entities: list[dict]) -> None:
    """Create every zone; on any failure remove the ones already created (no half runs)."""
    orion = _client(tenant_id)
    created: list[str] = []
    try:
        for e in entities:
            try:
                await orion.create_entity(e)
            except Exception as exc:
                logger.exception("manual zone write failed: tenant_id=%s parcel_id=%s zone=%s",
                                 tenant_id, parcel_id, e["id"])
                for eid in created:
                    try:
                        await orion.delete_entity(eid)
                    except Exception:
                        logger.warning("rollback delete failed: tenant_id=%s zone=%s", tenant_id, eid)
                raise PlanError("PERSIST_FAILED", "manual zoning could not be saved", {}) from exc
            created.append(e["id"])
    finally:
        await orion.close()


async def delete(tenant_id: str, parcel_id: str, run_id: str) -> int:
    """Delete a manual zoning; automatic zonings belong to their generator (409)."""
    zoning = next((z for z in await list_zonings(tenant_id, parcel_id) if z.run_id == run_id), None)
    if zoning is None:
        raise PlanError("ZONING_NOT_FOUND", "zoning not found for this parcel", {"run_id": run_id})
    if zoning.method != "manual":
        raise PlanError("ZONING_NOT_MANUAL", "only manual zonings can be deleted",
                        {"run_id": run_id, "method": zoning.method})
    orion = _client(tenant_id)
    try:
        for z in zoning.zones:
            await orion.delete_entity(z.id)
    except Exception as exc:
        logger.exception("manual zoning delete failed: tenant_id=%s parcel_id=%s run_id=%s",
                         tenant_id, parcel_id, run_id)
        raise PlanError("PERSIST_FAILED", "manual zoning could not be deleted", {}) from exc
    finally:
        await orion.close()
    return len(zoning.zones)


def new_run_hex() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
