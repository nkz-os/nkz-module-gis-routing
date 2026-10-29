"""A-B pathfinding with DEM-based least-cost routing."""
import asyncio
import logging
import math
from nkz_platform_sdk.auth import require_auth, AuthContext
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.pathfinding.least_cost_path import compute_ab_routes, blocked_terminus
from app.services.pathfinding.dem_provider import DemRegistry, EuElevationProvider
from app.services.parcel_constraints import (
    fetch_parcel_constraints as _fetch_parcel_constraints,
    fetch_tenant_parcels_in_bbox,
)
from app.services.pathfinding.barriers import parcel_barrier_map
from app.services.machines import fetch_machine_kinematics
from app.services.coverage.errors import PlanError
from app.services.pathfinding.job_store import JobStore, JobLimitError
from app.services.exclusion import buffered_zones, rasterize_blocked_cells
from app.services.routing.base import project_polygon_to_utm

from shapely.geometry import Polygon

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/path", tags=["pathfinding"])

JOBS = JobStore()

# Search area around the A-B box; one wider retry when nothing is found.
SEARCH_MARGINS_M = (500, 2000)
DEM_RESOLUTION_M = 10
# Cap on planned DEM cells. Measured: an exhaustive no-path A* over 1M cells takes
# ~14 s and ~200 MB; the pod limit is 512 MiB, so 1M is the ceiling. The two
# objectives run one after the other (compute_ab_routes) and each search's
# structures are freed when it returns.
MAX_SEARCH_CELLS = 1_000_000
_M_PER_DEG_LAT = 111320.0
# One DEM fetch + search at a time across all jobs: each search can use ~200 MB
# and the pod limit is 512 MiB. Waiting jobs stay "queued".
_SEARCH_LOCK = asyncio.Semaphore(1)


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


def _rasterize_constraints(zones, parcels, raster, cols, rows, machine_width_m):
    """CPU part of an attempt (zone growing + rasterization, fences): runs in a worker thread."""
    block_wgs84 = _grow_zones(zones, machine_width_m / 2.0)
    zone_cells = rasterize_blocked_cells(
        block_wgs84, raster["origin_lon"], raster["origin_lat"],
        raster["pixel_size_deg"], cols, rows)
    fences = parcel_barrier_map(parcels, raster, machine_width_m, cols=cols, rows=rows)
    return zone_cells, fences


async def _resolve_path_constraints(parcel_id, tenant_id, raster, cols, rows, machine_width_m, bbox,
                                    report: dict | None = None):
    """Return (default_origin_or_None, zone_cells, fences).

    One read of the tenant's parcels in bbox gives both parts. The zones of every
    parcel are always blocked (an A-B route can leave the parcel); with parcel_id,
    that parcel's own zones are added and its access point is the default origin.
    fences maps each gated parcel id to its fence cells (crossable only at the gate);
    ungated parcels are open ground. The Orion reads are async; all geometry and
    raster work runs in a thread so the event loop keeps serving other requests.
    When report is given, parcels whose location is unreadable are counted in
    report["unreadable_parcels"] (their zones still count; they get no fence).
    """
    parcels = await fetch_tenant_parcels_in_bbox(tenant_id, bbox)
    zones = [z for p in parcels for z in p["zones"]]
    default_origin = None
    if parcel_id:
        c = await _fetch_parcel_constraints(parcel_id, tenant_id)
        zones += list(c["zones"])
        default_origin = c["access_point"]
    if report is not None:
        report["unreadable_parcels"] = sum(1 for p in parcels if p.get("polygon") is None and p.get("geometry") is None)
    zone_cells, fences = await asyncio.to_thread(
        _rasterize_constraints, zones, parcels, raster, cols, rows, machine_width_m)
    if report is not None:
        report["constraints_used"] = {"parcels": len(parcels), "gated": len(fences), "zones": len(zones)}
    return default_origin, zone_cells, fences


