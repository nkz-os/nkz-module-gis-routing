"""
GIS Routing - Sync API with WatermelonDB protocol and route generation.

Provides WatermelonDB-compatible GET/POST /sync endpoints for delta-based
offline sync, plus the existing POST /routing/generate endpoint with
Orion-LD persistence.
"""

import hashlib
import csv
import json
import logging
import time
import io
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import JSONResponse
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel, Field
from typing import Optional, Literal

import httpx
from app.services.sync_service import SyncService, SyncConflictError
from app.services.orion_client import OrionLDClient
from app.services.timescale_client import TimescaleDBClient
from app.services.export_service import RouteExporter
from app.services.pmtiles_generator import PMTileGenerator
from app.config import get_settings
from app.api.deps import get_tenant_id

logger = logging.getLogger(__name__)
router = APIRouter(tags=["routing"])

_PATTERN_ALIASES = {"ab-line": "boustrophedon", "ab-skip": "snake"}


def _relationship_target(entity: dict, key: str) -> str:
    rel = entity.get(key, {}) or {}
    return str(rel.get("object") or rel.get("value") or "")


def _machine_role_from_category(category: str) -> str:
    value = (category or "").strip().lower()
    if value in {"tractor", "tractors", "vehicle", "power_unit"}:
        return "tractor"
    if value in {"implement", "apero", "tool", "attachment"}:
        return "implement"
    return "unknown"


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_external_zone_features(raw_features: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for idx, feat in enumerate(raw_features):
        if not isinstance(feat, dict):
            continue
        geometry = feat.get("geometry")
        if not isinstance(geometry, dict):
            continue
        properties = feat.get("properties", {}) or {}
        normalized.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "zone_id": properties.get("zone_id", properties.get("zoneId", f"ext-{idx + 1}")),
                    "zone_class": str(properties.get("zone_class", properties.get("zoneClass", "external"))),
                    "prescription_rate": _to_float(
                        properties.get("prescription_rate", properties.get("prescriptionRate", 1.0)),
                        1.0,
                    ),
                },
            }
        )
    return normalized


def _parse_external_zones_csv(content: str) -> list[dict]:
    """
    Expected columns: geometry (GeoJSON geometry as string), optional zone_id, zone_class, prescription_rate.
    """
    reader = csv.DictReader(io.StringIO(content))
    out: list[dict] = []
    for idx, row in enumerate(reader):
        geom_raw = (row.get("geometry") or "").strip()
        if not geom_raw:
            continue
        try:
            geometry = json.loads(geom_raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid CSV geometry at row {idx + 2}: {exc}",
            ) from exc
        out.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "zone_id": (row.get("zone_id") or f"csv-{idx + 1}").strip(),
                    "zone_class": (row.get("zone_class") or "external").strip(),
                    "prescription_rate": _to_float(row.get("prescription_rate"), 1.0),
                },
            }
        )
    return out


def _pick_trajectory_alternative(
    alternatives: list[dict],
    selected_alternative_id: Optional[str],
    heading_deg: float,
) -> dict:
    if selected_alternative_id:
        for alt in alternatives:
            if alt.get("id") == selected_alternative_id:
                return alt
    for alt in alternatives:
        if abs(float(alt.get("heading_deg", 0)) - heading_deg) < 0.01:
            return alt
    return alternatives[0]



@router.get("/health")
async def api_health_check():
    return {"status": "healthy", "service": "gis-routing", "version": get_settings().app_version}

@router.get("/parcels")
async def list_parcels(request: Request):
    """List AgriParcel entities for the authenticated tenant."""
    tenant_id = _get_tenant_id(request)
    if not tenant_id or tenant_id == "default":
        raise HTTPException(status_code=404, detail="Tenant not found")
    settings = get_settings()
    orion = OrionLDClient(
        base_url=settings.context_broker_url,
        context_url=settings.ngsi_ld_context,
    )
    try:
        entities = await orion.query_entities(
            "AgriParcel", tenant_id, attrs="name,location,area,ownedBy,dateCreated",
            limit=200,
        )
        return [
            {
                "id": e.get("id", ""),
                "name": (e.get("name", {}) or {}).get("value", ""),
                "location": (e.get("location", {}) or {}).get("value"),
                "area": (e.get("area", {}) or {}).get("value"),
                "ownedBy": (e.get("ownedBy", {}) or {}).get("object", ""),
            }
            for e in entities
        ]
    finally:
        await orion.close()

