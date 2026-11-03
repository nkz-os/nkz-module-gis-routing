"""Management-zone reading and distribution for class-based VRA."""
from __future__ import annotations

import logging
import math

from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform as shp_transform

from app.config import get_settings
from app.services.coverage.errors import PlanError
from app.services.routing.base import get_utm_crs
from app.services.vra.classify import ZoneValue, valid_zones, weighted_percentiles
from nkz_platform_sdk.gis import Zoning, default_zoning, group_zonings
from nkz_platform_sdk.orion import OrionClient

logger = logging.getLogger(__name__)

ZONE_TYPE = "AgriManagementZone"
_PAGE = 100
_MAX_PAGES = 100


def _prop(entity: dict, key: str):
    v = entity.get(key)
    if isinstance(v, dict):
        v = v.get("value", v.get("object"))
    if isinstance(v, dict) and "@value" in v:
        v = v["@value"]
    return v


def _finite(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def area_ha(geom) -> float:
    """Planar area in hectares of a WGS84 geometry (local UTM)."""
    if geom is None or geom.is_empty:
        return 0.0
    c = geom.centroid
    to_utm = Transformer.from_crs("EPSG:4326", get_utm_crs(c.x, c.y), always_xy=True).transform
    return shp_transform(to_utm, geom).area / 10000.0


async def _fetch_entities(tenant_id: str, parcel_id: str) -> list[dict]:
    settings = get_settings()
    orion = OrionClient(tenant_id, base_url=settings.context_broker_url,
                        context_url=settings.ngsi_ld_context)
    if '"' in parcel_id or "\\" in parcel_id:
        raise PlanError("INVALID_GEOMETRY", "parcel_id contains invalid characters")
    out: list[dict] = []
    seen: set[str] = set()
    try:
        for page in range(_MAX_PAGES):
            try:
                batch = await orion.query_entities(
                    ZONE_TYPE, q=f'hasAgriParcel=="{parcel_id}"',
                    limit=_PAGE, offset=page * _PAGE, options="sysAttrs")
            except Exception as exc:
                logger.exception("zone read failed: tenant_id=%s parcel_id=%s page=%d",
                                 tenant_id, parcel_id, page)
                raise PlanError("ZONES_UNAVAILABLE", "management zones could not be read",
                                {}) from exc
            for e in batch:
                eid = e.get("id")
                if eid in seen:
                    continue
                seen.add(eid)
                out.append(e)
            if len(batch) < _PAGE:
                break
        else:
            logger.warning("zone listing truncated: parcel_id=%s pages=%d", parcel_id, _MAX_PAGES)
    finally:
        await orion.close()
    return out


def select_zoning(zonings: list[Zoning], run_id: str | None) -> Zoning | None:
    """The chosen zoning, or the default (latest automatic) when ``run_id`` is None.

    A manual zoning is never the default. An unknown ``run_id`` is an error, never a
    silent fallback to another zoning.
    """
    if run_id is None:
        return default_zoning(zonings)
    for z in zonings:
        if z.run_id == run_id:
            return z
    raise PlanError("ZONING_NOT_FOUND", "zoning not found for this parcel", {"run_id": run_id})


async def list_zonings(tenant_id: str, parcel_id: str) -> list[Zoning]:
    """Every zoning of the parcel, most recent first."""
    return group_zonings(await _fetch_entities(tenant_id, parcel_id))


async def load_zone_entities(tenant_id: str, parcel_id: str,
                             run_id: str | None = None) -> list[dict]:
    """Zone entities of the chosen zoning (default: the latest automatic one)."""
    entities = await _fetch_entities(tenant_id, parcel_id)
    chosen = select_zoning(group_zonings(entities), run_id)
    if chosen is None:
        return []
    ids = {z.id for z in chosen.zones}
    return [e for e in entities if e.get("id") in ids]


def _zone_from_entity(e: dict) -> tuple[ZoneValue | None, str | None]:
    mean = _finite(_prop(e, "meanValue"))
    if mean is None:
        return None, "no_mean_value"
    loc = _prop(e, "location")
    try:
        geom = shape(loc)
    except Exception:
        return None, "no_geometry"
    if geom.is_empty:
        return None, "no_geometry"
    area = _finite(_prop(e, "areaHa"))
    if area is None or area <= 0:
        area = area_ha(geom)
    return ZoneValue(id=e.get("id", ""), mean=mean, area_ha=area, geometry=geom), None


def run_id_of(entities: list[dict]) -> str | None:
    """zoningRunId of the (already single-zoning) zones, or None when they carry none."""
    ids = sorted({str(_prop(e, "zoningRunId")) for e in entities if _prop(e, "zoningRunId")})
    return ids[-1] if ids else None


def zones_from_entities(entities: list[dict]) -> tuple[list[ZoneValue], list[dict]]:
    zones: list[ZoneValue] = []
    missing: list[dict] = []
    for e in entities:
        z, reason = _zone_from_entity(e)
        if z is None:
            missing.append({"id": e.get("id", ""), "reason": reason})
        else:
            zones.append(z)
    return zones, missing


async def load_zones(tenant_id: str, parcel_id: str,
                     run_id: str | None = None) -> tuple[list[ZoneValue], list[dict]]:
    return zones_from_entities(await load_zone_entities(tenant_id, parcel_id, run_id))


def external_value(props: dict) -> float | None:
    """Classification value of an external zone: value, else mean_value, else
    prescription_rate (last resort)."""
    for key in ("value", "mean_value", "prescription_rate"):
        v = _finite(props.get(key))
        if v is not None:
            return v
    return None


def external_zones(features: list[dict]) -> tuple[list[ZoneValue], list[dict]]:
    zones: list[ZoneValue] = []
    missing: list[dict] = []
    for i, f in enumerate(features or []):
        props = (f.get("properties") or {}) if isinstance(f, dict) else {}
        zid = str(props.get("zone_id") or props.get("zoneId") or f"ext-{i + 1}")
        mean = external_value(props)
        if mean is None:
            missing.append({"id": zid, "reason": "no_mean_value"})
            continue
        try:
            geom = shape(f.get("geometry"))
        except Exception:
            geom = None
        if geom is None or geom.is_empty:
            missing.append({"id": zid, "reason": "no_geometry"})
            continue
        zones.append(ZoneValue(id=zid, mean=mean, area_ha=area_ha(geom), geometry=geom))
    return zones, missing


def distribution(zones: list[ZoneValue], missing: list[dict], *, source: str,
                 variable: str) -> dict:
    ok = valid_zones(zones)
    return {
        "source": source,
        "variable": variable,
        "zones": [{"id": z.id, "mean": z.mean, "area_ha": round(z.area_ha, 4),
                   "geometry": mapping(z.geometry)} for z in ok],
        "missing": missing,
        "percentiles": weighted_percentiles(ok),
    }
