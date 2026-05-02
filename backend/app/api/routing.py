"""
GIS Routing - Sync API with WatermelonDB protocol and route generation.

Provides WatermelonDB-compatible GET/POST /sync endpoints for delta-based
offline sync, plus the existing POST /routing/generate endpoint with
Orion-LD persistence.
"""

import hashlib
import json
import logging
import time
import uuid
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import JSONResponse
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel, Field
from typing import Optional

import httpx
from app.services.sync_service import SyncService, SyncConflictError
from app.services.geometry import generate_swaths
from app.services.orion_client import OrionLDClient
from app.services.timescale_client import TimescaleDBClient
from app.services.export_service import RouteExporter
from app.services.pmtiles_generator import PMTileGenerator
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
    dem_correction: bool = Field(False, description="Enable DEM slope correction via eu-elevation")
    persist: bool = True


@router.post("/generate")
async def generate_routing_plan(request: Request, body: GenerateRequest):
    if body.parcel_geometry.get("type") != "Polygon":
        raise HTTPException(status_code=400,
                            detail="parcel_geometry must be a GeoJSON Polygon")
    try:
        from shapely.geometry import mapping

        if body.dem_correction:
            from app.config import get_settings
            from app.services.geometry import generate_swaths_with_dem

            dem_url = get_settings().eu_elevation_url
            multi_line_string = await generate_swaths_with_dem(
                geojson_polygon=body.parcel_geometry,
                start_point=body.start_point,
                heading_deg=body.heading_deg,
                width_m=body.width_m,
                dem_url=dem_url,
            )
        else:
            multi_line_string = generate_swaths(
                geojson_polygon=body.parcel_geometry,
                start_point=body.start_point,
                heading_deg=body.heading_deg,
                width_m=body.width_m,
            )

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


class GenerateVRARequest(BaseModel):
    parcel_geometry: dict
    start_point: list[float]
    heading_deg: float = Field(..., ge=0, lt=360)
    width_m: float = Field(..., gt=0)
    parcel_id: Optional[str] = None
    tractor_id: Optional[str] = None
    implement_id: Optional[str] = None
    operation_type: Optional[str] = "spraying"
    dem_correction: bool = Field(False, description="Enable DEM slope correction via eu-elevation")
    base_rate: float = Field(
        ..., gt=0, description="Base application rate l/ha or kg/ha"
    )
    rate_unit: Optional[str] = "l_ha"
    zone_ids: Optional[list[str]] = None
    persist: bool = True


