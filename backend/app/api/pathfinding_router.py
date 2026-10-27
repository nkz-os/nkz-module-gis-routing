"""A-B pathfinding with DEM-based least-cost routing."""
import asyncio
import logging
from nkz_platform_sdk.auth import require_auth, AuthContext
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.pathfinding.least_cost_path import compute_ab_routes, terminus_blocked
from app.services.pathfinding.dem_provider import DemRegistry, EuElevationProvider
from app.services.parcel_constraints import (
    fetch_parcel_constraints as _fetch_parcel_constraints,
    fetch_tenant_zones_in_bbox,
)
from app.services.machines import fetch_machine_kinematics
from app.services.pathfinding.job_store import JobStore, JobLimitError
from app.services.exclusion import buffered_zones, rasterize_blocked_cells
from app.services.routing.base import project_polygon_to_utm

from shapely.geometry import Polygon

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/path", tags=["pathfinding"])

JOBS = JobStore()


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
    machine_id: str | None = None
    min_turn_radius_m: float | None = None  # deprecated: accepted and ignored
    elevation_grid: dict | None = None
    parcel_id: str | None = None


def _grow_zones(zones, buffer_m):
    """Buffer WGS84 zones by buffer_m (in UTM) and return their union in WGS84."""
    if not zones:
        return None
    grown = []
    for z in zones:
        _p, _crs, to_utm, to_wgs84 = project_polygon_to_utm(z)
        ux, uy = to_utm(*z.exterior.coords.xy)
        gu = Polygon(zip(ux, uy)).buffer(buffer_m)
        gx, gy = to_wgs84(*gu.exterior.coords.xy)
        grown.append(Polygon(zip(gx, gy)))
    return buffered_zones(grown, 0.0)  # union (already buffered)


async def _resolve_path_constraints(parcel_id, tenant_id, raster, cols, rows, machine_width_m, bbox):
    """Return (default_origin_or_None, blocked_cells_set).

    With parcel_id: that parcel's zones and access point. Without: the zones of
    the tenant's parcels intersecting bbox.
    """
    if parcel_id:
        c = await _fetch_parcel_constraints(parcel_id, tenant_id)
        zones, default_origin = c["zones"], c["access_point"]
    else:
        zones, default_origin = await fetch_tenant_zones_in_bbox(tenant_id, bbox), None
    block_wgs84 = _grow_zones(zones, machine_width_m / 2.0)
    blocked = rasterize_blocked_cells(
        block_wgs84, raster["origin_lon"], raster["origin_lat"],
        raster["pixel_size_deg"], cols, rows)
    return default_origin, blocked


@router.post("/calculate")
async def start_path_calculation(request: Request, body: PathRequest, auth: AuthContext = require_auth()):
    tenant_id = auth.tenant_id
    if body.min_turn_radius_m is not None:
        logger.warning("path/calculate: min_turn_radius_m is deprecated and ignored")
    try:
        job_id = JOBS.create(tenant_id)
    except JobLimitError:
        raise HTTPException(status_code=429, detail={
            "code": "JOB_LIMIT", "message": "too many pathfinding jobs for this tenant"})
    asyncio.create_task(_run_pathfinding(job_id, body, tenant_id))
    return {"job_id": job_id, "status": "queued"}


@router.get("/{job_id}")
async def get_path_result(job_id: str, auth: AuthContext = require_auth()):
    job = JOBS.get(job_id, auth.tenant_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _run_pathfinding(job_id: str, body: PathRequest, tenant_id: str):
    try:
        lon_a, lat_a = body.point_a
        lon_b, lat_b = body.point_b

        margin = 0.005
        bbox = (
            min(lon_a, lon_b) - margin, min(lat_a, lat_b) - margin,
            max(lon_a, lon_b) + margin, max(lat_a, lat_b) + margin,
        )
        machine_width_m = body.machine_width_m
        if body.machine_id:
            kin = await fetch_machine_kinematics(body.machine_id, tenant_id)
            width = kin.get("implementWidth")
            if isinstance(width, (int, float)) and width > 0:
                machine_width_m = float(width)

        if body.elevation_grid:
            raster = body.elevation_grid  # legacy/explicit override (tests)
        else:
            raster = await build_dem_registry().fetch_best(bbox, resolution_m=10)
            if not raster:
                JOBS.set(job_id, {"status": "failed",
                                 "error": "No elevation data available for this area"})
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
            parcel_id=body.parcel_id, tenant_id=tenant_id, raster=raster,
            cols=cols, rows=rows, machine_width_m=machine_width_m, bbox=bbox)

        if terminus_blocked((start_col, start_row), (end_col, end_row), blocked):
            JOBS.set(job_id, {"status": "failed",
                             "error": "Start or end point is inside a no-go zone"})
            return

        alternatives = compute_ab_routes(
            elevations, origin_lon, origin_lat, pixel_size,
            start_col, start_row, end_col, end_row,
            max_slope_deg=body.max_slope_deg,
            blocked=blocked,
        )

        if not alternatives:
            JOBS.set(job_id, {"status": "failed",
                             "error": "No route avoids the no-go zones"})
            return

        JOBS.set(job_id, {
            "status": "completed",
            "alternatives": alternatives,
            "report": {
                "max_slope_deg": body.max_slope_deg,
                "blocked_cells_hit": sum(a["blocked_cells_hit"] for a in alternatives),
            },
        })
    except Exception as e:
        logger.exception("Pathfinding job %s failed", job_id)
        JOBS.set(job_id, {"status": "failed", "error": str(e)})
