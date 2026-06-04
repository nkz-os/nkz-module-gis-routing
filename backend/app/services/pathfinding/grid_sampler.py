"""Build a callable(lon, lat) -> elevation_m from a DEM grid dict.

Nearest-cell lookup, clamped to the grid edges so it never raises for points
slightly outside the sampled envelope. Matches the grid contract: origin = SW
corner, row 0 southernmost, row index increases northward.
"""
from __future__ import annotations


def make_grid_sampler(grid: dict):
    elevations = grid["elevations"]
    origin_lon = grid["origin_lon"]
    origin_lat = grid["origin_lat"]
    pixel = grid["pixel_size_deg"]
    rows = grid["rows"]
    cols = grid["cols"]

    def sample(lon: float, lat: float) -> float:
        col = int(round((lon - origin_lon) / pixel))
        row = int(round((lat - origin_lat) / pixel))
        col = max(0, min(cols - 1, col))
        row = max(0, min(rows - 1, row))
        return float(elevations[row][col])

    return sample