@router.post("/generate/with-vra")
async def generate_routing_with_vra(request: Request, body: GenerateVRARequest):
    from shapely.geometry import mapping
    from app.services.vra_intersector import intersect_swaths_with_zones

    if body.parcel_geometry.get("type") != "Polygon":
        raise HTTPException(
            status_code=400, detail="parcel_geometry must be a GeoJSON Polygon"
        )
    tenant_id = _get_tenant_id(request)
    settings = get_settings()

    # Generate swaths
    try:
        if body.dem_correction:
            from app.services.geometry import generate_swaths_with_dem

            dem_url = settings.eu_elevation_url
            multi_line_string = await generate_swaths_with_dem(
                geojson_polygon=body.parcel_geometry,
                start_point=body.start_point,
                heading_deg=body.heading_deg,
                width_m=body.width_m,
                dem_url=dem_url,
            )
        else:
            multi_line_string = generate_swaths(
                geojson_polygon=body.parcel_geometry,
                start_point=body.start_point,
                heading_deg=body.heading_deg,
                width_m=body.width_m,
            )
        swath_geojson = mapping(multi_line_string)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Fetch VRA zones from Orion-LD
    orion = OrionLDClient(
        base_url=settings.context_broker_url, context_url=settings.ngsi_ld_context
    )
    zones = await orion.query_entities("AgriManagementZone", tenant_id)
    await orion.close()

    # Filter zones linked to parcel
    if body.parcel_id:
        zones = [
            z
            for z in zones
            if body.parcel_id
            in str(z.get("refAgriParcel", {}).get("value", ""))
        ]
    if body.zone_ids:
        zones = [z for z in zones if z["id"] in body.zone_ids]

    # Intersect with VRA zones
    prescription_map = None
    if zones:
        zone_features = []
        for z in zones:
            loc = z.get("location", {}).get("value", {})
            if loc:
                zone_features.append(
                    {
                        "type": "Feature",
                        "geometry": loc,
                        "properties": {
                            "zone_id": z.get("zoneId", {}).get("value", z["id"]),
                            "zone_class": z.get("zoneClass", {}).get("value", ""),
                            "prescription_rate": float(
                                z.get("prescriptionRate", {}).get("value", 1.0)
                            ),
                        },
                    }
                )
        if zone_features:
            prescription_map = intersect_swaths_with_zones(
                multi_line_string, zone_features, body.base_rate, body.width_m
            )

    # Persist
    operation_id = None
    if body.persist and body.parcel_id:
        op_remote_id = (
            f"urn:ngsi-ld:AgriParcelOperation:{tenant_id}:"
            f"{uuid.uuid4().hex[:8]}"
        )
        now_ms = int(time.time() * 1000)
        orion = OrionLDClient(
            base_url=settings.context_broker_url,
            context_url=settings.ngsi_ld_context,
        )
        entity = {
            "id": op_remote_id,
            "type": "AgriParcelOperation",
            "name": {
                "type": "Property",
                "value": f"VRA {body.operation_type} - {body.parcel_id[:8]}",
            },
            "operationType": {"type": "Property", "value": body.operation_type},
            "status": {"type": "Property", "value": "planned"},
            "location": {"type": "GeoProperty", "value": swath_geojson},
            "implementWidth": {"type": "Property", "value": body.width_m},
            "vraEnabled": {"type": "Property", "value": bool(zones)},
            "baseRate": {"type": "Property", "value": body.base_rate},
            "rateUnit": {"type": "Property", "value": body.rate_unit},
        }
        if prescription_map:
            entity["prescriptionMap"] = {
                "type": "Property",
                "value": prescription_map,
            }
        try:
            await orion.create_entity(entity, tenant_id)
            operation_id = op_remote_id
        except Exception as e:
            logger.error("Failed to persist VRA operation: %s", e)
        finally:
            await orion.close()

    return {
        "success": True,
        "data": {
            "type": "Feature",
            "geometry": swath_geojson,
            "properties": {
                "heading_deg": body.heading_deg,
                "width_m": body.width_m,
                "swath_count": len(swath_geojson.get("coordinates", [])),
                "vra_enabled": bool(zones),
                "zone_count": len(zones),
                "base_rate": body.base_rate,
                "rate_unit": body.rate_unit,
                "operation_id": operation_id,
            },
        },
        "prescription_map": prescription_map,
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


# ── Zoning (AgriManagementZone via Orion-LD, generation via vegetation-health proxy) ──


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
        ref = str(z.get("refAgriParcel", {}).get("value", ""))
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
    """Trigger VRA zone generation via vegetation-health backend (server-to-server proxy)."""
    tenant_id = _get_tenant_id(request)
    body = await request.json()
    n_zones = body.get("n_zones", 3)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                f"http://vegetation-health-api-service:8000/api/vegetation/jobs/zoning/{parcel_id}",
                json={"n_zones": n_zones, "tenant_id": tenant_id},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            logger.error("Vegetation-health proxy failed: %s", e)
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
    Extracts the changed entities and materializes them into TimescaleDB.
    No JWT required — Orion-LD sends service-to-service notifications.
    """
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

            elif etype in ("AgriculturalTractor", "AgriculturalImplement"):
                name = str(entity.get("name", {}).get("value", eid))
                eq_type = "tractor" if etype == "AgriculturalTractor" else "implement"
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
                    parcel_id=str(entity.get("refAgriParcel", {}).get("value", "")),
                    equipment_id=None,
                    tractor_id=str(entity.get("refTractor", {}).get("value", "")),
                    implement_id=str(entity.get("refImplement", {}).get("value", "")),
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
