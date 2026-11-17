"""Bilinear resample of a coarse native DEM onto the requested grid. Synthetic grids only."""
import pytest

from app.services.pathfinding.dem_resample import resample_bilinear

# Native: 4x4 cells of 0.004 deg (cols) x 0.003 deg (rows), south-first.
NAT_PX, NAT_H = 0.004, 0.003
O_LON, O_LAT = -1.0, 42.0


def _plane(lon, lat):
    return 100.0 + 2000.0 * (lon - O_LON) + 3000.0 * (lat - O_LAT)


def _native(none_at=None):
    el = []
    for r in range(4):
        row = []
        for c in range(4):
            lon = O_LON + (c + 0.5) * NAT_PX
            lat = O_LAT + (r + 0.5) * NAT_H
            row.append(None if (r, c) == none_at else _plane(lon, lat))
        el.append(row)
    return {"elevations": el, "origin_lon": O_LON, "origin_lat": O_LAT, "pixel_size_deg": NAT_PX,
            "pixel_height_deg": NAT_H, "cols": 4, "rows": 4, "source": {"resolution_m": 25.0}}


def _target():
    # 10x8 cells over the same box: 0.0016 x 0.0015 deg
    return {"elevations": [[0.0] * 10 for _ in range(8)], "origin_lon": O_LON, "origin_lat": O_LAT,
            "pixel_size_deg": 0.0016, "pixel_height_deg": 0.0015, "cols": 10, "rows": 8,
            "source": {"resolution_m": 25.0, "id": "first"}}


def test_plane_is_reproduced_exactly():
    out = resample_bilinear(_native(), _target())
    for r in range(8):
        lat = O_LAT + (r + 0.5) * 0.0015
        for c in range(10):
            lon = O_LON + (c + 0.5) * 0.0016
            inside = (O_LON + 0.5 * NAT_PX <= lon <= O_LON + 3.5 * NAT_PX
                      and O_LAT + 0.5 * NAT_H <= lat <= O_LAT + 3.5 * NAT_H)
            if inside:
                assert out["elevations"][r][c] == pytest.approx(_plane(lon, lat), abs=1e-6)


def test_outside_centre_range_is_clamped_not_extrapolated():
    out = resample_bilinear(_native(), _target())
    # SW target cell centre lies south-west of the first native centre: clamped to it.
    assert out["elevations"][0][0] == pytest.approx(_plane(O_LON + 0.5 * NAT_PX, O_LAT + 0.5 * NAT_H))


def test_none_neighbour_gives_none():
    out = resample_bilinear(_native(none_at=(0, 0)), _target())
    assert out["elevations"][0][0] is None
    assert out["elevations"][7][9] is not None


def test_target_geometry_and_source_kept():
    nat = _native()
    out = resample_bilinear(nat, _target())
    assert (out["origin_lon"], out["origin_lat"], out["pixel_size_deg"], out["pixel_height_deg"],
            out["cols"], out["rows"]) == (O_LON, O_LAT, 0.0016, 0.0015, 10, 8)
    assert out["source"] == nat["source"]
    assert len(out["elevations"]) == 8 and all(len(r) == 10 for r in out["elevations"])
    assert all(v is None or type(v) is float for r in out["elevations"] for v in r)
