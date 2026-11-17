"""Reference oracle: the pre-scipy A*, kept only for parity tests."""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

from app.services.pathfinding.least_cost_path import K_SLOPE, _cell_dist_m


@dataclass(order=True)
class _Node:
    f: float
    g: float = field(compare=False)
    col: int = field(compare=False)
    row: int = field(compare=False)
    parent: "_Node | None" = field(compare=False, default=None)


def _astar(elevations, origin_lon, origin_lat, pixel_size_deg,
           start_col, start_row, end_col, end_row, max_slope_deg, objective,
           blocked=None, pixel_height_deg=None):
    rows = len(elevations)
    cols = len(elevations[0]) if rows else 0
    max_slope_rad = math.radians(max_slope_deg)
    height = pixel_height_deg or pixel_size_deg

    def lat_of(r: int) -> float:
        return origin_lat + r * height

    def elev(c: int, r: int) -> float:
        return elevations[r][c]

    def heuristic(c: int, r: int) -> float:
        return _cell_dist_m(end_col - c, end_row - r, lat_of(r), pixel_size_deg, height)

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
                                lat_of(cur.row), pixel_size_deg, height)
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