@router.get("/parcels/{parcel_id}/geometry")
async def get_parcel_geometry(request: Request, parcel_id: str):
    """Get the full geometry (GeoJSON) of a specific AgriParcel."""
    tenant_id = _get_tenant_id(request)
    if not tenant_id or tenant_id == "default":
        raise HTTPException(status_code=404, detail="Tenant not found")
    settings = get_settings()
    orion = OrionLDClient(
        base_url=settings.context_broker_url,
        context_url=settings.ngsi_ld_context,
    )
    try:
        entity = await orion.get_entity(parcel_id, tenant_id)
        if not entity:
            raise HTTPException(status_code=404, detail="Parcel not found")
        location_val = (entity.get("location", {}) or {}).get("value")
        if not location_val:
            raise HTTPException(status_code=404, detail="Parcel has no geometry")
        return {
            "id": entity.get("id", ""),
            "name": (entity.get("name", {}) or {}).get("value", ""),
            "geometry": location_val,
        }
    finally:
        await orion.close()

@router.get("/equipment")
async def list_equipment(request: Request):
    """List ManufacturingMachine entities (tractors/implements) for the tenant."""
    tenant_id = _get_tenant_id(request)
    if not tenant_id or tenant_id == "default":
        raise HTTPException(status_code=404, detail="Tenant not found")
    settings = get_settings()
    orion = OrionLDClient(
        base_url=settings.context_broker_url,
        context_url=settings.ngsi_ld_context,
    )
    try:
        entities = await orion.query_entities(
            "ManufacturingMachine", tenant_id,
            attrs=(
                "name,category,description,serialNumber,isobusCompatible,"
                "implementWidth,trackWidth,wheelbase,minTurningRadius,gpsOffsetX,gpsOffsetY,gpsOffsetZ,"
                "hitchType,hitchOffsetX,implementLength,implementOffsetX,steeringType,steeringAxles,dateCreated"
            ),
            limit=100,
        )
        return [
            {
                "id": e.get("id", ""),
                "name": (e.get("name", {}) or {}).get("value", ""),
                "category": (e.get("category", {}) or {}).get("value", ""),
                "machine_role": _machine_role_from_category((e.get("category", {}) or {}).get("value", "")),
                "description": (e.get("description", {}) or {}).get("value", ""),
                "serialNumber": (e.get("serialNumber", {}) or {}).get("value", ""),
                "isobusCompatible": (e.get("isobusCompatible", {}) or {}).get("value", False),
                "implementWidth": (e.get("implementWidth", {}) or {}).get("value"),
                "trackWidth": (e.get("trackWidth", {}) or {}).get("value"),
                "wheelbase": (e.get("wheelbase", {}) or {}).get("value"),
                "minTurningRadius": (e.get("minTurningRadius", {}) or {}).get("value"),
                "gpsOffsetX": (e.get("gpsOffsetX", {}) or {}).get("value"),
                "gpsOffsetY": (e.get("gpsOffsetY", {}) or {}).get("value"),
                "gpsOffsetZ": (e.get("gpsOffsetZ", {}) or {}).get("value"),
                "hitchType": (e.get("hitchType", {}) or {}).get("value"),
                "hitchOffsetX": (e.get("hitchOffsetX", {}) or {}).get("value"),
                "implementLength": (e.get("implementLength", {}) or {}).get("value"),
                "implementOffsetX": (e.get("implementOffsetX", {}) or {}).get("value"),
                "steeringType": (e.get("steeringType", {}) or {}).get("value"),
                "steeringAxles": (e.get("steeringAxles", {}) or {}).get("value"),
            }
            for e in entities
        ]
    finally:
        await orion.close()

