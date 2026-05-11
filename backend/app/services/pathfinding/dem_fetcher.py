"""Fetch DEM raster data from eu-elevation service."""
import httpx
import logging

logger = logging.getLogger(__name__)


async def fetch_dem_raster(dem_url: str, bbox: tuple) -> dict | None:
    """Fetch a DEM raster for a bounding box from eu-elevation.
    Returns dict with 'elevations' (2D list), 'origin_lon', 'origin_lat',
    'pixel_size_deg', 'cols', 'rows', or None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{dem_url}/raster",
                params={
                    "min_lon": bbox[0], "min_lat": bbox[1],
                    "max_lon": bbox[2], "max_lat": bbox[3],
                    "resolution_m": 10,
                },
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning("DEM raster fetch returned %s", resp.status_code)
            return None
    except Exception as e:
        logger.error("DEM raster fetch failed: %s", e)
        return None
