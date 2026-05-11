"""A* least-cost path on a DEM grid, minimizing cumulative elevation change."""
import math
import heapq
from dataclasses import dataclass, field


@dataclass(order=True)
class _Node:
    f: float
    g: float = field(compare=False)
    h: float = field(compare=False)
    col: int = field(compare=False)
    row: int = field(compare=False)
    parent: "_Node | None" = field(compare=False, default=None)


def compute_least_cost_paths(
    elevations: list[list[float]],
    origin_lon: float,
    origin_lat: float,
    pixel_size_deg: float,
    start_col: int,
    start_row: int,
    end_col: int,
    end_row: int,
    max_slope_deg: float = 15.0,
    num_alternatives: int = 3,
) -> list[dict]:
    """Compute up to num_alternatives least-cost paths using A* with varied cost weights.
    Cost function: cost = w_elev * dz + w_slope * slope_penalty + w_dist * distance
    """
    rows = len(elevations)
    cols = len(elevations[0]) if rows > 0 else 0

    def _cost_weights(alt_idx: int) -> tuple[float, float, float]:
        if alt_idx == 0:
            return (1.0, 2.0, 0.01)
        elif alt_idx == 1:
            return (0.3, 0.5, 1.0)
        else:
            return (0.1, 0.2, 2.0)

    def _heuristic(c: int, r: int, ec: int, er: int) -> float:
        return math.hypot(c - ec, r - er) * pixel_size_deg * 111320.0

    def _elevation(c: int, r: int) -> float:
        if 0 <= r < rows and 0 <= c < cols:
            return elevations[r][c]
        return float("inf")

    def _neighbors(c: int, r: int) -> list[tuple[int, int]]:
        return [
            (c + 1, r), (c - 1, r), (c, r + 1), (c, r - 1),
            (c + 1, r + 1), (c - 1, r - 1), (c + 1, r - 1), (c - 1, r + 1),
        ]

    alternatives = []
    for alt_idx in range(num_alternatives):
        w_elev, w_slope, w_dist = _cost_weights(alt_idx)
        open_set = []
        closed = set()
        start_node = _Node(f=0, g=0, h=0, col=start_col, row=start_row)
        heapq.heappush(open_set, start_node)
        found = None

        while open_set:
            current = heapq.heappop(open_set)
            if (current.col, current.row) in closed:
                continue
            closed.add((current.col, current.row))

            if current.col == end_col and current.row == end_row:
                found = current
                break

            for nc, nr in _neighbors(current.col, current.row):
                if (nc, nr) in closed:
                    continue
                ez = _elevation(nc, nr)
                if ez == float("inf"):
                    continue
                cz = _elevation(current.col, current.row)
                dz = abs(ez - cz)
                dist_m = math.hypot(nc - current.col, nr - current.row) * pixel_size_deg * 111320.0
                slope = math.atan(dz / dist_m) if dist_m > 0 else 0
                if abs(math.degrees(slope)) > max_slope_deg:
                    continue
                slope_penalty = dz if math.degrees(slope) > max_slope_deg * 0.5 else 0
                step_cost = w_elev * dz + w_slope * slope_penalty + w_dist * dist_m
                g = current.g + step_cost
                h = _heuristic(nc, nr, end_col, end_row)
                neighbor = _Node(f=g + h, g=g, h=h, col=nc, row=nr, parent=current)
                heapq.heappush(open_set, neighbor)

        if found:
            path = _reconstruct_path(found, elevations, origin_lon, origin_lat, pixel_size_deg)
            cumulative_climb = sum(
                max(0, elevations[p["row"]][p["col"]] - elevations[prev["row"]][prev["col"]])
                for prev, p in zip(path, path[1:])
            )
            total_dist = sum(
                math.hypot(
                    (p2["col"] - p1["col"]) * pixel_size_deg * 111320.0,
                    (p2["row"] - p1["row"]) * pixel_size_deg * 111320.0,
                )
                for p1, p2 in zip(path, path[1:])
            )
            alternatives.append({
                "id": f"path-{alt_idx}",
                "label": _path_label(alt_idx, total_dist, cumulative_climb),
                "distance_m": round(total_dist, 1),
                "cumulative_climb_m": round(cumulative_climb, 1),
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[p["lon"], p["lat"]] for p in path],
                },
                "elevation_profile": [[p["lon"], p["lat"], p["elevation"]] for p in path],
            })

    return alternatives


def _reconstruct_path(node, elevations, origin_lon, origin_lat, pixel_size_deg) -> list[dict]:
    path = []
    current = node
    while current:
        lon = origin_lon + current.col * pixel_size_deg
        lat = origin_lat + current.row * pixel_size_deg
        path.append({
            "col": current.col, "row": current.row,
            "lon": round(lon, 7), "lat": round(lat, 7),
            "elevation": elevations[current.row][current.col]
                if 0 <= current.row < len(elevations)
                   and 0 <= current.col < len(elevations[0])
                else 0,
        })
        current = current.parent
    path.reverse()
    return path


def _path_label(alt_idx: int, dist: float, climb: float) -> str:
    if alt_idx == 0:
        return f"Minimum elevation change ({climb:.1f}m cumulative)"
    elif alt_idx == 1:
        return f"Balanced ({dist:.0f}m, {climb:.1f}m)"
    else:
        return f"Shortest route ({dist:.0f}m)"
