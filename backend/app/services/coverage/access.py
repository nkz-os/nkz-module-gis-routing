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

import shapely
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


class InsidePaths:
    """Shortest paths inside one polygon, many queries over one visibility graph.

    The vertex-to-vertex edges are built once; each query only links its two end
    points. Same validity rule as the access path: a segment is an edge when it
    stays within the polygon buffered by CLEARANCE_M.
    """

    def __init__(self, area: Polygon, *, simplify_m: float = 0.02):
        if simplify_m >= CLEARANCE_M:
            raise ValueError("simplify_m must be smaller than CLEARANCE_M")
        self.allowed = area.buffer(CLEARANCE_M)
        shapely.prepare(self.allowed)
        simple = _as_polygon(area.simplify(simplify_m, preserve_topology=True)) or area
        nodes: list[tuple[float, float]] = _ring_vertices(simple.exterior)
        for ring in simple.interiors:
            nodes.extend(_ring_vertices(ring))
        self._nodes = nodes
        self._adj: list[list[tuple[int, float]]] = [[] for _ in nodes]
        pairs = [(i, j) for i in range(len(nodes)) for j in range(i + 1, len(nodes)) if nodes[i] != nodes[j]]
        if pairs:
            lines = shapely.linestrings([[nodes[i], nodes[j]] for i, j in pairs])
            for (i, j), ok in zip(pairs, shapely.covers(self.allowed, lines)):
                if ok:
                    w = math.hypot(nodes[j][0] - nodes[i][0], nodes[j][1] - nodes[i][1])
                    self._adj[i].append((j, w))
                    self._adj[j].append((i, w))

    def covers(self, p: Point) -> bool:
        return bool(self.allowed.covers(p))

    def path(self, start: Point, target: Point) -> LineString | None:
        """Shortest path from start to target inside the area, or None when there is none."""
        if not (self.covers(start) and self.covers(target)):
            return None
        s = (start.x, start.y)
        t = (target.x, target.y)
        if self.allowed.covers(LineString([s, t])):
            return LineString([s, t])
        nodes = [s, t] + self._nodes
        k = len(self._nodes)
        # Graph nodes: 0 = start, 1 = target, 2.. = polygon vertices (vertex i of self._nodes is i + 2).
        ends: list[list[tuple[int, float]]] = [[], []]
        if k:
            for e, p in enumerate((s, t)):
                lines = shapely.linestrings([[p, q] for q in self._nodes])
                for i, ok in enumerate(shapely.covers(self.allowed, lines)):
                    if ok and p != self._nodes[i]:
                        ends[e].append((i + 2, math.hypot(self._nodes[i][0] - p[0], self._nodes[i][1] - p[1])))
        to_target = {i: w for i, w in ends[1]}

        def neighbours(u: int):
            if u == 0:
                return ends[0]
            if u == 1:
                return ends[1]
            out = [(v + 2, w) for v, w in self._adj[u - 2]]
            if u in to_target:
                out.append((1, to_target[u]))
            return out

        dist = [math.inf] * (k + 2)
        prev = [-1] * (k + 2)
        dist[0] = 0.0
        heap = [(0.0, 0)]
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist[u]:
                continue
            if u == 1:
                break
            for v, w in neighbours(u):
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
        return LineString([nodes[i] for i in seq])


def compute_access_path(
    start: Point, target: Point, area: Polygon, *, simplify_m: float = 0.02
) -> LineString | None:
    if simplify_m >= CLEARANCE_M:
        raise ValueError("simplify_m must be smaller than CLEARANCE_M")
    poly = _as_polygon(area)
    if poly is None or poly.is_empty:
        return None
    return InsidePaths(poly, simplify_m=simplify_m).path(start, target)
