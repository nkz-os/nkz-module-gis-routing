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


def valid_zones(zones: list[ZoneValue]) -> list[ZoneValue]:
    """Zones with a usable mean and positive weight."""
    return [z for z in zones
            if z.mean is not None and math.isfinite(z.mean)
            and math.isfinite(z.area_ha) and z.area_ha > 0]


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


def cut_values(zones: list[ZoneValue], classes: list[dict]) -> list[float]:
    rows = _cumulative(zones)
    if not rows:
        return []
    return [_percentile(rows, c["max_pct"]) for c in classes[:-1]]


def assign_classes(zones: list[ZoneValue], classes: list[dict]) -> dict[str, int]:
    cuts = cut_values(zones, classes)
    last = len(classes) - 1
    out: dict[str, int] = {}
    for z in valid_zones(zones):
        k = last
        for i, c in enumerate(cuts):
            if z.mean <= c:
                k = i
                break
        out[z.id] = k
    return out
