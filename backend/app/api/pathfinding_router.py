"""A-B pathfinding with DEM-based least-cost routing."""
import asyncio
import logging
import uuid
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.pathfinding.least_cost_path import compute_ab_routes, terminus_blocked
from app.services.pathfinding.dem_provider import DemRegistry, EuElevationProvider
from app.services.parcel_constraints import fetch_parcel_constraints as _fetch_parcel_constraints
from app.services.exclusion import buffered_zones, rasterize_blocked_cells
from app.services.routing.base import project_polygon_to_utm
from app.api.deps import get_tenant_id
from shapely.geometry import Polygon

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/path", tags=["pathfinding"])

_JOBS: dict[str, dict] = {}


def build_dem_registry() -> DemRegistry:
    """Active providers, highest precision first. Today: eu-elevation only.
    Follow-up providers (LiDAR/IDENA/IGN) register here with higher priority."""
    settings = get_settings()
    return DemRegistry([EuElevationProvider(dem_url=settings.eu_elevation_url)])


class PathRequest(BaseModel):
    point_a: list[float]
    point_b: list[float]
    machine_width_m: float = Field(default=3.0, gt=0)
    max_slope_deg: float = Field(default=15.0, gt=0, le=45)
    min_turn_radius_m: float = Field(default=8.0, gt=0)
    elevation_grid: dict | None = None
    parcel_id: str | None = None


async def _resolve_path_constraints(parcel_id, tenant_id, raster, cols, rows,
                                    machine_width_m):
    """Return (default_origin_or_None, blocked_cells_set)."""
    if not parcel_id:
        return None, set()
    c = await _fetch_parcel_constraints(parcel_id, tenant_id)
    buffer_m = machine_width_m / 2.0
    block_wgs84 = None
    if c["zones"]:
        grown = []
        for z in c["zones"]:
            _p, _crs, to_utm, to_wgs84 = project_polygon_to_utm(z)
            ux, uy = to_utm(*z.exterior.coords.xy)
            gu = Polygon(zip(ux, uy)).buffer(buffer_m)
            gx, gy = to_wgs84(*gu.exterior.coords.xy)
            grown.append(Polygon(zip(gx, gy)))
        block_wgs84 = buffered_zones(grown, 0.0)  # union (already buffered)
    blocked = rasterize_blocked_cells(
        block_wgs84, raster["origin_lon"], raster["origin_lat"],
        raster["pixel_size_deg"], cols, rows)
    return c["access_point"], blocked


@router.post("/calculate")
async def start_path_calculation(request: Request, body: PathRequest):
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {"status": "queued", "result": None}
    # Tenant is only required when parcel_id is given (to fetch constraints).
    # Without parcel_id the endpoint works without auth headers (free routing).
    try:
        tenant_id = get_tenant_id(request)
    except HTTPException:
        if body.parcel_id:
            raise
        tenant_id = None
    asyncio.create_task(_run_pathfinding(job_id, body, tenant_id))
    return {"job_id": job_id, "status": "queued"}


@router.get("/{job_id}")
async def get_path_result(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _run_pathfinding(job_id: str, body: PathRequest, tenant_id: str | None):
    try:
        lon_a, lat_a = body.point_a
        lon_b, lat_b = body.point_b

        if body.elevation_grid:
            raster = body.elevation_grid  # legacy/explicit override (tests)
        else:
            margin = 0.005
            bbox = (
                min(lon_a, lon_b) - margin, min(lat_a, lat_b) - margin,
                max(lon_a, lon_b) + margin, max(lat_a, lat_b) + margin,
            )
            raster = await build_dem_registry().fetch_best(bbox, resolution_m=10)
            if not raster:
                _JOBS[job_id] = {"status": "failed",
                                 "error": "No elevation data available for this area"}
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

        default_origin, blocked = await _resolve_path_constraints(
            body.parcel_id, tenant_id, raster, cols, rows, body.machine_width_m)

        if terminus_blocked((start_col, start_row), (end_col, end_row), blocked):
            _JOBS[job_id] = {"status": "failed",
                             "error": "Start or end point is inside a no-go zone"}
            return

        alternatives = compute_ab_routes(
            elevations, origin_lon, origin_lat, pixel_size,
            start_col, start_row, end_col, end_row,
            max_slope_deg=body.max_slope_deg,
            blocked=blocked,
        )

        if not alternatives:
            _JOBS[job_id] = {"status": "failed",
                             "error": "No route avoids the no-go zones"}
            return

        _JOBS[job_id] = {"status": "completed", "alternatives": alternatives}
    except Exception as e:
        logger.exception("Pathfinding job %s failed", job_id)
        _JOBS[job_id] = {"status": "failed", "error": str(e)}
