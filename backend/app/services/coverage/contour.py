"""Choose a working heading aligned with terrain contours (across-slope).

Estimates the local gradient direction from a DEM sampler and returns the
heading perpendicular to it (i.e. along the contour), which is the across-slope
direction used for contour farming. Falls back is handled by the caller.
"""
from __future__ import annotations

import math


def best_contour_heading_deg(centroid, bbox, sampler, n: int = 8) -> float:
    """Return the contour-aligned heading in degrees (azimuth, 0=N, CW).

    centroid: (lon, lat). bbox: (min_lon, min_lat, max_lon, max_lat).
    sampler(lon, lat) -> elevation (m). n: samples per axis for the gradient.
    """
    lon0, lat0 = centroid
    min_lon, min_lat, max_lon, max_lat = bbox
    dlon = (max_lon - min_lon) / 2.0
    dlat = (max_lat - min_lat) / 2.0

    # Central-difference gradient at the centroid.
    dz_dlon = (sampler(lon0 + dlon, lat0) - sampler(lon0 - dlon, lat0)) / (2 * dlon)
    dz_dlat = (sampler(lon0, lat0 + dlat) - sampler(lon0, lat0 - dlat)) / (2 * dlat)

    # Gradient points uphill; its azimuth (0=N, CW from north).
    grad_az = math.degrees(math.atan2(dz_dlon, dz_dlat)) % 360.0
    # Contour heading is perpendicular to the gradient.
    return (grad_az + 90.0) % 360.0
