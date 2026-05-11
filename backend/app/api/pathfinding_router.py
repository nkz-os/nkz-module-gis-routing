"""A-B pathfinding with DEM-based least-cost routing."""
import asyncio
import logging
import uuid
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from app.config import get_settings
from app.services.pathfinding.least_cost_path import compute_least_cost_paths
from app.services.pathfinding.dem_fetcher import fetch_dem_raster

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/path", tags=["pathfinding"])

_JOBS: dict[str, dict] = {}


class PathRequest(BaseModel):
    point_a: list[float]
    point_b: list[float]
    machine_width_m: float = Field(default=3.0, gt=0)
    max_slope_deg: float = Field(default=15.0, gt=0, le=45)
    min_turn_radius_m: float = Field(default=8.0, gt=0)
    elevation_source: Literal["eu-dem", "external"] = "eu-dem"
    num_alternatives: int = Field(default=3, ge=1, le=5)


@router.post("/calculate")
async def start_path_calculation(request: Request, body: PathRequest):
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {"status": "queued", "result": None}
    asyncio.create_task(_run_pathfinding(job_id, body))
    return {"job_id": job_id, "status": "queued"}


@router.get("/{job_id}")
async def get_path_result(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _run_pathfinding(job_id: str, body: PathRequest):
    try:
        settings = get_settings()
        dem_url = settings.eu_elevation_url if body.elevation_source == "eu-dem" else None
        if not dem_url:
            _JOBS[job_id] = {"status": "failed", "error": "No DEM source configured"}
            return

        lon_a, lat_a = body.point_a
        lon_b, lat_b = body.point_b
        margin = 0.005
        bbox = (
            min(lon_a, lon_b) - margin, min(lat_a, lat_b) - margin,
            max(lon_a, lon_b) + margin, max(lat_a, lat_b) + margin,
        )

        raster = await fetch_dem_raster(dem_url, bbox)
        if not raster:
            _JOBS[job_id] = {"status": "failed", "error": "DEM raster fetch failed"}
            return

        elevations = raster["elevations"]
        origin_lon = raster["origin_lon"]
        origin_lat = raster["origin_lat"]
        pixel_size = raster["pixel_size_deg"]
        rows = len(elevations)
        cols = len(elevations[0]) if rows > 0 else 0

        start_col = max(0, min(int((lon_a - origin_lon) / pixel_size), cols - 1))
        start_row = max(0, min(int((lat_a - origin_lat) / pixel_size), rows - 1))
        end_col = max(0, min(int((lon_b - origin_lon) / pixel_size), cols - 1))
        end_row = max(0, min(int((lat_b - origin_lat) / pixel_size), rows - 1))

        alternatives = compute_least_cost_paths(
            elevations, origin_lon, origin_lat, pixel_size,
            start_col, start_row, end_col, end_row,
            max_slope_deg=body.max_slope_deg,
            num_alternatives=body.num_alternatives,
        )

        _JOBS[job_id] = {"status": "completed", "alternatives": alternatives}
    except Exception as e:
        logger.exception("Pathfinding job %s failed", job_id)
        _JOBS[job_id] = {"status": "failed", "error": str(e)}