@router.get("/operations")
async def list_operations(request: Request, limit: int = 20, parcel_id: Optional[str] = None):
    """List route operations (history) for the tenant from Orion-LD."""
    from app.services import operation_store
    tenant_id = _get_tenant_id(request)
    settings = get_settings()
    orion = OrionLDClient(settings.context_broker_url, settings.ngsi_ld_context)
    try:
        return await operation_store.list_operations(orion, tenant_id, parcel_id=parcel_id, limit=limit)
    except Exception as e:
        logger.error("Failed to list operations for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=502, detail="Operation store unavailable")
    finally:
        await orion.close()


@router.get("/operations/{operation_id}")
async def get_operation(request: Request, operation_id: str):
    """Full operation detail incl. geometry and the inputs needed to re-run."""
    from app.services import operation_store
    tenant_id = _get_tenant_id(request)
    settings = get_settings()
    orion = OrionLDClient(settings.context_broker_url, settings.ngsi_ld_context)
    try:
        detail = await operation_store.get_operation(orion, operation_id, tenant_id)
    except Exception as e:
        logger.error("Failed to get operation %s: %s", operation_id, e)
        raise HTTPException(status_code=502, detail="Operation store unavailable")
    finally:
        await orion.close()
    if detail is None:
        raise HTTPException(status_code=404, detail="Operation not found")
    return detail

VALID_COLLECTIONS = {"parcels", "equipment", "operations"}


_get_tenant_id = get_tenant_id


def _build_sync_service(request: Request) -> SyncService:
    settings = get_settings()
    orion = OrionLDClient(base_url=settings.context_broker_url,
                          context_url=settings.ngsi_ld_context)
    ts = TimescaleDBClient(dsn=settings.database_url)
    return SyncService(timescale=ts, orion=orion)


@router.get("/sync")
async def pull_changes(
    request: Request,
    collections: str = Query(..., description="Comma-separated collection names"),
    last_pulled_at: int = Query(..., description="Last sync timestamp epoch millis"),
    schema_version: int = Query(..., description="WatermelonDB schema version"),
):
    col_list = [c.strip() for c in collections.split(",") if c.strip()]
    invalid = set(col_list) - VALID_COLLECTIONS
    if invalid:
        raise HTTPException(status_code=400,
            detail={"error": {"code": "INVALID_COLLECTION",
                              "message": f"Unknown collection(s): {', '.join(sorted(invalid))}"}})
    tenant_id = _get_tenant_id(request)
    sync_svc = _build_sync_service(request)
    try:
        result = await sync_svc.pull(collections=col_list, tenant_id=tenant_id,
                                      last_pulled_at=last_pulled_at,
                                      schema_version=schema_version)
    except ValueError as e:
        msg = str(e)
        code = "INVALID_SCHEMA" if "INVALID_SCHEMA" in msg else "INVALID_COLLECTION"
        raise HTTPException(status_code=400,
                            detail={"error": {"code": code, "message": msg}})
    return JSONResponse(content=result)


@router.post("/sync")
async def push_changes(
    request: Request,
    collections: str = Query(..., description="Comma-separated collection names"),
):
    col_list = [c.strip() for c in collections.split(",") if c.strip()]
    invalid = set(col_list) - VALID_COLLECTIONS
    if invalid:
        raise HTTPException(status_code=400,
            detail={"error": {"code": "INVALID_COLLECTION",
                              "message": f"Unknown collection(s): {', '.join(sorted(invalid))}"}})
    tenant_id = _get_tenant_id(request)
    # Read raw body
    body = await request.json()
    if not body or "changes" not in body:
        raise HTTPException(status_code=400,
            detail={"error": {"code": "INVALID_BODY",
                              "message": "Missing 'changes' in request body"}})
    sync_svc = _build_sync_service(request)
    try:
        result = await sync_svc.push(collections=col_list, tenant_id=tenant_id,
                                      changes=body["changes"],
                                      last_pulled_at=body.get("last_pulled_at", 0))
    except ValueError as e:
        raise HTTPException(status_code=400,
            detail={"error": {"code": "INVALID_COLLECTION", "message": str(e)}})
    except SyncConflictError as e:
        raise HTTPException(status_code=409,
            detail={"error": {"code": "CONFLICT", "message": str(e),
                              "server_timestamp": e.server_timestamp}})
    return JSONResponse(content=result)


class PatternConfigRequest(BaseModel):
    heading_deg: Optional[float] = Field(default=None, ge=0, lt=360)
    width_m: float = Field(default=24, gt=0)
    overlap_pct: float = Field(default=0, ge=0, le=30)
    headland_passes: int = Field(default=0, ge=0, le=3)
    direction: Literal["inside-out", "outside-in"] = "outside-in"
    heading_objective: Literal["efficiency", "contour"] = "efficiency"
    turning_radius_m: Optional[float] = Field(default=None, gt=0)


class VRAConfig(BaseModel):
    enabled: bool = False
    source: Literal["vegetation-health", "orion", "external"] = "orion"
    base_rate: float = Field(default=100, gt=0)
    rate_unit: str = "l_ha"
    zone_ids: Optional[list[str]] = None
    external_features: Optional[list[dict]] = None


class GenerateRequest(BaseModel):
    parcel_geometry: dict
    parcel_id: Optional[str] = None
    tractor_id: Optional[str] = None
    implement_id: Optional[str] = None
    pattern: Literal[
        "boustrophedon", "snake", "spiral", "headland-only",
        "ab-line", "ab-skip",
    ] = "boustrophedon"
    pattern_config: PatternConfigRequest = Field(default_factory=PatternConfigRequest)
    operation_type: str = "spraying"
    coupling_model: str = "rigid"
    persist: bool = True
    selected_alternative_id: Optional[str] = None
    base_pattern_id: Optional[str] = None
    vra: Optional[VRAConfig] = None


@router.post("/generate")
async def generate_routing_plan(request: Request, body: GenerateRequest):
    """Unified route generation endpoint (Fields2Cover coverage engine)."""
    if body.parcel_geometry.get("type") != "Polygon":
        raise HTTPException(status_code=400, detail="parcel_geometry must be a GeoJSON Polygon")

    from shapely.geometry import shape, mapping as _map
    from app.services.coverage.robot_model import build_robot
    from app.services.coverage.f2c_engine import generate_coverage, CoverageConfig

    wgs84_poly = shape(body.parcel_geometry)
    pc = body.pattern_config
    pattern = _PATTERN_ALIASES.get(body.pattern, body.pattern)

    machine = await _resolve_machine(body, request)
    machine.setdefault("implementWidth", pc.width_m)
    try:
        robot = build_robot(
            machine,
            overlap_pct=pc.overlap_pct,
            turning_radius_override=pc.turning_radius_m,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    cfg = CoverageConfig(
        pattern=pattern,
        heading_deg=pc.heading_deg,
        headland_passes=pc.headland_passes,
        heading_objective=pc.heading_objective,
    )
    from app.services.exclusion import ExclusionError
    cov_kwargs = await _coverage_constraints(
        body.parcel_id, _get_tenant_id(request), robot.cov_width)
    try:
        result = generate_coverage(wgs84_poly, robot, cfg, **cov_kwargs)
    except ExclusionError as exc:
        raise HTTPException(status_code=422, detail=f"unroutable: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"route generation failed: {exc}")

    prescription_map = None
    if body.vra and body.vra.enabled:
        zone_features = await _resolve_vra_zones(body, request)
        if zone_features:
            from app.services.vra_intersector import intersect_swaths_with_zones
            prescription_map = intersect_swaths_with_zones(
                result.geometry, zone_features, body.vra.base_rate, pc.width_m,
            )

    operation_id = None
    if body.persist and body.parcel_id:
        operation_id = await _persist_operation(result, body, request, prescription_map)

    selected = {
        "pattern": result.pattern,
        "route": _map(result.geometry),
        "swath_count": result.swath_count,
        "headland_count": result.headland_count,
        "total_distance_m": result.total_distance_m,
        "pass_order": result.pass_order,
        "metrics": result.metrics,
        "metadata": result.metadata,
    }
    return {
        "success": True,
        "selected": selected,
        "prescription_map": prescription_map,
        "operation_id": operation_id,
    }


async def _resolve_machine(body: GenerateRequest, request: Request) -> dict:
    """Fetch ManufacturingMachine kinematics for the implement (or tractor).

    Returns a dict of attribute values (implementWidth, trackWidth,
    minTurningRadius, steeringType). Empty dict when no id is provided.
    """
    machine_id = body.implement_id or body.tractor_id
    if not machine_id:
        return {}
    tenant_id = _get_tenant_id(request)
    settings = get_settings()
    orion = OrionLDClient(
        base_url=settings.context_broker_url,
        context_url=settings.ngsi_ld_context,
    )
    try:
        entity = await orion.get_entity(machine_id, tenant_id)
    finally:
        await orion.close()
    if not entity:
        return {}
    keys = ("implementWidth", "trackWidth", "minTurningRadius", "steeringType")
    return {k: (entity.get(k, {}) or {}).get("value") for k in keys
            if entity.get(k) is not None}


async def _fetch_parcel_constraints(parcel_id: str, tenant_id: str) -> dict:
    """Read accessPoint + exclusionZones for a parcel from Orion. Empty if absent."""
    from shapely.geometry import shape
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


async def _coverage_constraints(parcel_id, tenant_id: str, cov_width: float) -> dict:
    """Build the exclusion kwargs for generate_coverage from a parcel's config."""
    if not parcel_id:
        return {}
    c = await _fetch_parcel_constraints(parcel_id, tenant_id)
    return {
        "start_point_wgs84": c["access_point"],
        "exclusion_zones_wgs84": c["zones"],
        "exclusion_buffer_m": cov_width / 2.0,
    }


async def _resolve_vra_zones(body: GenerateRequest, request: Request) -> list[dict]:
    """Resolve VRA zone features from the configured source.

    Both "orion" (default) and the legacy "vegetation-health" source resolve to
    Orion-LD AgriManagementZone entities. vegetation-prime persists its computed
    zones to Orion (the platform source of truth), so gis-routing reads them
    there rather than via a redundant cross-service HTTP call. (Re)computation is
    triggered explicitly via POST /zones/{parcel_id}/generate.
    """
    if body.vra.source == "external":
        return _normalize_external_zone_features(body.vra.external_features or [])

    # "orion" and legacy "vegetation-health" → Orion-LD AgriManagementZone
    settings = get_settings()
    orion = OrionLDClient(settings.context_broker_url, settings.ngsi_ld_context)
    try:
        zones = await orion.query_entities("AgriManagementZone", _get_tenant_id(request))
    finally:
        await orion.close()
    return _zones_from_orion(zones, body.parcel_id, body.vra.zone_ids if body.vra else None)


def _zones_from_orion(zones: list[dict], parcel_id: str, zone_ids: list[str] | None) -> list[dict]:
    matched = []
    for z in zones:
        ref = _relationship_target(z, "refAgriParcel")
        if parcel_id not in ref:
            continue
        if zone_ids and z["id"] not in zone_ids:
            continue
        loc = z.get("location", {}).get("value", {})
        if loc:
            matched.append({
                "type": "Feature",
                "geometry": loc,
                "properties": {
                    "zone_id": z.get("zoneId", {}).get("value", z["id"]),
                    "zone_class": z.get("zoneClass", {}).get("value", ""),
                    "prescription_rate": float(z.get("prescriptionRate", {}).get("value", 1.0)),
                },
            })
    return matched


async def _persist_operation(
    result, body: GenerateRequest, request: Request, prescription_map: dict | None,
) -> Optional[str]:
    """Persist route as AgriParcelOperation in Orion-LD. Returns operation URN."""
    from app.services import operation_store
    tenant_id = _get_tenant_id(request)
    settings = get_settings()
    op_id = operation_store.new_operation_id(tenant_id)
    entity = operation_store.build_operation_entity(
        op_id=op_id, body=body, result=result,
        prescription_map=prescription_map, is_template=False,
    )
    orion = OrionLDClient(settings.context_broker_url, settings.ngsi_ld_context)
    try:
        await orion.create_entity(entity, tenant_id)
        return op_id
    except Exception as e:
        logger.error("Failed to persist operation: %s", e)
        return None
    finally:
        await orion.close()


class ExternalZonesIngestRequest(BaseModel):
    format: str = Field(default="geojson", description="Supported: geojson, csv")
    content: str = Field(..., description="Raw file contents")


@router.post("/zones/external/ingest")
async def ingest_external_zones(body: ExternalZonesIngestRequest):
    fmt = (body.format or "geojson").strip().lower()
    if fmt not in {"geojson", "csv"}:
        raise HTTPException(status_code=400, detail="Unsupported format. Use geojson or csv.")
    if fmt == "geojson":
        try:
            parsed = json.loads(body.content)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid GeoJSON: {exc}") from exc
        features = parsed.get("features", []) if isinstance(parsed, dict) else []
        out = _normalize_external_zone_features(features)
    else:
        out = _parse_external_zones_csv(body.content)
    if not out:
        raise HTTPException(status_code=400, detail="No valid zone features found in external file.")
    return {
        "success": True,
        "data": {
            "count": len(out),
            "zones": out,
        },
    }


@router.get("/tiles")
async def get_offline_tiles(
    request: Request, parcel_id: str = Query(..., description="Parcel entity ID")
):
    tenant_id = _get_tenant_id(request)
    generator = PMTileGenerator()
    cached = generator.get_from_cache(tenant_id, parcel_id)
    if cached is not None:
        sha = hashlib.sha256(cached).hexdigest()
        return FastAPIResponse(
            content=cached,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{parcel_id}_basemap.pmtiles"',
                "X-File-Hash": f"sha256:{sha}",
                "X-Bounding-Box": "0,0,0,0",
                "Cache-Control": "public, max-age=86400",
            },
        )
    return JSONResponse(
        status_code=202,
        content={
            "message": "PMTiles generation started",
            "retry_after_seconds": 60,
        },
        headers={"Retry-After": "60"},
    )


# ── Zoning (AgriManagementZone via Orion-LD, generation via vegetation-prime proxy) ──


@router.get("/zones/{parcel_id}")
async def get_parcel_zones(request: Request, parcel_id: str):
    """Fetch AgriManagementZone entities for a parcel from Orion-LD."""
    tenant_id = _get_tenant_id(request)
    settings = get_settings()
    orion = OrionLDClient(base_url=settings.context_broker_url, context_url=settings.ngsi_ld_context)
    zones = await orion.query_entities("AgriManagementZone", tenant_id)
    await orion.close()

    matched = []
    for z in zones:
        ref = _relationship_target(z, "refAgriParcel")
        if parcel_id in ref:
            location = z.get("location", {}).get("value", {})
            matched.append({
                "id": z["id"],
                "zone_id": z.get("zoneId", {}).get("value", ""),
                "zone_class": z.get("zoneClass", {}).get("value", ""),
                "prescription_rate": z.get("prescriptionRate", {}).get("value", 1.0),
                "mean_value": z.get("meanValue", {}).get("value", 0),
                "area_ha": z.get("areaHa", {}).get("value", 0),
                "geometry": location,
            })
    return {"success": True, "data": {"parcel_id": parcel_id, "zones": matched, "count": len(matched)}}


@router.post("/zones/{parcel_id}/generate")
async def generate_vra_zones(request: Request, parcel_id: str):
    """Trigger VRA zone generation via vegetation-prime backend (server-to-server proxy)."""
    tenant_id = _get_tenant_id(request)
    body = await request.json()
    n_zones = body.get("n_zones", 3)

    # vegetation-prime performs its own JWT validation (Bearer/cookie) AND requires
    # X-Tenant-ID, so forward the caller's auth context. ASSUMPTION: the inbound
    # request carries a forwardable token (Authorization or nkz_token cookie) —
    # not guaranteed on gateway-injected-header paths; confirm before relying on it.
    fwd_headers = {"X-Tenant-ID": tenant_id}
    auth_header = request.headers.get("Authorization")
    if auth_header:
        fwd_headers["Authorization"] = auth_header
    elif request.cookies.get("nkz_token"):
        fwd_headers["Authorization"] = f"Bearer {request.cookies['nkz_token']}"
    user_id = request.headers.get("x-user-id")
    if user_id:
        fwd_headers["X-User-ID"] = user_id

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                f"http://vegetation-prime-api-service:8000/api/vegetation/jobs/zoning/{parcel_id}",
                json={"n_zones": n_zones},
                headers=fwd_headers,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            logger.error("vegetation-prime zoning proxy failed: %s", e)
            raise HTTPException(status_code=502, detail="Zone generation service unavailable")


@router.get("/export/{operation_id}")
async def export_operation(
    request: Request,
    operation_id: str,
    format: str = Query("geojson", description="Export format: isoxml, geojson, gpx"),
):
    tenant_id = _get_tenant_id(request)
    settings = get_settings()
    orion = OrionLDClient(
        base_url=settings.context_broker_url, context_url=settings.ngsi_ld_context
    )
    entity = await orion.get_entity(operation_id, tenant_id)
    await orion.close()
    if not entity:
        raise HTTPException(status_code=404, detail="Operation not found")
    location = entity.get("location", {}).get("value", {})
    op_record = {
        "id": entity["id"],
        "name": entity.get("name", {}).get("value", ""),
        "operation_type": entity.get("operationType", {}).get("value", ""),
        "ab_line_geojson": json.dumps(location) if location else "{}",
        "implement_width": entity.get("implementWidth", {}).get("value", 24.0),
        "vra_enabled": entity.get("vraEnabled", {}).get("value", False),
    }
    exporter = RouteExporter()
    if format == "isoxml":
        content = exporter.to_isoxml(op_record)
        return FastAPIResponse(
            content=content,
            media_type="application/xml",
            headers={
                "Content-Disposition": f'attachment; filename="{operation_id.rsplit(":", 1)[-1]}.xml"'
            },
        )
    elif format == "gpx":
        content = exporter.to_gpx(op_record)
        return FastAPIResponse(
            content=content,
            media_type="application/gpx+xml",
            headers={
                "Content-Disposition": f'attachment; filename="{operation_id.rsplit(":", 1)[-1]}.gpx"'
            },
        )
    else:
        content = exporter.to_geojson(op_record)
        return FastAPIResponse(
            content=content,
            media_type="application/geo+json",
            headers={
                "Content-Disposition": f'attachment; filename="{operation_id.rsplit(":", 1)[-1]}.geojson"'
            },
        )


@router.post("/notify")
async def on_ngsild_notification(request: Request):
    """Receive NGSI-LD subscription notifications from Orion-LD.

    Called by Orion-LD when entities matching our subscriptions change.
    No JWT required — Orion-LD sends service-to-service notifications.
    """
    settings = get_settings()
    if settings.module_management_key:
        secret = request.headers.get("X-Orion-Secret", "")
        if secret != settings.module_management_key:
            raise HTTPException(status_code=403, detail="Invalid shared secret")

    body = await request.json()
    tenant_id = request.headers.get("FIWARE-Service", "default")
    data = body.get("data", [])

    if not data:
        return {"status": "ok", "materialized": 0}

    settings = get_settings()
    ts = TimescaleDBClient(dsn=settings.database_url)
    await ts.connect()
    count = 0
    try:
        for entity in data:
            etype = entity.get("type", "")
            eid = entity.get("id", "")
            if not eid:
                continue

            if etype == "AgriParcel":
                location = entity.get("location", {}).get("value", {})
                geojson_str = json.dumps(location) if location else "{}"
                coords_list = location.get("coordinates", [[[0, 0]]]) if location else [[[0, 0]]]
                centroid = coords_list[0][0] if coords_list and coords_list[0] else [0, 0]
                name = str(entity.get("name", {}).get("value", eid))
                area = float(entity.get("area", {}).get("value", 0))
                crop_type = str(entity.get("category", {}).get("value", ""))
                status_val = str(entity.get("cropStatus", {}).get("value", "active"))
                status = "active" if status_val in ("growing", "active") else "fallow"
                updated_at = int(time.time() * 1000)
                await ts.materialize_parcel(
                    remote_id=eid, tenant_id=tenant_id, name=name,
                    geojson=geojson_str, area=area, crop_type=crop_type,
                    status=status, centroid_lat=float(centroid[1]) if len(centroid) > 1 else 0,
                    centroid_lng=float(centroid[0]), updated_at=updated_at)
                count += 1

            elif etype == "ManufacturingMachine":
                name = str(entity.get("name", {}).get("value", eid))
                category_val = str(entity.get("category", {}).get("value", "tractor"))
                eq_type = "tractor" if category_val == "tractor" else "implement"
                width = float(entity.get("implementWidth", {}).get("value", 0) or 3.0)
                status = str(entity.get("status", {}).get("value", "available"))
                steering = str(entity.get("steeringType", {}).get("value", "ackermann"))
                axles = str(entity.get("steeringAxles", {}).get("value", "front"))
                updated_at = int(time.time() * 1000)
                await ts.materialize_equipment(
                    remote_id=eid, tenant_id=tenant_id, name=name,
                    equipment_type=eq_type, implement_width=max(width, 1.0),
                    status=status, steering_type=steering, steering_axles=axles,
                    track_width=float(entity.get("trackWidth", {}).get("value", 0)),
                    wheelbase=float(entity.get("wheelbase", {}).get("value", 0)),
                    gps_offset_x=float(entity.get("gpsOffsetX", {}).get("value", 0)),
                    gps_offset_y=float(entity.get("gpsOffsetY", {}).get("value", 0)),
                    gps_offset_z=float(entity.get("gpsOffsetZ", {}).get("value", 0)),
                    hitch_type=str(entity.get("hitchType", {}).get("value", "none")),
                    hitch_offset_x=float(entity.get("hitchOffsetX", {}).get("value", 0)),
                    implement_length=float(entity.get("implementLength", {}).get("value", 0)),
                    implement_offset_x=float(entity.get("implementOffsetX", {}).get("value", 0)),
                    updated_at=updated_at)
                count += 1

            elif etype == "AgriParcelOperation":
                status = str(entity.get("status", {}).get("value", "planned"))
                updated_at = int(time.time() * 1000)
                prescription_map = None
                pm_attr = entity.get("prescriptionMap", {})
                if pm_attr:
                    pm_value = pm_attr.get("value")
                    prescription_map = json.dumps(pm_value) if pm_value else None
                await ts.materialize_operation(
                    remote_id=eid, tenant_id=tenant_id,
                    parcel_id=_relationship_target(entity, "refAgriParcel"),
                    equipment_id=None,
                    tractor_id=_relationship_target(entity, "refTractor"),
                    implement_id=_relationship_target(entity, "refImplement"),
                    operation_type=str(entity.get("operationType", {}).get("value", "")),
                    ab_line_geojson=json.dumps(entity.get("location", {}).get("value", {})),
                    implement_width=float(entity.get("implementWidth", {}).get("value", 24.0)),
                    status=status,
                    vra_enabled=bool(entity.get("vraEnabled", {}).get("value", False)),
                    prescription_map=prescription_map,
                    base_rate=float(entity.get("baseRate", {}).get("value", 0)) if entity.get("baseRate") else None,
                    rate_unit=str(entity.get("rateUnit", {}).get("value", "")) if entity.get("rateUnit") else None,
                    started_at=None, completed_at=None, updated_at=updated_at)
                count += 1
    finally:
        await ts.close()

    logger.info("Materialized %d entities for tenant %s from notification", count, tenant_id)
    return {"status": "ok", "materialized": count}