@router.post("/calculate")
async def start_path_calculation(request: Request, body: PathRequest, auth: AuthContext = require_auth()):
    tenant_id = auth.tenant_id
    if body.min_turn_radius_m is not None:
        logger.warning("path/calculate: min_turn_radius_m is deprecated and ignored")
    try:
        job_id = JOBS.create(tenant_id)
    except JobLimitError:
        raise PlanError("JOBS_LIMIT", "too many pathfinding jobs running for this tenant",
                        {"max_jobs": JOBS.max_per_tenant})
    asyncio.create_task(_run_pathfinding(job_id, body, tenant_id))
    return {"job_id": job_id, "status": "queued"}


@router.get("/{job_id}")
async def get_path_result(job_id: str, auth: AuthContext = require_auth()):
    job = JOBS.get(job_id, auth.tenant_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _fail(job_id: str, code: str, text: str, params: dict | None = None) -> None:
    JOBS.set(job_id, {"status": "failed", "error": text,
                      "error_code": code, "error_params": params or {}})


def _search_bbox(a: list[float], b: list[float], margin_m: float) -> tuple[float, float, float, float]:
    """A-B bounding box grown by margin_m on every side (WGS84 degrees)."""
    mid_lat = (a[1] + b[1]) / 2.0
    dlat = margin_m / _M_PER_DEG_LAT
    dlon = margin_m / (_M_PER_DEG_LAT * max(math.cos(math.radians(mid_lat)), 0.01))
    return (min(a[0], b[0]) - dlon, min(a[1], b[1]) - dlat,
            max(a[0], b[0]) + dlon, max(a[1], b[1]) + dlat)


def _planned_cells(bbox: tuple[float, float, float, float]) -> int:
    """Cells of the DEM grid for bbox. The grid has square degrees (pixel = 10 m / 111320 on both
    axes), so longitude cells are narrower than 10 m away from the equator and there are more."""
    cols = math.ceil((bbox[2] - bbox[0]) * _M_PER_DEG_LAT / DEM_RESOLUTION_M)
    rows = math.ceil((bbox[3] - bbox[1]) * _M_PER_DEG_LAT / DEM_RESOLUTION_M)
    return cols * rows


async def _run_pathfinding(job_id: str, body: PathRequest, tenant_id: str):
    try:
        lon_a, lat_a = body.point_a
        lon_b, lat_b = body.point_b

        machine_width_m = body.machine_width_m
        if body.machine_id:
            kin = await fetch_machine_kinematics(body.machine_id, tenant_id)
            width = kin.get("implementWidth")
            if not isinstance(width, (int, float)) or width <= 0:
                logger.error("path/calculate: machine not found or has no implementWidth: machine_id=%s job=%s",
                             body.machine_id, job_id)
                _fail(job_id, "MACHINE_WIDTH_MISSING", "machine not found or has no implementWidth",
                      {"machine_id": body.machine_id})
                return
            machine_width_m = float(width)

        async with _SEARCH_LOCK:
            JOBS.set(job_id, {"status": "running"})
            await _search(job_id, body, tenant_id, machine_width_m)
    except Exception:
        logger.exception("Pathfinding job %s failed", job_id)
        _fail(job_id, "ENGINE_FAILURE", "Route calculation failed")


def _too_large(job_id: str, margin_m: int, first: bool, cells: int) -> None:
    logger.warning("path job %s: search area too large margin_m=%d cells=%d cap=%d",
                   job_id, margin_m, cells, MAX_SEARCH_CELLS)
    if first:
        _fail(job_id, "AREA_TOO_LARGE", "The search area is too large",
              {"margin_m": margin_m, "max_cells": MAX_SEARCH_CELLS})
    else:  # the first attempt found no route and the wider retry does not fit
        _fail(job_id, "NO_PATH", "No route avoids the no-go zones",
              {"search_margin_m": SEARCH_MARGINS_M[0], "retry": "skipped_area_cap"})


async def _search(job_id: str, body: PathRequest, tenant_id: str, machine_width_m: float):
    lon_a, lat_a = body.point_a
    lon_b, lat_b = body.point_b
    # An explicit elevation grid (tests/legacy) is fixed: widening the area cannot help.
    margins = SEARCH_MARGINS_M[:1] if body.elevation_grid else SEARCH_MARGINS_M
    for attempt, margin_m in enumerate(margins):
        bbox = _search_bbox(body.point_a, body.point_b, margin_m)
        cells = _planned_cells(bbox)
        if cells > MAX_SEARCH_CELLS:
            _too_large(job_id, margin_m, attempt == 0, cells)
            return

        if body.elevation_grid:
            raster = body.elevation_grid
        else:
            raster = await build_dem_registry().fetch_best(bbox, resolution_m=DEM_RESOLUTION_M)
            if not raster:
                _fail(job_id, "DEM_UNAVAILABLE", "No elevation data available for this area")
                return

        elevations = raster["elevations"]
        origin_lon = raster["origin_lon"]
        origin_lat = raster["origin_lat"]
        pixel_size = raster["pixel_size_deg"]
        rows = len(elevations)
        cols = len(elevations[0]) if rows > 0 else 0
        if rows * cols > MAX_SEARCH_CELLS:
            _too_large(job_id, margin_m, attempt == 0, rows * cols)
            return

        start_col = max(0, min(int((lon_a - origin_lon) / pixel_size), cols - 1))
        start_row = max(0, min(int((lat_a - origin_lat) / pixel_size), rows - 1))
        end_col = max(0, min(int((lon_b - origin_lon) / pixel_size), cols - 1))
        end_row = max(0, min(int((lat_b - origin_lat) / pixel_size), rows - 1))

        prep: dict = {}
        _default_origin, zone_cells, fences = await _resolve_path_constraints(
            parcel_id=body.parcel_id, tenant_id=tenant_id, raster=raster,
            cols=cols, rows=rows, machine_width_m=machine_width_m, bbox=bbox, report=prep)
        fence_cells: set = set().union(*fences.values()) if fences else set()
        blocked = zone_cells | fence_cells

        start, end = (start_col, start_row), (end_col, end_row)
        point = blocked_terminus(start, end, zone_cells)
        if point:
            coords = [lon_a, lat_a] if point == "A" else [lon_b, lat_b]
            _fail(job_id, "POINT_IN_ZONE", "Start or end point is inside a no-go zone",
                  {"point": point, "geometry": {"type": "Point", "coordinates": coords}})
            return
        point = blocked_terminus(start, end, fence_cells)
        if point:
            cell = start if point == "A" else end
            coords = [lon_a, lat_a] if point == "A" else [lon_b, lat_b]
            on_parcel = next((pid for pid, cs in fences.items() if cell in cs), None)
            _fail(job_id, "POINT_ON_BARRIER", "Start or end point is on a parcel fence",
                  {"point": point, "parcel_id": on_parcel,
                   "geometry": {"type": "Point", "coordinates": coords}})
            return

        alternatives = await asyncio.to_thread(
            compute_ab_routes,
            elevations, origin_lon, origin_lat, pixel_size,
            start_col, start_row, end_col, end_row,
            max_slope_deg=body.max_slope_deg,
            blocked=blocked,
        )
        if alternatives:
            JOBS.set(job_id, {
                "status": "completed",
                "alternatives": alternatives,
                "report": {
                    "max_slope_deg": body.max_slope_deg,
                    "max_slope_deg_found": max(a["max_slope_deg_found"] for a in alternatives),
                    "blocked_cells_hit": sum(a["blocked_cells_hit"] for a in alternatives),
                    "search_margin_m": margin_m,
                    "warnings": ([{"code": "PARCELS_UNREADABLE", "params": {"count": prep["unreadable_parcels"]}}]
                                 if prep.get("unreadable_parcels") else []),
                    "constraints_used": prep.get("constraints_used",
                                                 {"parcels": 0, "gated": 0, "zones": 0}),
                },
            })
            return
        logger.info("path job %s: no route with margin_m=%d cells=%d", job_id, margin_m, rows * cols)

    _fail(job_id, "NO_PATH", "No route avoids the no-go zones")
