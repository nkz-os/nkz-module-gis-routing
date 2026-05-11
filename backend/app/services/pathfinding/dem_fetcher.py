"""Fetch DEM raster data from eu-elevation or LiDAR module."""

import io
import logging
import tempfile
import os
import httpx

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


async def fetch_lidar_raster(lidar_api_url: str, parcel_id: str) -> dict | None:
    """Fetch a DTM raster from the LiDAR module for a given parcel.

    1. Lists available LiDAR layers for the parcel.
    2. Picks the first completed layer.
    3. Downloads the DTM GeoTIFF.
    4. Parses it into the standard raster dict format via GDAL.

    Returns dict with 'elevations', 'origin_lon', 'origin_lat',
    'pixel_size_deg', 'cols', 'rows', or None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # 1. Find available LiDAR layers for this parcel
            layers_resp = await client.get(
                f"{lidar_api_url}/layers",
                params={"parcel_id": parcel_id},
            )
            if layers_resp.status_code != 200:
                logger.warning("LiDAR layers query returned %s", layers_resp.status_code)
                return None

            layers = layers_resp.json()
            if not isinstance(layers, list) or not layers:
                logger.info("No LiDAR layers found for parcel %s", parcel_id)
                return None

            # Pick first completed layer
            layer_id = layers[0].get("id")
            if not layer_id:
                return None

            # 2. Download DTM GeoTIFF
            dtm_resp = await client.get(
                f"{lidar_api_url}/export/{layer_id}/dtm",
            )
            if dtm_resp.status_code != 200:
                logger.warning("LiDAR DTM fetch returned %s", dtm_resp.status_code)
                return None

            dtm_bytes = dtm_resp.read()

        # 3. Parse GeoTIFF via GDAL (if available) or rasterio
        return _parse_geotiff_with_gdal(dtm_bytes)

    except Exception as e:
        logger.error("LiDAR DTM fetch failed: %s", e)
        return None


def _parse_geotiff_with_gdal(data: bytes) -> dict | None:
    """Parse a GeoTIFF byte buffer using GDAL or rasterio.

    Returns {elevations, origin_lon, origin_lat, pixel_size_deg, cols, rows}
    or None if parsing fails.
    """
    tmp_path = None
    try:
        # Try rasterio first (lighter dependency)
        try:
            import rasterio

            with rasterio.MemoryFile(data) as memfile:
                with memfile.open() as src:
                    band = src.read(1)
                    elevations = band.tolist()
                    transform = src.transform
                    origin_lon = transform.c
                    origin_lat = transform.f
                    pixel_size_deg = abs(transform.a)
                    return {
                        "elevations": elevations,
                        "origin_lon": origin_lon,
                        "origin_lat": origin_lat,
                        "pixel_size_deg": pixel_size_deg,
                        "cols": src.width,
                        "rows": src.height,
                    }
        except ImportError:
            pass

        # Fall back to GDAL via osgeo
        try:
            from osgeo import gdal

            tmp_path = tempfile.mktemp(suffix=".tif")
            with open(tmp_path, "wb") as f:
                f.write(data)

            ds = gdal.Open(tmp_path)
            if not ds:
                return None

            band = ds.GetRasterBand(1)
            elevations = band.ReadAsArray().tolist()
            geotransform = ds.GetGeoTransform()
            cols = ds.RasterXSize
            rows = ds.RasterYSize

            ds = None
            return {
                "elevations": elevations,
                "origin_lon": geotransform[0],
                "origin_lat": geotransform[3],
                "pixel_size_deg": abs(geotransform[1]),
                "cols": cols,
                "rows": rows,
            }
        except (ImportError, AttributeError):
            pass

        logger.warning("Neither rasterio nor GDAL available for GeoTIFF parsing")
        return None

    except Exception as e:
        logger.error("GeoTIFF parsing failed: %s", e)
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
