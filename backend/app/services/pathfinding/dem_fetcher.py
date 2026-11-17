"""Fetch DEM raster data from eu-elevation and normalise it to the internal grid.

eu-elevation /raster serves rows north first (``row_order: "north_first"``,
``north_lat``; ``origin_lat`` is the SOUTH edge) and columns west first.
``pixel_size_deg`` is the column width; the row height is
``(north_lat - origin_lat) / rows`` and differs from it by rounding. The
internal grid (``DemGrid``) has row 0 = south, so rows are reordered here, once,
and the row height travels as ``pixel_height_deg``. No-data cells stay ``None``.

A response whose layout is not the declared one is rejected (None), never guessed.
"""
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_SECRET_ENV = "INTERNAL_SERVICE_SECRET"


def dem_secret_configured() -> bool:
    """eu-elevation only serves readers that present the internal service secret."""
    return bool(os.getenv(_SECRET_ENV, ""))


def _reject(bbox: tuple, reason: str) -> None:
    logger.error("DEM raster rejected: reason=%s bbox=%s", reason, bbox)


def _normalise(payload: dict, bbox: tuple) -> dict | None:
    if payload.get("row_order") != "north_first":
        _reject(bbox, f"row_order={payload.get('row_order')!r}")
        return None
    north_lat = payload.get("north_lat")
    if not isinstance(north_lat, (int, float)):
        _reject(bbox, "north_lat missing")
        return None
    rows, cols = payload.get("rows"), payload.get("cols")
    elevations = payload.get("elevations")
    if (not isinstance(elevations, list) or not isinstance(rows, int) or not isinstance(cols, int)
            or rows < 1 or cols < 1 or len(elevations) != rows
            or any(not isinstance(r, list) or len(r) != cols for r in elevations)):
        _reject(bbox, "shape does not match rows x cols")
        return None
    if all(v is None for r in elevations for v in r):
        logger.warning("DEM raster has no data: bbox=%s", bbox)
        return None
    origin_lat = payload["origin_lat"]
    return {
        "elevations": list(reversed(elevations)),
        "origin_lon": payload["origin_lon"],
        "origin_lat": origin_lat,
        "pixel_size_deg": payload["pixel_size_deg"],
        "pixel_height_deg": (north_lat - origin_lat) / rows,
        "cols": cols,
        "rows": rows,
        "source": payload.get("source") or {},
    }


async def fetch_dem_raster(dem_url: str, bbox: tuple, resolution_m: float = 10) -> dict | None:
    """Fetch a DEM grid for bbox (min_lon, min_lat, max_lon, max_lat) as a DemGrid
    (see dem_provider.DemGrid), or None when unavailable."""
    secret = os.getenv(_SECRET_ENV, "")
    if not secret:
        logger.error("DEM raster not requested: %s not set", _SECRET_ENV)
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{dem_url}/raster",
                headers={"X-Internal-Service-Secret": secret},
                params={
                    "min_lon": bbox[0], "min_lat": bbox[1],
                    "max_lon": bbox[2], "max_lat": bbox[3],
                    "resolution_m": resolution_m,
                    "nodata": "null",
                },
            )
            if resp.status_code != 200:
                logger.warning("DEM raster fetch returned %s: bbox=%s resolution_m=%s",
                               resp.status_code, bbox, resolution_m)
                return None
            return _normalise(resp.json(), bbox)
    except Exception as e:
        logger.error("DEM raster fetch failed: %s bbox=%s", type(e).__name__, bbox)
        return None
