"""Resample a coarse native DEM onto a finer requested grid, bilinearly.

eu-elevation answers a request finer than its source (e.g. 10 m from a 25 m
national DEM) by block resampling: integer-metre steps every 2-3 cells, which
read as false slopes of 30-60 degrees between neighbours. Interpolating the
native grid at the requested cell centres keeps the source's own slopes and
invents no detail. Both grids are DemGrid (row 0 = south).
"""
from __future__ import annotations

import numpy as np


def _height(grid: dict) -> float:
    return grid.get("pixel_height_deg", grid["pixel_size_deg"])


def resample_bilinear(native: dict, target: dict) -> dict:
    """Return `target`'s geometry with elevations interpolated from `native`.

    Values at target cell centres; positions beyond the outermost native cell
    centres are clamped to them (no extrapolation). A target cell whose four native
    neighbours include a no-data cell is no-data (None).
    """
    nat = np.array([[np.nan if v is None else v for v in row] for row in native["elevations"]],
                   dtype=float)
    n_rows, n_cols = nat.shape
    cols, rows = target["cols"], target["rows"]
    xs = target["origin_lon"] + (np.arange(cols) + 0.5) * target["pixel_size_deg"]
    ys = target["origin_lat"] + (np.arange(rows) + 0.5) * _height(target)

    fc = np.clip((xs - native["origin_lon"]) / native["pixel_size_deg"] - 0.5, 0.0, n_cols - 1)
    fr = np.clip((ys - native["origin_lat"]) / _height(native) - 0.5, 0.0, n_rows - 1)
    c0 = np.minimum(np.floor(fc).astype(int), max(n_cols - 2, 0))
    r0 = np.minimum(np.floor(fr).astype(int), max(n_rows - 2, 0))
    c1 = np.minimum(c0 + 1, n_cols - 1)
    r1 = np.minimum(r0 + 1, n_rows - 1)
    tc = (fc - c0)[None, :]
    tr = (fr - r0)[:, None]
    R0, C0 = np.meshgrid(r0, c0, indexing="ij")
    R1, C1 = np.meshgrid(r1, c1, indexing="ij")
    z = (nat[R0, C0] * (1 - tc) * (1 - tr) + nat[R0, C1] * tc * (1 - tr)
         + nat[R1, C0] * (1 - tc) * tr + nat[R1, C1] * tc * tr)

    out = z.astype(object)
    out[np.isnan(z)] = None
    elevations = [[None if v is None else float(v) for v in row] for row in out.tolist()]
    return {
        "elevations": elevations,
        "origin_lon": target["origin_lon"],
        "origin_lat": target["origin_lat"],
        "pixel_size_deg": target["pixel_size_deg"],
        "pixel_height_deg": _height(target),
        "cols": cols,
        "rows": rows,
        "source": native.get("source") or {},
    }
