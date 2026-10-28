"""Area-weighted percentile classification of management zones (pure)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry.base import BaseGeometry

_EPS = 1e-9


@dataclass(frozen=True)
class ZoneValue:
    id: str
    mean: float | None
    area_ha: float
    geometry: BaseGeometry  # Polygon | MultiPolygon, WGS84


def _usable(z: ZoneValue) -> bool:
    return (z.mean is not None and math.isfinite(z.mean)
            and math.isfinite(z.area_ha) and z.area_ha > 0)


def valid_zones(zones: list[ZoneValue]) -> list[ZoneValue]:
    """Zones with a usable mean and positive weight."""
    return [z for z in zones if _usable(z)]


def _cumulative(zones: list[ZoneValue]) -> list[tuple[float, float]]:
    """(mean, cumulative area fraction with mean <= m), one row per distinct mean."""
    zs = valid_zones(zones)
    total = sum(z.area_ha for z in zs)
    if not zs or total <= 0:
        return []
    by_mean: dict[float, float] = {}
    for z in zs:
        by_mean[z.mean] = by_mean.get(z.mean, 0.0) + z.area_ha
    rows, acc = [], 0.0
    for m in sorted(by_mean):
        acc += by_mean[m]
        rows.append((m, acc / total))
    return rows


def _percentile(rows: list[tuple[float, float]], pct: float) -> float:
    if pct <= 0:
        return rows[0][0]
    target = pct / 100.0
    for m, frac in rows:
        if frac >= target - _EPS:
            return m
    return rows[-1][0]


def weighted_percentiles(zones: list[ZoneValue], step: int = 5) -> list[float]:
    """Values at p0, p<step>, ..., p100 (step function, no interpolation)."""
    rows = _cumulative(zones)
    if not rows:
        return []
    return [_percentile(rows, p) for p in range(0, 101, step)]


def _ranks_by_position(zones: list[ZoneValue]) -> dict[int, float]:
    """Area-weighted midpoint rank (0-100) per zone position; equal means share a rank."""
    idx = [i for i, z in enumerate(zones) if _usable(z)]
    total = sum(zones[i].area_ha for i in idx)
    if not idx or total <= 0:
        return {}
    blocks: dict[float, list[int]] = {}
    for i in idx:
        blocks.setdefault(zones[i].mean, []).append(i)
    ranks: dict[int, float] = {}
    below = 0.0
    for m in sorted(blocks):
        area = sum(zones[i].area_ha for i in blocks[m])
        rank = (below + area / 2.0) / total * 100.0
        for i in blocks[m]:
            ranks[i] = rank
        below += area
    return ranks


def assign_by_position(zones: list[ZoneValue], classes: list[dict]) -> dict[int, int]:
    """Class index per zone position (duplicate ids stay distinct).

    Class k where min_pct <= rank < max_pct; the last class also takes rank 100.
    All-equal means (no spread) go to class 0.
    """
    ranks = _ranks_by_position(zones)
    if len({zones[i].mean for i in ranks}) == 1:
        return {i: 0 for i in ranks}
    last = len(classes) - 1
    out: dict[int, int] = {}
    for i, rank in ranks.items():
        k = last
        for j, c in enumerate(classes[:-1]):
            if rank < c["max_pct"]:
                k = j
                break
        out[i] = k
    return out


def midpoint_ranks(zones: list[ZoneValue]) -> dict[str, float]:
    """Ranks keyed by zone id (ids are expected unique; use the position API otherwise)."""
    return {zones[i].id: r for i, r in _ranks_by_position(zones).items()}


def assign_classes(zones: list[ZoneValue], classes: list[dict]) -> dict[str, int]:
    return {zones[i].id: k for i, k in assign_by_position(zones, classes).items()}
