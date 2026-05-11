"""DEM slope correction — adjusts swath spacing based on terrain slope."""

import math

import httpx
import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import MultiLineString

from app.services.routing.base import get_utm_crs


async def apply_dem_correction(
    swaths_wgs84: MultiLineString,
    start_point: list[float],
    heading_deg: float,
    width_m: float,
    dem_url: str,
    dem_sample_spacing_m: float = 10.0,
) -> float:
    """Sample elevation along AB reference line, compute mean slope,
    and return the corrected width so terrain distance equals width_m.

    Returns the original width_m if slope < 1° or DEM unavailable.
    """
    ref_points = _sample_ab_line(
        start_point, heading_deg, swaths_wgs84, dem_sample_spacing_m,
    )

    elevations = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for pt in ref_points:
            try:
                resp = await client.get(
                    f"{dem_url}/point",
                    params={"lat": pt[1], "lon": pt[0], "source": "auto"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    elevations.append(data["elevation_m"])
            except Exception:
                pass

    if len(elevations) < 2:
        return width_m

    slopes = []
    for i in range(1, len(elevations)):
        dz = abs(elevations[i] - elevations[i - 1])
        slopes.append(math.atan(dz / dem_sample_spacing_m))
    mean_slope = sum(slopes) / len(slopes)

    if mean_slope <= math.radians(1.0):
        return width_m

    return width_m / math.cos(mean_slope)


def _sample_ab_line(
    start_point: list[float],
    heading_deg: float,
    swaths: MultiLineString,
    spacing_m: float,
) -> list[list[float]]:
    """Sample points along the AB reference line at regular intervals."""
    if swaths.is_empty:
        return []
    ref_line = list(swaths.geoms)[0]
    centroid = ref_line.centroid
    utm_crs = get_utm_crs(centroid.x, centroid.y)
    wgs84 = CRS.from_epsg(4326)
    to_utm = Transformer.from_crs(wgs84, utm_crs, always_xy=True).transform
    to_wgs = Transformer.from_crs(utm_crs, wgs84, always_xy=True).transform

    coords = np.array(ref_line.coords)
    x, y = to_utm(coords[:, 0], coords[:, 1])

    points = []
    cumulative = 0.0
    target = 0.0
    for i in range(1, len(x)):
        dx = x[i] - x[i - 1]
        dy = y[i] - y[i - 1]
        seg_len = math.hypot(dx, dy)
        while target < cumulative + seg_len:
            t = (target - cumulative) / seg_len if seg_len > 0 else 0
            px = x[i - 1] + dx * t
            py = y[i - 1] + dy * t
            wgs_x, wgs_y = to_wgs(px, py)
            points.append([wgs_x, wgs_y])
            target += spacing_m
        cumulative += seg_len
    return points
