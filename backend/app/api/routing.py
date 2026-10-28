from nkz_platform_sdk.auth import require_auth, AuthContext
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
import math
import os
import time
import io
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, Literal

import httpx
from app.services.sync_service import SyncService, SyncConflictError
from nkz_platform_sdk.notify_auth import accept_master_from_env, verify_notification
from nkz_platform_sdk.orion import OrionClient
from app.services.timescale_client import TimescaleDBClient
from app.services.export_service import RouteExporter
from app.services.pmtiles_generator import PMTileGenerator
from app.services.parcel_constraints import fetch_parcel_constraints
from app.api.pathfinding_router import build_dem_registry
from app.services.pathfinding.grid_sampler import make_grid_sampler
from app.config import get_settings
from app.services.machines import fetch_machine_kinematics
from app.services.coverage.errors import PlanError
from app.services.coverage.ladder import plan_with_fallbacks, LadderInput
from app.services.exclusion import validate_access_point
from app.services.routing.base import project_polygon_to_utm
from shapely.geometry import Point
from shapely.ops import transform as shp_transform


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


def _explicit_value(props: dict) -> dict:
    """Classification value as given: value, else mean_value, else (last resort) an explicit
    prescription_rate. A defaulted prescription_rate is never used as a value."""
    for key in ("value", "mean_value", "prescription_rate", "prescriptionRate"):
        raw = props.get(key)
        if raw in (None, ""):
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            return {"value": v}
    return {}


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
                    **_explicit_value(properties),
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
                    **_explicit_value(row),
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
async def list_parcels(request: Request, auth: AuthContext = require_auth()):
    """List AgriParcel entities for the authenticated tenant."""
    tenant_id = auth.tenant_id
    if not tenant_id or tenant_id == "default":
        raise HTTPException(status_code=404, detail="Tenant not found")
    settings = get_settings()
    orion = OrionClient(
        tenant_id,
        base_url=settings.context_broker_url,
        context_url=settings.ngsi_ld_context,
    )
    try:
        entities = await orion.query_entities(
            "AgriParcel", attrs="name,location,area,ownedBy,dateCreated",
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
async def get_parcel_geometry(request: Request, parcel_id: str, auth: AuthContext = require_auth()):
    """Get the full geometry (GeoJSON) of a specific AgriParcel."""
    tenant_id = auth.tenant_id
    if not tenant_id or tenant_id == "default":
        raise HTTPException(status_code=404, detail="Tenant not found")
    settings = get_settings()
    orion = OrionClient(
        tenant_id,
        base_url=settings.context_broker_url,
        context_url=settings.ngsi_ld_context,
    )
    try:
        entity = await orion.get_entity(parcel_id)
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
async def list_equipment(request: Request, auth: AuthContext = require_auth()):
    """List ManufacturingMachine entities (tractors/implements) for the tenant."""
    tenant_id = auth.tenant_id
    if not tenant_id or tenant_id == "default":
        raise HTTPException(status_code=404, detail="Tenant not found")
    settings = get_settings()
    orion = OrionClient(
        tenant_id,
        base_url=settings.context_broker_url,
        context_url=settings.ngsi_ld_context,
    )
    try:
        entities = await orion.query_entities(
            "ManufacturingMachine",
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
async def list_operations(request: Request, limit: int = 20, parcel_id: Optional[str] = None, auth: AuthContext = require_auth()):
    """List route operations (history) for the tenant from Orion-LD."""
    from app.services import operation_store
    tenant_id = auth.tenant_id
    settings = get_settings()
    orion = OrionClient(tenant_id, base_url=settings.context_broker_url,
                       context_url=settings.ngsi_ld_context)
    try:
        return await operation_store.list_operations(orion, tenant_id, parcel_id=parcel_id, limit=limit)
    except Exception as e:
        logger.error("Failed to list operations for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=502, detail="Operation store unavailable")
    finally:
        await orion.close()


@router.get("/operations/{operation_id}")
async def get_operation(request: Request, operation_id: str, auth: AuthContext = require_auth()):
    """Full operation detail incl. geometry and the inputs needed to re-run."""
    from app.services import operation_store
    tenant_id = auth.tenant_id
    settings = get_settings()
    orion = OrionClient(tenant_id, base_url=settings.context_broker_url,
                       context_url=settings.ngsi_ld_context)
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





def _build_sync_service(tenant_id: str) -> SyncService:
    settings = get_settings()
    orion = OrionClient(tenant_id=tenant_id, base_url=settings.context_broker_url,
                          context_url=settings.ngsi_ld_context)
    ts = TimescaleDBClient(dsn=settings.database_url)
    return SyncService(timescale=ts, orion=orion)


@router.get("/sync")
async def pull_changes(request: Request, collections: str = Query(..., description="Comma-separated collection names"),
    last_pulled_at: int = Query(..., description="Last sync timestamp epoch millis"),
    schema_version: int = Query(..., description="WatermelonDB schema version"),
        auth: AuthContext = require_auth()
):
    col_list = [c.strip() for c in collections.split(",") if c.strip()]
    invalid = set(col_list) - VALID_COLLECTIONS
    if invalid:
        raise HTTPException(status_code=400,
            detail={"error": {"code": "INVALID_COLLECTION",
                              "message": f"Unknown collection(s): {', '.join(sorted(invalid))}"}})
    tenant_id = auth.tenant_id
    sync_svc = _build_sync_service(tenant_id)
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
async def push_changes(request: Request, collections: str = Query(..., description="Comma-separated collection names"),
    auth: AuthContext = require_auth()
):
    col_list = [c.strip() for c in collections.split(",") if c.strip()]
    invalid = set(col_list) - VALID_COLLECTIONS
    if invalid:
        raise HTTPException(status_code=400,
            detail={"error": {"code": "INVALID_COLLECTION",
                              "message": f"Unknown collection(s): {', '.join(sorted(invalid))}"}})
    tenant_id = auth.tenant_id
    # Read raw body
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid JSON body")
    if not body or "changes" not in body:
        raise HTTPException(status_code=400,
            detail={"error": {"code": "INVALID_BODY",
                              "message": "Missing 'changes' in request body"}})
    sync_svc = _build_sync_service(tenant_id)
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
    model_config = ConfigDict(extra="forbid")

    heading_deg: Optional[float] = Field(default=None, ge=0, lt=360)
    width_m: float = Field(default=24, gt=0)
    overlap_pct: float = Field(default=0, ge=0, le=30)
    headland_passes: int = Field(default=1, ge=1, le=3)
    heading_objective: Literal["efficiency", "contour"] = "efficiency"
    turning_radius_m: Optional[float] = Field(default=None, gt=0)


class VRAClass(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_pct: float
    max_pct: float
    rate: float
    label: Optional[str] = Field(default=None, max_length=80)


class VRAConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    source: Literal["orion", "external"] = "orion"
    variable: str = Field(default="NDVI", max_length=40)
    classes: list[VRAClass] = Field(default_factory=list)
    unit: Literal["kg_ha", "l_ha"] = "kg_ha"
    product: str = Field(default="", max_length=80)
    invert: bool = False
    external_features: Optional[dict] = None


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parcel_geometry: dict
    parcel_id: Optional[str] = None
    tractor_id: Optional[str] = None
    implement_id: Optional[str] = None
    pattern: Literal[
        "auto", "boustrophedon", "snake", "spiral", "headland-only",
        "ab-line", "ab-skip",
    ] = "auto"
    pattern_config: PatternConfigRequest = Field(default_factory=PatternConfigRequest)
    operation_type: str = "spraying"
    return_to_access: bool = False
    planned_start_at: Optional[datetime] = None  # ISO 8601 with offset; stored as UTC "...Z"
    planned_end_at: Optional[datetime] = None
    persist: bool = True
    vra: Optional[VRAConfig] = None

    @field_validator("planned_start_at", "planned_end_at")
    @classmethod
    def planned_dates_are_utc(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("planned dates must carry a timezone offset (e.g. Z)")
        return value.astimezone(timezone.utc)


@router.post("/generate")
async def generate_routing_plan(request: Request, body: GenerateRequest, auth: AuthContext = require_auth()):
    """Unified route generation endpoint (Fields2Cover coverage engine)."""

    if body.parcel_geometry.get("type") != "Polygon":
        raise PlanError("INVALID_GEOMETRY", "parcel_geometry must be a GeoJSON Polygon")

    from shapely.geometry import shape
    from app.services.coverage.robot_model import build_robot
    from app.services.coverage.f2c_engine import CoverageConfig

    try:
        wgs84_poly = shape(body.parcel_geometry)
    except (ValueError, TypeError, KeyError) as exc:
        raise PlanError("INVALID_GEOMETRY", "parcel_geometry is not a valid polygon") from exc
    if not wgs84_poly.is_valid:
        wgs84_poly = wgs84_poly.buffer(0)
    if (not wgs84_poly.is_valid or wgs84_poly.is_empty or wgs84_poly.area == 0
            or wgs84_poly.geom_type != "Polygon"):
        raise PlanError("INVALID_GEOMETRY", "parcel_geometry is not a valid polygon")
    pc = body.pattern_config
    pattern = _PATTERN_ALIASES.get(body.pattern, body.pattern)

    machine = await _resolve_machine(body, auth)
    machine.setdefault("implementWidth", pc.width_m)
    robot = build_robot(
        machine,
        overlap_pct=pc.overlap_pct,
        turning_radius_override=pc.turning_radius_m,
    )

    cfg = CoverageConfig(
        pattern=pattern,
        heading_deg=pc.heading_deg,
        headland_passes=pc.headland_passes,
        heading_objective=pc.heading_objective,
        return_to_access=body.return_to_access,
    )
    # Wire DEM sampler when contour heading is requested.
    if pc.heading_objective == "contour":
        sampler, bbox = await _resolve_contour_dem(body.parcel_geometry)
        if sampler:
            cfg.dem_sampler = sampler
            cfg.parcel_bbox = bbox
    try:
        try:
            constraints = await _load_constraints_wgs84(body.parcel_id, auth.tenant_id)
        except PlanError:
            raise
        except ValueError as exc:
            # _zone_polygons: unreadable / malformed no-go zone on the parcel entity.
            logger.error("generate: invalid no-go zone configuration: parcel_id=%s error=%s",
                         body.parcel_id, exc)
            raise PlanError("INVALID_GEOMETRY",
                            f"parcel configuration has an invalid no-go zone: {body.parcel_id}") from exc
        access_wgs84 = constraints["access_point"]
        zones_wgs84 = constraints["zones"]

        parcel_utm, _crs, to_utm, to_wgs84 = project_polygon_to_utm(wgs84_poly)
        zones_utm = [shp_transform(to_utm, z) for z in zones_wgs84]
        access_utm = None
        if access_wgs84 is not None:
            access_utm = shp_transform(to_utm, Point(access_wgs84[0], access_wgs84[1]))
            validate_access_point(access_utm, parcel_utm, zones_utm, robot.cov_width / 2.0,
                                  to_wgs84=to_wgs84)

        # CPU-bound (Fields2Cover): keep it off the event loop.
        plan = await run_in_threadpool(
            plan_with_fallbacks,
            LadderInput(parcel_utm=parcel_utm, zones_utm=zones_utm, robot=robot, cfg=cfg,
                        access_utm=access_utm, wgs84_poly=wgs84_poly),
            time_budget_s=get_settings().LADDER_TIME_BUDGET_S)
        result = plan.to_route_result(to_wgs84, robot.cov_width)
        plan_dict = plan.as_api_dict(to_wgs84, robot.cov_width)
    except PlanError:
        raise
    except Exception as exc:
        logger.exception("generate: route generation failed (pattern=%s, parcel_id=%s)",
                         pattern, body.parcel_id)
        raise PlanError("ENGINE_FAILURE", "route generation failed", {}) from exc

    if body.vra and body.vra.enabled:
        prescription = await _build_vra_prescription(
            body.vra, parcel_id=body.parcel_id, tenant_id=auth.tenant_id,
            swaths_utm=plan.swaths, parcel_utm=parcel_utm, to_utm=to_utm, to_wgs=to_wgs84)
        plan_dict["prescription"] = prescription
        if plan_dict.get("validation") is None:
            plan_dict["validation"] = {"ok": True, "checks": [], "fallbacks_applied": [],
                                       "warnings": []}
        plan_dict["validation"]["warnings"].extend(
            {"code": w["code"], "geometry": None, "params": w["params"]}
            for w in prescription["warnings"])

    operation_id = None
    if body.persist and body.parcel_id:
        operation_id = await _persist_operation(result, body, auth, None, plan_dict)
    persisted = operation_id is not None

    return {
        "success": True,
        "operation_id": operation_id,
        "persisted": persisted,
        "plan": plan_dict,
    }


async def _vra_zones(vra: VRAConfig, parcel_id, tenant_id: str):
    from app.services.vra.zones import load_zones, external_zones
    if vra.source == "external":
        feats = (vra.external_features or {}).get("features")
        if not feats:
            raise PlanError("INVALID_VRA", "external source needs external_features")
        return external_zones(feats)
    if not parcel_id:
        raise PlanError("INVALID_VRA", "orion source needs a parcel_id")
    return await load_zones(tenant_id, parcel_id)


async def _build_vra_prescription(vra: VRAConfig, *, parcel_id, tenant_id: str, swaths_utm,
                                  parcel_utm, to_utm, to_wgs) -> dict:
    from app.services.vra.prescription import build_prescription
    zones, _missing = await _vra_zones(vra, parcel_id, tenant_id)
    return await run_in_threadpool(
        lambda: build_prescription(
            zones=zones, classes=[c.model_dump(exclude={"label"}) for c in vra.classes],
            unit=vra.unit, product=vra.product, invert=vra.invert, swaths_utm=swaths_utm,
            parcel_utm=parcel_utm, to_utm=to_utm, to_wgs=to_wgs))


async def _load_parcel_polygon(parcel_id: str, tenant_id: str):
    """WGS84 Polygon of an AgriParcel read from Orion."""
    from shapely.geometry import shape
    settings = get_settings()
    orion = OrionClient(tenant_id, base_url=settings.context_broker_url,
                        context_url=settings.ngsi_ld_context)
    try:
        entity = await orion.get_entity(parcel_id)
    finally:
        await orion.close()
    loc = ((entity or {}).get("location") or {}).get("value")
    try:
        poly = shape(loc)
    except Exception as exc:
        raise PlanError("INVALID_GEOMETRY", f"parcel geometry not found: {parcel_id}") from exc
    if poly.geom_type != "Polygon" or poly.is_empty:
        raise PlanError("INVALID_GEOMETRY", "parcel geometry must be a Polygon")
    return poly if poly.is_valid else poly.buffer(0)


class PrescriptionSwath(BaseModel):
    index: int
    kind: Literal["work", "headland"] = "work"
    geometry: dict


class PrescriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parcel_id: str
    swaths: list[PrescriptionSwath]
    vra: VRAConfig


@router.post("/prescription")
async def compute_prescription(body: PrescriptionRequest, auth: AuthContext = require_auth()):
    """Stateless class-based prescription for the given swaths (nothing is persisted)."""
    from shapely.geometry import shape
    from app.services.coverage.plan import Swath
    poly = await _load_parcel_polygon(body.parcel_id, auth.tenant_id)
    parcel_utm, _crs, to_utm, to_wgs84 = project_polygon_to_utm(poly)
    swaths = []
    for s in body.swaths:
        try:
            line = shape(s.geometry)
        except Exception as exc:
            raise PlanError("INVALID_GEOMETRY", f"swath {s.index} geometry is not valid") from exc
        if line.geom_type != "LineString":
            raise PlanError("INVALID_GEOMETRY", f"swath {s.index} must be a LineString")
        swaths.append(Swath(index=s.index, kind=s.kind, geometry=shp_transform(to_utm, line)))
    prescription = await _build_vra_prescription(
        body.vra, parcel_id=body.parcel_id, tenant_id=auth.tenant_id, swaths_utm=swaths,
        parcel_utm=parcel_utm, to_utm=to_utm, to_wgs=to_wgs84)
    return {"prescription": prescription}


async def _resolve_machine(body: GenerateRequest, auth: AuthContext) -> dict:
    """Fetch ManufacturingMachine kinematics for the implement (or tractor).

    Returns a dict of attribute values (implementWidth, trackWidth,
    minTurningRadius, steeringType). Empty dict when no id is provided.
    """
    machine_id = body.implement_id or body.tractor_id
    if not machine_id:
        return {}
    machine = await fetch_machine_kinematics(machine_id, auth.tenant_id)
    if not machine:
        # Never fall back to the request's default width for a machine that does not exist.
        raise PlanError("MACHINE_WIDTH_MISSING", f"machine not found: {machine_id}")
    return machine


# Re-export from the shared service so existing monkeypatches on
# `routing._fetch_parcel_constraints` continue to work (Task 7 tests).
_fetch_parcel_constraints = fetch_parcel_constraints


async def _load_constraints_wgs84(parcel_id, tenant_id: str) -> dict:
    """Access point (lon, lat) and exclusion zones (WGS84 polygons) of a parcel."""
    if not parcel_id:
        return {"access_point": None, "zones": []}
    c = await _fetch_parcel_constraints(parcel_id, tenant_id)
    return {"access_point": c["access_point"], "zones": list(c["zones"])}


async def _resolve_contour_dem(parcel_geometry: dict):
    """Return (sampler, bbox) for contour heading, or (None, None) if no DEM."""
    from shapely.geometry import shape
    poly = shape(parcel_geometry)
    bbox = poly.bounds  # (min_lon, min_lat, max_lon, max_lat)
    grid = await build_dem_registry().fetch_best(bbox, resolution_m=10)
    if not grid:
        return None, None
    return make_grid_sampler(grid), bbox


def _zones_from_orion(zones: list[dict], parcel_id: str, zone_ids: list[str] | None) -> list[dict]:
    matched = []
    for z in zones:
        ref = _relationship_target(z, "hasAgriParcel")
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


async def _persist_operation(result, body: GenerateRequest, auth: AuthContext,
                             prescription_map: dict | None, plan_dict: dict | None = None) -> Optional[str]:
    """Persist route as AgriParcelOperation in Orion-LD. Returns operation URN."""
    from app.services import operation_store
    tenant_id = auth.tenant_id
    settings = get_settings()
    op_id = operation_store.new_operation_id(tenant_id)
    entity = operation_store.build_operation_entity(
        op_id=op_id, body=body, result=result,
        prescription_map=prescription_map, is_template=False, plan=plan_dict,
        planned_start_at=_iso_utc(body.planned_start_at), planned_end_at=_iso_utc(body.planned_end_at),
    )
    orion = OrionClient(tenant_id, base_url=settings.context_broker_url,
                       context_url=settings.ngsi_ld_context)
    try:
        await orion.create_entity(entity)
        return op_id
    except Exception:
        # Reported to the client as persisted=false; the plan itself is still returned.
        logger.exception("Failed to persist operation: op_id=%s parcel_id=%s", op_id, body.parcel_id)
        return None
    finally:
        await orion.close()


def _iso_utc(value: Optional[datetime]) -> Optional[str]:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value is not None else None


class ExternalZonesIngestRequest(BaseModel):
    format: str = Field(default="geojson", description="Supported: geojson, csv")
    content: str = Field(..., description="Raw file contents")


@router.post("/zones/external/ingest")
async def ingest_external_zones(body: ExternalZonesIngestRequest, auth: AuthContext = require_auth()):
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
    from app.services.vra.zones import distribution, external_zones
    zones, missing = external_zones(out)
    return {
        "success": True,
        "data": {
            "count": len(out),
            "zones": out,
            "distribution": distribution(zones, missing, source="external", variable="value"),
        },
    }


@router.get("/tiles")
async def get_offline_tiles(request: Request, parcel_id: str = Query(..., description="Parcel entity ID"),
    auth: AuthContext = require_auth()
):
    tenant_id = auth.tenant_id
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
async def get_parcel_zones(request: Request, parcel_id: str, auth: AuthContext = require_auth()):
    """Fetch AgriManagementZone entities for a parcel from Orion-LD."""
    from app.services.vra.zones import load_zone_entities
    zones = await load_zone_entities(auth.tenant_id, parcel_id)

    matched = []
    for z in zones:
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


@router.get("/zones/{parcel_id}/distribution")
async def zone_distribution(parcel_id: str, source: Literal["orion"] = "orion",
                            variable: str = Query("NDVI", max_length=40),
                            auth: AuthContext = require_auth()):
    """Area-weighted value distribution of the parcel's current zones (5 % steps)."""
    from app.services.vra.zones import distribution, load_zones
    zones, missing = await load_zones(auth.tenant_id, parcel_id)
    return distribution(zones, missing, source=source, variable=variable)


@router.post("/zones/{parcel_id}/generate")
async def generate_vra_zones(request: Request, parcel_id: str, auth: AuthContext = require_auth()):
    """Trigger VRA zone generation via vegetation-prime backend (server-to-server proxy)."""
    tenant_id = auth.tenant_id
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid JSON body")
    n_zones = body.get("n_zones", 8) if isinstance(body, dict) else None
    if isinstance(n_zones, bool) or not isinstance(n_zones, int) or not 2 <= n_zones <= 12:
        raise HTTPException(status_code=422, detail="n_zones must be an integer from 2 to 12")

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
async def export_operation(request: Request, operation_id: str, format: str = Query("geojson", description="Export format: isoxml, geojson, gpx"),
    auth: AuthContext = require_auth()
):
    tenant_id = auth.tenant_id
    settings = get_settings()
    orion = OrionClient(
        tenant_id,
        base_url=settings.context_broker_url, context_url=settings.ngsi_ld_context
    )
    entity = await orion.get_entity(operation_id)
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


def _reject_unauthenticated_notify(headers) -> HTTPException | None:
    """Flag-gated auth for the Orion notification receiver (two-phase rollout).

    Accepts the token bound to this tenant and host (nkz_platform_sdk.notify_auth)
    and, until NKZ_NOTIFY_ACCEPT_MASTER is false, the master secret itself.
    """
    require = os.getenv("NOTIFY_REQUIRE_INTERNAL_SECRET", "").lower() in (
        "1", "true", "yes", "on"
    )
    if not require:
        return None
    if not verify_notification(
        headers,
        secret=os.getenv("INTERNAL_SERVICE_SECRET", ""),
        accept_master=accept_master_from_env(),
    ):
        return HTTPException(status_code=401, detail="missing or invalid notification credentials")
    return None


@router.post("/notify", status_code=204)
async def on_ngsild_notification(request: Request):
    """Receive NGSI-LD subscription notifications from Orion-LD.

    Called by Orion-LD when entities matching our subscriptions change.
    No JWT required — Orion-LD sends service-to-service notifications.

    Answers 204 with no body: Orion-LD looks for a capitalised "Content-Length:"
    with a case-sensitive strstr and only skips that check on a 204. uvicorn emits
    the header lower-cased, so any other success status is counted as a failed
    notification and deactivates the subscription after 3 consecutive hits.
    """
    reject = _reject_unauthenticated_notify(request.headers)
    if reject:
        raise reject

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid JSON body")
    # Orion-LD conveys the tenant of a notification via NGSILD-Tenant
    # (verified in production: telemetry-worker attributes rows to real tenants
    # from this header alone). Fiware-Service is kept only as a legacy fallback.
    tenant_id = (request.headers.get("NGSILD-Tenant")
                 or request.headers.get("FIWARE-Service"))
    if not tenant_id:
        # Fail closed: an anonymous notification cannot be attributed to a
        # tenant, and a silent "default" would mix tenants in the sync tables.
        raise HTTPException(status_code=400, detail="Missing NGSILD-Tenant header")
    data = body.get("data", [])

    if not data:
        return None

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
                # Extract constraints; notification may be partial so values may be None.
                # The UPSERT uses COALESCE so None will not overwrite an existing value.
                access_point = entity.get("accessPoint", {}).get("value")
                exclusion_zones = entity.get("exclusionZones", {}).get("value")
                await ts.materialize_parcel(
                    remote_id=eid, tenant_id=tenant_id, name=name,
                    geojson=geojson_str, area=area, crop_type=crop_type,
                    status=status, centroid_lat=float(centroid[1]) if len(centroid) > 1 else 0,
                    centroid_lng=float(centroid[0]), updated_at=updated_at,
                    access_point=json.dumps(access_point) if access_point else None,
                    exclusion_zones=json.dumps(exclusion_zones) if exclusion_zones else None)
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
                    parcel_id=(_relationship_target(entity, "hasAgriParcel")
                               or _relationship_target(entity, "refAgriParcel")),
                    equipment_id=None,
                    tractor_id=_relationship_target(entity, "usesTractor"),
                    implement_id=_relationship_target(entity, "usesImplement"),
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
    return None
