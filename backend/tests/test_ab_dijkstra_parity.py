"""Parity of the scipy Dijkstra search with the reference A* (same optimal cost)."""
import math

import numpy as np
import pytest

from app.services.pathfinding.least_cost_path import K_SLOPE, _cell_dist_m, _shortest_path
from tests._astar_reference import _astar

PX = 1e-4
LAT0 = 43.3
OBJECTIVES = ("least_slope", "fastest")


def path_cost(path, elevations, lat0, px, ph, objective):
    cost = 0.0
    for (c0, r0), (c1, r1) in zip(path, path[1:]):
        d = _cell_dist_m(c1 - c0, r1 - r0, lat0 + r0 * ph, px, ph)
        s = math.atan2(abs(elevations[r1][c1] - elevations[r0][c0]), d)
        cost += d if objective == "fastest" else d * (1.0 + K_SLOPE * math.tan(s))
    return cost


def _terrain(seed, rows, cols, int_elev):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:rows, 0:cols]
    z = 30 * np.sin(x / 9.0) * np.cos(y / 7.0) + 15 * np.sin(x / 4.0 + y / 5.0) + rng.standard_normal((rows, cols))
    elev = [[int(round(v)) if int_elev else float(v) for v in row] for row in z]
    for r in range(rows // 5, rows // 3):          # a no-data block
        for c in range(cols - cols // 4, cols):
            elev[r][c] = None
    wall_c = cols // 2                              # a zone wall with one gap
    zones = {(wall_c, r) for r in range(rows) if r != rows // 2}
    pinch_c = cols // 3                             # diagonal checkerboard pinch strip
    zones |= {(pinch_c + (r % 2), r) for r in range(rows // 4, 3 * rows // 4)}
    return elev, zones


def _impassable(elev, zones):
    return set(zones) | {(c, r) for r, row in enumerate(elev) for c, v in enumerate(row) if v is None}


def _check_path(path, start, end, imp):
    assert path[0] == start and path[-1] == end
    for (c0, r0), (c1, r1) in zip(path, path[1:]):
        dc, dr = c1 - c0, r1 - r0
        assert max(abs(dc), abs(dr)) == 1
        assert (c1, r1) not in imp
        if dc and dr:
            assert not ((c0 + dc, r0) in imp and (c0, r0 + dr) in imp)


def _both(elev, start, end, objective, blocked, ph=PX, max_slope=15.0):
    args = (elev, 0.0, LAT0, PX, *start, *end, max_slope, objective)
    ref = _astar(*args, blocked=blocked, pixel_height_deg=ph)
    new = _shortest_path(*args, blocked=blocked, pixel_height_deg=ph)
    return ref, new


@pytest.mark.parametrize("seed,rows,cols,int_elev,ph_ratio", [
    (1, 40, 60, False, 1.0),
    (2, 35, 50, True, 1.0),
    (3, 40, 40, False, 1.37),
])
def test_parity_random_grids(seed, rows, cols, int_elev, ph_ratio):
    elev, zones = _terrain(seed, rows, cols, int_elev)
    imp = _impassable(elev, zones)
    ph = PX * ph_ratio
    start, end = (2, rows // 2), (cols - 3, rows - 3)
    for objective in OBJECTIVES:
        ref, new = _both(elev, start, end, objective, imp, ph=ph)
        assert (ref is None) == (new is None)
        if ref is None:
            continue
        _check_path(new, start, end, imp)
        assert math.isclose(path_cost(new, elev, LAT0, PX, ph, objective),
                            path_cost(ref, elev, LAT0, PX, ph, objective), rel_tol=1e-9)


def test_start_in_blocked_matches_reference():
    elev, _ = _terrain(4, 20, 20, False)
    start, end = (3, 3), (16, 16)
    blocked = _impassable(elev, {start, (10, 10)})
    for objective in OBJECTIVES:
        ref, new = _both(elev, start, end, objective, blocked)
        assert (ref is None) == (new is None)
        if ref is not None:
            assert math.isclose(path_cost(new, elev, LAT0, PX, PX, objective),
                                path_cost(ref, elev, LAT0, PX, PX, objective), rel_tol=1e-9)


def test_out_of_grid_blocked_cells_ignored():
    rows, cols = 6, 8
    elev = [[0.0] * cols for _ in range(rows)]
    blocked = {(-1, 0), (cols, 0), (0, -1), (0, rows), (-1, -1)}
    start, end = (0, 0), (cols - 1, rows - 1)
    for objective in OBJECTIVES:
        ref, _ = _both(elev, start, end, objective, set())
        new = _shortest_path(elev, 0.0, LAT0, PX, *start, *end, 15.0, objective,
                             blocked=blocked, pixel_height_deg=PX)
        assert new is not None
        assert math.isclose(path_cost(new, elev, LAT0, PX, PX, objective),
                            path_cost(ref, elev, LAT0, PX, PX, objective), rel_tol=1e-9)


def test_start_equals_end_single_cell():
    elev = [[0.0] * 5 for _ in range(5)]
    assert _shortest_path(elev, 0.0, LAT0, PX, 2, 2, 2, 2, 15.0, "fastest",
                          blocked=set(), pixel_height_deg=PX) == [(2, 2)]


def test_no_wraparound_across_grid_edge():
    elev = [[0.0] * 5 for _ in range(5)]
    blocked = {(1, r) for r in range(5)}
    for objective in OBJECTIVES:
        assert _shortest_path(elev, 0.0, LAT0, PX, 0, 2, 4, 2, 15.0, objective,
                              blocked=blocked, pixel_height_deg=PX) is None


def test_unreachable_returns_none():
    # A 100 m cliff between columns 2 and 3 (~11 m cells): far above 15 degrees.
    elev = [[0.0, 0.0, 0.0, 100.0, 100.0, 100.0] for _ in range(4)]
    for objective in OBJECTIVES:
        assert _shortest_path(elev, 0.0, LAT0, PX, 0, 1, 5, 1, 15.0, objective,
                              blocked=set(), pixel_height_deg=PX) is None
