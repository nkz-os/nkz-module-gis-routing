"""A* A->B routing on a DEM grid with two objectives: least slope, fastest.

The grid is geographic (uniform pixel size in degrees). Distances are metric-
corrected: longitude degrees shrink by cos(latitude). The two objectives use
distinct cost structures so they are guaranteed to differ on sloped terrain:

  - "fastest":      step cost = horizontal distance only.
  - "least_slope":  step cost = distance * (1 + K_SLOPE * tan(slope)), which
                    strongly penalizes steep cells.

Both use an admissible straight-line (meters) heuristic, since every step cost
is >= its distance term.
"""
from __future__ import annotations

import math
import heapq
from dataclasses import dataclass, field

_M_PER_DEG_LAT = 111320.0
_OBJECTIVES = ("least_slope", "fastest")
K_SLOPE = 80.0  # least-slope steepness penalty weight


@dataclass(order=True)
class _Node:
    f: float
    g: float = field(compare=False)
    col: int = field(compare=False)
    row: int = field(compare=False)
    parent: "_Node | None" = field(compare=False, default=None)


def _m_per_deg_lon(lat: float) -> float:
    return _M_PER_DEG_LAT * math.cos(math.radians(lat))


def _cell_dist_m(dcol: int, drow: int, lat: float, pixel_size_deg: float) -> float:
    dx = dcol * pixel_size_deg * _m_per_deg_lon(lat)
    dy = drow * pixel_size_deg * _M_PER_DEG_LAT
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
) -> list[dict]:
    """Return the least-slope and fastest A->B routes (each a dict, or omitted
    if unreachable).

    `blocked` is an optional set of (col, row) tuples that are impassable
    (e.g., rasterized exclusion zones).
    """
    routes = []
    for objective in _OBJECTIVES:
        path = _astar(
            elevations, origin_lon, origin_lat, pixel_size_deg,
            start_col, start_row, end_col, end_row, max_slope_deg, objective,
            blocked=blocked,
        )
        if path:
            smoothed = _smooth_cells(path, blocked or set())
            routes.append(_summarize(path, objective, elevations,
                                     origin_lon, origin_lat, pixel_size_deg,
                                     smoothed=smoothed))
    return routes


def _astar(elevations, origin_lon, origin_lat, pixel_size_deg,
           start_col, start_row, end_col, end_row, max_slope_deg, objective,
           blocked=None):
    rows = len(elevations)
    cols = len(elevations[0]) if rows else 0
    max_slope_rad = math.radians(max_slope_deg)

    def lat_of(r: int) -> float:
        return origin_lat + r * pixel_size_deg

    def elev(c: int, r: int) -> float:
        return elevations[r][c]

    def heuristic(c: int, r: int) -> float:
        return _cell_dist_m(end_col - c, end_row - r, lat_of(r), pixel_size_deg)

    def neighbors(c: int, r: int):
        for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (-1, -1), (1, -1), (-1, 1)):
            nc, nr = c + dc, r + dr
            if 0 <= nc < cols and 0 <= nr < rows:
                yield nc, nr

    open_set = [_Node(f=heuristic(start_col, start_row), g=0.0,
                      col=start_col, row=start_row)]
    best_g = {(start_col, start_row): 0.0}
    closed = set()

    while open_set:
        cur = heapq.heappop(open_set)
        key = (cur.col, cur.row)
        if key in closed:
            continue
        closed.add(key)
        if key == (end_col, end_row):
            return _reconstruct(cur)

        for nc, nr in neighbors(cur.col, cur.row):
            if (nc, nr) in closed:
                continue
            if blocked and (nc, nr) in blocked:
                continue
            dc = nc - cur.col
            dr = nr - cur.row
            # No corner-cutting through a no-go pinch: a diagonal move may not
            # pass between two blocked cells.
            if blocked and dc != 0 and dr != 0 and \
               (cur.col + dc, cur.row) in blocked and (cur.col, cur.row + dr) in blocked:
                continue
            dist = _cell_dist_m(nc - cur.col, nr - cur.row,
                                lat_of(cur.row), pixel_size_deg)
            dz = elev(nc, nr) - elev(cur.col, cur.row)
            slope = math.atan2(abs(dz), dist) if dist > 0 else 0.0
            if slope > max_slope_rad:
                continue
            if objective == "fastest":
                step = dist
            else:  # least_slope
                step = dist * (1.0 + K_SLOPE * math.tan(slope))
            g = cur.g + step
            if g < best_g.get((nc, nr), math.inf):
                best_g[(nc, nr)] = g
                heapq.heappush(open_set, _Node(
                    f=g + heuristic(nc, nr), g=g, col=nc, row=nr, parent=cur))
    return None


