"""Access path from the field gate to the route start, inside the drivable area.

Pure shapely, UTM metres. Visibility graph over the area's vertices plus
Dijkstra; an edge is valid when the segment stays within the area buffered
by a small clearance (absorbs floating-point noise on boundary vertices).
Invariant: simplify_m < CLEARANCE_M, so the chord sagitta after simplification stays
below the clearance and edges hugging an obstacle remain inside area.buffer(CLEARANCE_M).
"""
from __future__ import annotations

import heapq
import logging
import math

from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon

logger = logging.getLogger(__name__)

CLEARANCE_M = 0.05


def _as_polygon(area):
    if isinstance(area, Polygon):
        return area
    if isinstance(area, (MultiPolygon, GeometryCollection)):
        parts = [g for g in area.geoms if isinstance(g, Polygon) and not g.is_empty]
        if parts:
            logger.warning("access path: %s given, using largest polygon part", area.geom_type)
            return max(parts, key=lambda g: g.area)
    return None


def _ring_vertices(ring) -> list[tuple[float, float]]:
    return [(c[0], c[1]) for c in list(ring.coords)[:-1]]


def compute_access_path(
    start: Point, target: Point, area: Polygon, *, simplify_m: float = 0.02
) -> LineString | None:
    if simplify_m >= CLEARANCE_M:
        raise ValueError("simplify_m must be smaller than CLEARANCE_M")
    poly = _as_polygon(area)
    if poly is None or poly.is_empty:
        return None
    allowed = poly.buffer(CLEARANCE_M)
    if not (allowed.covers(start) and allowed.covers(target)):
        return None

    s = (start.x, start.y)
    t = (target.x, target.y)
    if allowed.covers(LineString([s, t])):
        return LineString([s, t])

    simple = poly.simplify(simplify_m, preserve_topology=True)
    simple_poly = _as_polygon(simple) or poly
    nodes: list[tuple[float, float]] = [s, t]
    nodes.extend(_ring_vertices(simple_poly.exterior))
    for ring in simple_poly.interiors:
        nodes.extend(_ring_vertices(ring))

    n = len(nodes)
    adj: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            a, b = nodes[i], nodes[j]
            if a == b:
                continue
            if allowed.covers(LineString([a, b])):
                w = math.hypot(b[0] - a[0], b[1] - a[1])
                adj[i].append((j, w))
                adj[j].append((i, w))

    dist = [math.inf] * n
    prev = [-1] * n
    dist[0] = 0.0
    heap = [(0.0, 0)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for v, w in adj[u]:
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))

    if math.isinf(dist[1]):
        return None
    seq = [1]
    while seq[-1] != 0:
        seq.append(prev[seq[-1]])
    seq.reverse()
    return LineString([nodes[k] for k in seq])
