"""Least-cost A->B routing on a DEM grid with two objectives: least slope, fastest.

The grid is geographic: columns `pixel_size_deg` wide, rows `pixel_height_deg`
tall (row 0 = south). Distances are metric-corrected: longitude degrees shrink by
cos(latitude). No-data cells (None) are impassable. The two objectives use
distinct cost structures so they are guaranteed to differ on sloped terrain:

  - "fastest":      step cost = horizontal distance only.
  - "least_slope":  step cost = distance * (1 + K_SLOPE * tan(slope)), which
                    strongly penalizes steep cells.

The search is an exact Dijkstra (scipy, in C) over an 8-connected graph built
with numpy, so both objectives return an optimal path for their cost.
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

_M_PER_DEG_LAT = 111320.0
_OBJECTIVES = ("least_slope", "fastest")
K_SLOPE = 80.0  # least-slope steepness penalty weight


@lru_cache(maxsize=8192)
def _m_per_deg_lon(lat: float) -> float:
    return _M_PER_DEG_LAT * math.cos(math.radians(lat))


def _cell_dist_m(dcol: int, drow: int, lat: float, pixel_size_deg: float,
                 pixel_height_deg: float | None = None) -> float:
    dx = dcol * pixel_size_deg * _m_per_deg_lon(lat)
    dy = drow * (pixel_height_deg or pixel_size_deg) * _M_PER_DEG_LAT
    return math.hypot(dx, dy)


def compute_ab_routes(
    elevations: list[list[float]],
    origin_lon: float,
    origin_lat: float,
    pixel_size_deg: float,
    start_col: int,
    start_row: int,
    end_col: int,
    end_row: int,
    max_slope_deg: float = 15.0,
    blocked: set | None = None,
    pixel_height_deg: float | None = None,
) -> list[dict]:
    """Return the least-slope and fastest A->B routes (each a dict, or omitted
    if unreachable).

    `blocked` is an optional set of (col, row) tuples that are impassable
    (e.g., rasterized exclusion zones); no-data cells (None) are impassable too.
    `pixel_height_deg` defaults to `pixel_size_deg` (square client grids).
    """
    height = pixel_height_deg or pixel_size_deg
    # No-data cells join the blocked set, so smoothing never cuts through them either.
    nodata = {(c, r) for r, row in enumerate(elevations) for c, v in enumerate(row) if v is None}
    impassable = (blocked or set()) | nodata
    routes = []
    for objective in _OBJECTIVES:
        path = _shortest_path(
            elevations, origin_lon, origin_lat, pixel_size_deg,
            start_col, start_row, end_col, end_row, max_slope_deg, objective,
            blocked=impassable, pixel_height_deg=height,
        )
        if path:
            segment_cost = _segment_cost_fn(elevations, origin_lat, pixel_size_deg, height,
                                            max_slope_deg, objective)
            smoothed = _smooth_cells(path, impassable, segment_cost=segment_cost)
            routes.append(_summarize(path, objective, elevations,
                                     origin_lon, origin_lat, pixel_size_deg,
                                     smoothed=smoothed, blocked=blocked,
                                     pixel_height_deg=height))
    return routes


_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1))


def _grid_arrays(elevations, blocked, rows: int, cols: int) -> tuple[np.ndarray, np.ndarray]:
    """(z, impassable): elevations as float64 with NaN for no-data, and the mask of
    cells a route may not enter (no-data plus in-grid `blocked` cells; out-of-grid
    tuples are ignored, never wrapped by negative indexing)."""
    z = np.array([[np.nan if v is None else v for v in row] for row in elevations],
                 dtype=np.float64).reshape(rows, cols)
    impassable = np.isnan(z)
    for c, r in blocked or ():
        if 0 <= c < cols and 0 <= r < rows:
            impassable[r, c] = True
    return z, impassable


def _shortest_path(elevations, origin_lon, origin_lat, pixel_size_deg,
                   start_col, start_row, end_col, end_row, max_slope_deg, objective,
                   blocked=None, pixel_height_deg=None) -> list[tuple[int, int]] | None:
    """Exact least-cost 8-connected path from start to end, or None if unreachable.

    Edge rules: the destination must be passable, the step slope atan2(|dz|, dist)
    must not exceed max_slope_deg, and a diagonal step may not pass between two
    impassable side cells. Distance uses cos(latitude of the source row). The graph
    is built with numpy (one-cell impassable padding, so nothing wraps across the
    grid edge) and searched with scipy's Dijkstra in C."""
    rows = len(elevations)
    cols = len(elevations[0]) if rows else 0
    if not rows or not cols:
        return None
    height = pixel_height_deg or pixel_size_deg
    z, imp = _grid_arrays(elevations, blocked, rows, cols)
    zp = np.pad(z, 1, constant_values=np.nan)
    ip = np.pad(imp, 1, constant_values=True)
    idx = np.arange(rows * cols, dtype=np.int32).reshape(rows, cols)
    idxp = np.pad(idx, 1, constant_values=-1)
    lats = origin_lat + np.arange(rows, dtype=np.float64) * height
    m_lon = (_M_PER_DEG_LAT * np.cos(np.radians(lats)))[:, None]

    dist = np.empty((rows, cols, 8))
    slope = np.empty((rows, cols, 8))
    ok = np.empty((rows, cols, 8), dtype=bool)
    nbr = np.empty((rows, cols, 8), dtype=np.int32)
    for k, (dc, dr) in enumerate(_DIRS):
        dst = (slice(1 + dr, 1 + dr + rows), slice(1 + dc, 1 + dc + cols))
        d = np.hypot(dc * pixel_size_deg * m_lon, dr * height * _M_PER_DEG_LAT)
        dist[..., k] = d
        with np.errstate(invalid="ignore"):
            slope[..., k] = np.arctan2(np.abs(zp[dst] - z), d)
        valid = ~ip[dst]
        if dc and dr:  # no slipping between two impassable side cells
            valid &= ~(ip[1:1 + rows, 1 + dc:1 + dc + cols] & ip[1 + dr:1 + dr + rows, 1:1 + cols])
        ok[..., k] = valid
        nbr[..., k] = idxp[dst]
    with np.errstate(invalid="ignore"):
        ok &= slope <= math.radians(max_slope_deg)

    indptr = np.zeros(rows * cols + 1, dtype=np.int32)
    np.cumsum(ok.reshape(rows * cols, 8).sum(axis=1), out=indptr[1:])
    indices = nbr[ok]
    del nbr
    if objective == "fastest":
        weights = dist[ok]
    else:  # least_slope
        weights = dist[ok] * (1.0 + K_SLOPE * np.tan(slope[ok]))
    del dist, slope, ok, zp, ip, idxp
    graph = csr_matrix((weights, indices, indptr), shape=(rows * cols, rows * cols))

    start, end = int(idx[start_row, start_col]), int(idx[end_row, end_col])
    cost, pred = dijkstra(graph, indices=start, return_predecessors=True)
    if not np.isfinite(cost[end]):
        return None
    cells = []
    node = end
    while node >= 0:
        cells.append((node % cols, node // cols))
        if node == start:
            break
        node = int(pred[node])
    cells.reverse()
    return cells


def _segment_cells(c0: int, r0: int, c1: int, r1: int) -> list[tuple[int, int]]:
    """Cells of the Bresenham walk from (c0, r0) to (c1, r1), both ends included.
    Each consecutive pair is one 8-connected move; the major axis advances one
    cell per step, so step k lies at fraction k/n of the straight segment."""
    dc = abs(c1 - c0)
    dr = abs(r1 - r0)
    sc = 1 if c1 > c0 else -1
    sr = 1 if r1 > r0 else -1
    c, r = c0, r0
    cells = [(c, r)]
    err = dc - dr
    while c != c1 or r != r1:
        e2 = 2 * err
        if e2 > -dr:
            err -= dr
            c += sc
        if e2 < dc:
            err += dc
            r += sr
        cells.append((c, r))
    return cells


def _segment_steps(c0, r0, c1, r1, origin_lat, pixel_size_deg, height):
    """Steps of the straight segment: (pc, pr, c, r, line_m, edge_m) per Bresenham move.

    line_m: the step's share of the straight line, measured at the latitude of
    its source row (so a collinear run costs exactly the sum of its search edges);
    edge_m: the cell-centre distance the search uses for the same move."""
    cells = _segment_cells(c0, r0, c1, r1)
    n = len(cells) - 1
    fc, fr = (c1 - c0) / n, (r1 - r0) / n
    steps = []
    for (pc, pr), (c, r) in zip(cells, cells[1:]):
        lat = origin_lat + pr * height
        line_m = _cell_dist_m(fc, fr, lat, pixel_size_deg, height)
        edge_m = _cell_dist_m(c - pc, r - pr, lat, pixel_size_deg, height)
        steps.append((pc, pr, c, r, line_m, edge_m))
    return steps


def _segment_cost_fn(elevations, origin_lat, pixel_size_deg, height, max_slope_deg, objective):
    """segment_cost(cells, check=True) -> cost of serving the straight segment through
    `cells` for this objective, or None if a step touches no-data or breaks the slope
    limit. A step must pass BOTH the slope along the served line (what a machine
    following it climbs) and the search's own edge rule (cell-centre distance), so
    the served line stays a path the search could have taken. A one-step segment
    costs exactly its search edge; check=False skips the limit for path edges the
    search already accepted (no rounding at the limit can reject them)."""
    tan_max = math.tan(math.radians(max_slope_deg))

    def segment_cost(cells: list[tuple[int, int]], check: bool = True) -> float | None:
        if len(cells) <= 1:
            return 0.0
        (c0, r0), (c1, r1) = cells[0], cells[-1]
        cost = 0.0
        for pc, pr, c, r, line_m, edge_m in _segment_steps(c0, r0, c1, r1, origin_lat,
                                                            pixel_size_deg, height):
            z0, z1 = elevations[pr][pc], elevations[r][c]
            if z0 is None or z1 is None:
                return None
            dz = abs(z1 - z0)
            # slope > limit  <=>  dz > distance * tan(limit)
            if check and (dz > line_m * tan_max or dz > edge_m * tan_max):
                return None
            # dist * (1 + K * tan(slope)) with tan(slope) = dz / dist
            cost += line_m if objective == "fastest" else line_m + K_SLOPE * dz
        return cost

    return segment_cost


def _gradient(elevations, c: int, r: int, origin_lat, pixel_size_deg, height) -> tuple[float, float]:
    """Terrain gradient (dz/dx east, dz/dy north) in m/m at a cell: centred difference,
    one-sided next to no-data or the grid edge, 0 on an axis with no usable neighbour."""
    rows, cols = len(elevations), len(elevations[0])
    z = elevations[r][c]
    dx = pixel_size_deg * _m_per_deg_lon(origin_lat + r * height)
    dy = height * _M_PER_DEG_LAT

    def axis(prev, nxt, spacing):
        if prev is not None and nxt is not None:
            return (nxt - prev) / (2.0 * spacing)
        if nxt is not None:
            return (nxt - z) / spacing
        if prev is not None:
            return (z - prev) / spacing
        return 0.0

    west = elevations[r][c - 1] if c > 0 else None
    east = elevations[r][c + 1] if c < cols - 1 else None
    south = elevations[r - 1][c] if r > 0 else None
    north = elevations[r + 1][c] if r < rows - 1 else None
    return axis(west, east, dx), axis(south, north, dy)


def _summarize(cells, objective, elevations,
               origin_lon, origin_lat, pixel_size_deg, smoothed=None, blocked=None,
               pixel_height_deg=None) -> dict:
    """Metrics, geometry and profile of the SERVED line (the smoothed vertices):
    distance = length of its straight segments (each step at its own latitude); climb, max slope and cross slope
    over one profile point per crossed cell, placed on the segment."""
    height = pixel_height_deg or pixel_size_deg
    vertices = smoothed if smoothed is not None else cells
    coords = [[round(origin_lon + c * pixel_size_deg, 7), round(origin_lat + r * height, 7)]
              for c, r in vertices]
    c0, r0 = vertices[0]
    profile = [[coords[0][0], coords[0][1], elevations[r0][c0]]]
    served = [(c0, r0)]
    distance_m = climb_m = max_slope = max_cross = 0.0
    for (ac, ar), (bc, br) in zip(vertices, vertices[1:]):
        seg = _segment_cells(ac, ar, bc, br)
        n = len(seg) - 1
        line_m = [st[4] for st in _segment_steps(ac, ar, bc, br, origin_lat, pixel_size_deg, height)]
        distance_m += sum(line_m)
        ex = (bc - ac) * pixel_size_deg * _m_per_deg_lon(origin_lat + ar * height)
        ny = (br - ar) * height * _M_PER_DEG_LAT
        norm = math.hypot(ex, ny)
        nx, nyy = -ny / norm, ex / norm  # unit normal to the direction of travel
        for k, (c, r) in enumerate(seg):
            gx, gy = _gradient(elevations, c, r, origin_lat, pixel_size_deg, height)
            max_cross = max(max_cross, math.degrees(math.atan(abs(gx * nx + gy * nyy))))
            if k == 0:
                continue
            pc, pr = seg[k - 1]
            dz = elevations[r][c] - elevations[pr][pc]
            climb_m += max(0.0, dz)
            max_slope = max(max_slope, math.degrees(math.atan2(abs(dz), line_m[k - 1])))
            colf = ac + (bc - ac) * k / n
            rowf = ar + (br - ar) * k / n
            profile.append([round(origin_lon + colf * pixel_size_deg, 7),
                            round(origin_lat + rowf * height, 7), elevations[r][c]])
            served.append((c, r))
    return {
        "id": objective,
        "label": _LABELS[objective],
        "distance_m": round(distance_m, 1),
        "cumulative_climb_m": round(climb_m, 1),
        "max_slope_deg_found": round(max_slope, 1),
        "max_cross_slope_deg_found": round(max_cross, 1),
        "blocked_cells_hit": sum(1 for cell in served if cell in blocked) if blocked else 0,
        "geometry": {"type": "LineString", "coordinates": coords},
        "elevation_profile": profile,
    }


_LABELS = {
    "least_slope": "Least slope",
    "fastest": "Fastest route",
}


def blocked_terminus(start: tuple, end: tuple, blocked: set) -> str | None:
    """"A" or "B" for the first endpoint cell in the blocked set (A* would start/end
    in a no-go zone); None when both are clear. A is reported before B."""
    if start in blocked:
        return "A"
    if end in blocked:
        return "B"
    return None


def _line_of_sight(c0: int, r0: int, c1: int, r1: int, blocked: set,
                   segment_ok=None) -> bool:
    """True if the straight segment between two cells may be served.

    Guarantees, for a no-go (fail-safe) context:
      - the segment does not pass through any blocked cell,
      - a diagonal step does not slip between two diagonally-adjacent blocked
        cells (a "pinch") — the corner gap is treated as crossing, and
      - with segment_ok, the walk passes it (slope limit and objective cost).

    This is a Bresenham walk hardened against diagonal-pinch tunneling; it is
    not a full supercover traversal, but it never lets a route squeeze through
    a blocked corner gap."""
    if not blocked and segment_ok is None:
        return True
    cells = _segment_cells(c0, r0, c1, r1)
    if blocked:
        if cells[0] in blocked:
            return False
        for (pc, pr), (c, r) in zip(cells, cells[1:]):
            if c != pc and r != pr and (pc, r) in blocked and (c, pr) in blocked:
                return False  # diagonal move slipping between two blocked corner cells
            if (c, r) in blocked:
                return False
    return segment_ok(cells) if segment_ok is not None else True


def _smooth_cells(cells: list[tuple[int, int]], blocked: set,
                  segment_cost=None) -> list[tuple[int, int]]:
    """String-pull: keep a vertex only when line-of-sight to the next anchor breaks.

    With segment_cost, a shortcut is also refused if a step breaks the slope limit
    or if it costs more, for the route's objective, than the path piece it
    replaces (so the least-slope line keeps its gentle detour). Consecutive path
    cells are legal search moves costing exactly their edge, so the pull always
    progresses."""
    if len(cells) <= 2:
        return list(cells)
    prefix = [0.0]
    if segment_cost is not None:
        for a, b in zip(cells, cells[1:]):
            prefix.append(prefix[-1] + segment_cost([a, b], check=False))
    out = [cells[0]]
    anchor = 0
    i = 1
    while i < len(cells):
        ok = None
        if segment_cost is not None:
            budget = prefix[i] - prefix[anchor]

            def ok(walk, budget=budget):
                cost = segment_cost(walk)
                return cost is not None and cost <= budget + 1e-9 * max(1.0, budget)
        if not _line_of_sight(*cells[anchor], *cells[i], blocked, ok):
            out.append(cells[i - 1])
            anchor = i - 1
        i += 1
    out.append(cells[-1])
    deduped = [out[0]]
    for cell in out[1:]:
        if cell != deduped[-1]:
            deduped.append(cell)
    return deduped