def _reconstruct(node) -> list[tuple[int, int]]:
    cells = []
    cur = node
    while cur:
        cells.append((cur.col, cur.row))
        cur = cur.parent
    cells.reverse()
    return cells


def _summarize(cells, objective, elevations,
               origin_lon, origin_lat, pixel_size_deg, smoothed=None) -> dict:
    # Metrics pass: ALWAYS over the full A* cell path (honest distance/climb).
    distance_m = 0.0
    climb_m = 0.0
    for i, (c, r) in enumerate(cells):
        if i > 0:
            pc, pr = cells[i - 1]
            distance_m += _cell_dist_m(c - pc, r - pr,
                                       origin_lat + pr * pixel_size_deg,
                                       pixel_size_deg)
            climb_m += max(0.0, elevations[r][c] - elevations[pr][pc])

    # Geometry/profile pass: over the smoothed any-angle vertices if provided.
    coords, profile = [], []
    for c, r in (smoothed if smoothed is not None else cells):
        lon = round(origin_lon + c * pixel_size_deg, 7)
        lat = round(origin_lat + r * pixel_size_deg, 7)
        z = elevations[r][c]
        coords.append([lon, lat])
        profile.append([lon, lat, z])
    return {
        "id": objective,
        "label": _LABELS[objective],
        "distance_m": round(distance_m, 1),
        "cumulative_climb_m": round(climb_m, 1),
        "geometry": {"type": "LineString", "coordinates": coords},
        "elevation_profile": profile,
    }


_LABELS = {
    "least_slope": "Least slope",
    "fastest": "Fastest route",
}


def terminus_blocked(start: tuple, end: tuple, blocked: set) -> bool:
    """True if either endpoint cell is in the blocked set (A* would start/end in a no-go zone)."""
    return start in blocked or end in blocked


def _line_of_sight(c0: int, r0: int, c1: int, r1: int, blocked: set) -> bool:
    """True if the straight segment between two cells crosses no blocked cell.

    Guarantees, for a no-go (fail-safe) context:
      - the segment does not pass through any blocked cell, and
      - a diagonal step does not slip between two diagonally-adjacent blocked
        cells (a "pinch") — the corner gap is treated as crossing.

    This is a Bresenham walk hardened against diagonal-pinch tunneling; it is
    not a full supercover traversal, but it never lets a route squeeze through
    a blocked corner gap."""
    if not blocked:
        return True
    dc = abs(c1 - c0)
    dr = abs(r1 - r0)
    sc = 1 if c1 > c0 else -1
    sr = 1 if r1 > r0 else -1
    c, r = c0, r0
    if (c, r) in blocked:
        return False
    err = dc - dr
    while c != c1 or r != r1:
        e2 = 2 * err
        stepped_c = stepped_r = False
        if e2 > -dr:
            err -= dr
            c += sc
            stepped_c = True
        if e2 < dc:
            err += dc
            r += sr
            stepped_r = True
        if stepped_c and stepped_r:
            # diagonal move: reject if it slips between two blocked corner cells
            if (c - sc, r) in blocked and (c, r - sr) in blocked:
                return False
        if (c, r) in blocked:
            return False
    return True


def _smooth_cells(cells: list[tuple[int, int]], blocked: set) -> list[tuple[int, int]]:
    """String-pull: keep a vertex only when line-of-sight to the next anchor breaks."""
    if len(cells) <= 2:
        return list(cells)
    out = [cells[0]]
    anchor = 0
    i = 1
    while i < len(cells):
        if not _line_of_sight(*cells[anchor], *cells[i], blocked):
            out.append(cells[i - 1])
            anchor = i - 1
        i += 1
    out.append(cells[-1])
    deduped = [out[0]]
    for cell in out[1:]:
        if cell != deduped[-1]:
            deduped.append(cell)
    return deduped
