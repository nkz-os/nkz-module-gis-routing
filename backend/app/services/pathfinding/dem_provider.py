"""Elevation provider abstraction.

A DemProvider knows whether it has data for a bbox (`covers`) and can fetch a
DEM grid for it (`fetch`). The registry tries providers by descending priority
(higher = more precise) and returns the first grid from a provider that covers
the bbox. Returns None when nothing covers — callers must fail safe.
"""
from __future__ import annotations

import logging
from typing import Protocol, TypedDict, runtime_checkable

from app.services.pathfinding.dem_fetcher import fetch_dem_raster
from app.services.pathfinding.dem_resample import resample_bilinear

logger = logging.getLogger(__name__)

Bbox = tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)


class DemGrid(TypedDict, total=False):
    # elevations[row][col]; row 0 = south, rows increase northward; None = no data
    elevations: list[list[float | None]]
    origin_lon: float   # west edge (min lon)
    origin_lat: float   # south edge (min lat)
    pixel_size_deg: float    # column width in degrees
    pixel_height_deg: float  # row height in degrees; absent = pixel_size_deg (client grids)
    cols: int
    rows: int
    source: dict  # eu-elevation source block (id, category, resolution_m, fallback_reason)


@runtime_checkable
class DemProvider(Protocol):
    name: str
    priority: int

    def covers(self, bbox: Bbox) -> bool: ...

    async def fetch(self, bbox: Bbox, resolution_m: float) -> DemGrid | None: ...


# EU-wide coverage bounds (lon/lat) — generous box covering the EU + nearby.
_EU_BOUNDS = (-31.5, 27.0, 45.0, 72.0)
# A source coarser than this factor times the requested resolution is re-read at its
# native resolution and interpolated (see dem_resample).
NATIVE_REFETCH_FACTOR = 1.5


class EuElevationProvider:
    """Default provider backed by nkz-module-eu-elevation (~10-30 m)."""

    name = "eu-elevation"
    priority = 10

    def __init__(self, dem_url: str):
        self._dem_url = dem_url

    def covers(self, bbox: Bbox) -> bool:
        min_lon, min_lat, max_lon, max_lat = bbox
        b = _EU_BOUNDS
        return (b[0] <= min_lon and b[1] <= min_lat
                and max_lon <= b[2] and max_lat <= b[3])

    async def fetch(self, bbox: Bbox, resolution_m: float) -> DemGrid | None:
        grid = await fetch_dem_raster(self._dem_url, bbox, resolution_m)
        if not grid:
            return None
        native_m = (grid.get("source") or {}).get("resolution_m")
        if not isinstance(native_m, (int, float)) or native_m <= NATIVE_REFETCH_FACTOR * resolution_m:
            return grid
        native = await fetch_dem_raster(self._dem_url, bbox, native_m)
        if not native:
            # The requested grid is block-resampled from the coarse source (false
            # slopes): never route on it.
            logger.warning("DEM native re-read failed: native_m=%s bbox=%s", native_m, bbox)
            return None
        logger.info("dem resampled native=%s target=%s bbox=%s", native_m, resolution_m, bbox)
        return resample_bilinear(native, grid)


class DemRegistry:
    def __init__(self, providers: list[DemProvider]):
        self._providers = sorted(providers, key=lambda p: p.priority, reverse=True)

    async def fetch_best(self, bbox: Bbox, resolution_m: float) -> DemGrid | None:
        for provider in self._providers:
            if provider.covers(bbox):
                grid = await provider.fetch(bbox, resolution_m)
                if grid:
                    return grid
                logger.warning(
                    "DEM provider %s covers bbox %s but returned no grid; "
                    "falling back to next provider", provider.name, bbox)
        return None
