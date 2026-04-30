import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from app.services.timescale_client import timescale_client
from app.config import get_settings

router = APIRouter(prefix="/operations", tags=["operations"])

class SessionCloseRequest(BaseModel):
    operation_id: str = Field(..., description="URN of the AgriParcelOperation in Orion-LD")
    end_date: str = Field(..., description="ISO 8601 End DateTime of the operation")
    status: str = Field(default="ended", description="Status to patch. Must be 'ended', 'finished', etc.")

async def patch_orion_operation(operation_id: str, payload: dict):
    """
    Background task to async fetch/patch the Context Broker.
    """
    settings = get_settings()
    orion_url = f"{settings.context_broker_url}/ngsi-ld/v1/entities/{operation_id}/attrs"
    # Adhering strictly to FIWARE NGSI-LD headers and no invented attributes
    headers = {
        "Content-Type": "application/json",
        "Link": f'<{settings.ngsi_ld_context}>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"'
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.patch(orion_url, json=payload, headers=headers, timeout=10.0)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # In production, we log this carefully. 404 means entity doesn't exist
            print(f"Failed to patch Orion {operation_id}: {e.response.text}")
        except Exception as e:
            print(f"Error contacting Context Broker: {e}")

@router.post("/session/close")
async def close_operation_session(request: SessionCloseRequest, background_tasks: BackgroundTasks):
    """
    Closes an AgriParcelOperation session.
    Updates metadata in Orion-LD (status = ended, endDate).
    Does NOT write geometric tracks to Orion-LD to avoid Context Broker overload.
    """
    # Create strict NGSI-LD Property patching payload for standard entity
    orion_payload = {
        "status": {
            "type": "Property",
            "value": request.status
        },
        "endDate": {
            "type": "Property",
            "value": {"@type": "DateTime", "@value": request.end_date}
        }
    }
    
    # We offload the actual HTTP request to a background task so the device 
    # receives an immediate '200 OK' response acknowledging the session end.
    background_tasks.add_task(patch_orion_operation, request.operation_id, orion_payload)
    
    return {
        "success": True, 
        "message": f"Operation {request.operation_id} marked for closure."
    }

@router.get("/coverage/{operation_id}")
async def get_operation_coverage(operation_id: str) -> Dict[str, Any]:
    """
    Retrieves the actual executed track (MultiLineString) for a given operation.
    Queries the TimescaleDB / PostGIS historics (where the IoT Agent dumped the data).
    Returns a GeoJSON Feature that the MapLibre frontend can render immediately.
    """
    # Delegate complex PostGIS aggregation to the timescale client
    geojson_multiline = await timescale_client.get_operation_coverage_map(operation_id)
    
    if not geojson_multiline:
        raise HTTPException(status_code=404, detail="No telemetry coverage found for this operation.")
        
    return {
        "success": True,
        "data": {
            "type": "Feature",
            "geometry": geojson_multiline,
            "properties": {
                "operation_id": operation_id,
                "layer_type": "actual_coverage"
            }
        }
    }
