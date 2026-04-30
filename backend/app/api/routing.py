"""
GIS Routing - Sync API with WatermelonDB protocol and route generation.

Provides WatermelonDB-compatible GET/POST /sync endpoints for delta-based
offline sync, plus the existing POST /routing/generate endpoint with
Orion-LD persistence.
"""

import json
import logging
import time
import uuid
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional

from app.services.sync_service import SyncService, SyncConflictError
from app.services.geometry import generate_swaths
from app.services.orion_client import OrionLDClient
from app.services.timescale_client import TimescaleDBClient
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["routing"])

VALID_COLLECTIONS = {"parcels", "equipment", "operations"}


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None)
    if not tid or tid == "default":
        raise HTTPException(status_code=404,
            detail={"error": {"code": "TENANT_NOT_FOUND",
                              "message": "Tenant not found or token missing tenant_id claim"}})
    return tid


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


# Keep existing generate endpoint -- it works with the geometry engine
class GenerateRequest(BaseModel):
    parcel_geometry: dict = Field(..., description="GeoJSON Polygon WGS84")
    start_point: list[float] = Field(..., description="[lon, lat] A-B reference point")
    heading_deg: float = Field(..., ge=0, lt=360)
    width_m: float = Field(..., gt=0)
    parcel_id: Optional[str] = None
    tractor_id: Optional[str] = None
    implement_id: Optional[str] = None
    operation_type: Optional[str] = "spraying"
    persist: bool = True


@router.post("/generate")
async def generate_routing_plan(request: Request, body: GenerateRequest):
    if body.parcel_geometry.get("type") != "Polygon":
        raise HTTPException(status_code=400,
                            detail="parcel_geometry must be a GeoJSON Polygon")
    try:
        from shapely.geometry import mapping
        multi_line_string = generate_swaths(
            geojson_polygon=body.parcel_geometry, start_point=body.start_point,
            heading_deg=body.heading_deg, width_m=body.width_m)
        geojson_result = mapping(multi_line_string)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    swath_count = len(geojson_result.get("coordinates", []))
    operation_id = None

    if body.persist and body.parcel_id:
        tenant_id = _get_tenant_id(request)
        settings = get_settings()
        orion = OrionLDClient(base_url=settings.context_broker_url,
                              context_url=settings.ngsi_ld_context)
        op_remote_id = (
            f"urn:ngsi-ld:AgriParcelOperation:{tenant_id}:"
            f"{uuid.uuid4().hex[:8]}"
        )
        entity = {
            "id": op_remote_id,
            "type": "AgriParcelOperation",
            "name": {
                "type": "Property",
                "value": f"{body.operation_type} - {body.parcel_id[:8]}",
            },
            "operationType": {"type": "Property", "value": body.operation_type},
            "status": {"type": "Property", "value": "planned"},
            "location": {"type": "GeoProperty", "value": geojson_result},
            "implementWidth": {"type": "Property", "value": body.width_m},
            "swathCount": {"type": "Property", "value": swath_count},
            "dateCreated": {
                "type": "Property",
                "value": {
                    "@type": "DateTime",
                    "@value": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
            },
        }
        if body.tractor_id:
            entity["refTractor"] = {"type": "Relationship", "value": body.tractor_id}
        if body.implement_id:
            entity["refImplement"] = {"type": "Relationship", "value": body.implement_id}

        try:
            await orion.create_entity(entity, tenant_id)
            operation_id = op_remote_id
            ts = TimescaleDBClient(dsn=settings.database_url)
            await ts.connect()
            try:
                await ts.materialize_operation(
                    remote_id=op_remote_id,
                    tenant_id=tenant_id,
                    parcel_id=body.parcel_id,
                    equipment_id=None,
                    tractor_id=body.tractor_id,
                    implement_id=body.implement_id,
                    operation_type=body.operation_type,
                    ab_line_geojson=json.dumps(geojson_result),
                    implement_width=body.width_m,
                    status="planned",
                    vra_enabled=False,
                    prescription_map=None,
                    base_rate=None,
                    rate_unit=None,
                    started_at=None,
                    completed_at=None,
                    updated_at=int(time.time() * 1000),
                )
            finally:
                await ts.close()
        except Exception as e:
            logger.error("Failed to persist operation: %s", e)
        finally:
            await orion.close()

    return {
        "success": True,
        "data": {
            "type": "Feature",
            "geometry": geojson_result,
            "properties": {
                "heading_deg": body.heading_deg,
                "width_m": body.width_m,
                "swath_count": swath_count,
                "operation_id": operation_id,
            },
        },
    }
