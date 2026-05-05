import logging
import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from app.services.timescale_client import TimescaleDBClient
from app.services.coverage_service import CoverageService
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/operations", tags=["operations"])

class SessionCloseRequest(BaseModel):
    operation_id: str = Field(..., description="URN of the AgriParcelOperation in Orion-LD")
    end_date: str = Field(..., description="ISO 8601 End DateTime of the operation")
    status: str = Field(default="ended", description="Status to patch. Must be 'ended', 'finished', etc.")

async def patch_orion_operation(operation_id: str, payload: dict, tenant_id: str):
    """
    Background task to async fetch/patch the Context Broker.
    """
    settings = get_settings()
    orion_url = f"{settings.context_broker_url}/ngsi-ld/v1/entities/{operation_id}/attrs"
    headers = {
        "Content-Type": "application/json",
        "Link": f'<{settings.ngsi_ld_context}>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"',
        "NGSILD-Tenant": tenant_id,
        "FIWARE-Service": tenant_id,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.patch(orion_url, json=payload, headers=headers, timeout=10.0)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error("Failed to patch Orion %s: %s", operation_id, e.response.text)
        except Exception as e:
            logger.error("Error contacting Context Broker: %s", e)

@router.post("/session/close")
async def close_operation_session(request: Request, session_req: SessionCloseRequest, background_tasks: BackgroundTasks):
    """
    Closes an AgriParcelOperation session.
    Updates metadata in Orion-LD (status = ended, endDate).
    Does NOT write geometric tracks to Orion-LD to avoid Context Broker overload.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id or tenant_id == "default":
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "TENANT_NOT_FOUND",
                              "message": "Tenant not found or token missing tenant_id claim"}})

    # Create strict NGSI-LD Property patching payload for standard entity
    orion_payload = {
        "status": {
            "type": "Property",
            "value": session_req.status
        },
        "endDate": {
            "type": "Property",
            "value": {"@type": "DateTime", "@value": session_req.end_date}
        }
    }
    
    # We offload the actual HTTP request to a background task so the device 
    # receives an immediate '200 OK' response acknowledging the session end.
    background_tasks.add_task(patch_orion_operation, session_req.operation_id, orion_payload, tenant_id)
    
    return {
        "success": True, 
        "message": f"Operation {session_req.operation_id} marked for closure."
    }

@router.get("/coverage/{operation_id}")
async def get_operation_coverage(request: Request, operation_id: str) -> Dict[str, Any]:
    """
    Retrieves the actual executed track (MultiLineString) for a given operation.
    Queries telemetry_events via CoverageService/PostGIS.
    Returns a GeoJSON Feature that the MapLibre frontend can render immediately.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id or tenant_id == "default":
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "TENANT_NOT_FOUND",
                              "message": "Tenant not found or token missing tenant_id claim"}})
    settings = get_settings()
    ts = TimescaleDBClient(dsn=settings.database_url)
    svc = CoverageService(timescale=ts)
    geojson_multiline = await svc.get_operation_coverage(operation_id, tenant_id)

    if not geojson_multiline:
        raise HTTPException(
            status_code=404,
            detail="No telemetry coverage found for this operation.",
        )

    return {
        "success": True,
        "data": {
            "type": "Feature",
            "geometry": geojson_multiline,
            "properties": {
                "operation_id": operation_id,
                "layer_type": "actual_coverage",
            },
        },
    }
