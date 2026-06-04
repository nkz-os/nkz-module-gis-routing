"""Elevation provider abstraction.

A DemProvider knows whether it has data for a bbox (`covers`) and can fetch a
DEM grid for it (`fetch`). The registry tries providers by descending priority
(higher = more precise) and returns the first grid from a provider that covers
the bbox. Returns None when nothing covers — callers must fail safe.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

Bbox = tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)


@runtime_checkable
class DemProvider(Protocol):
    name: str
    priority: int

    def covers(self, bbox: Bbox) -> bool: ...

    async def fetch(self, bbox: Bbox, resolution_m: float) -> dict | None: ...


class DemRegistry:
    def __init__(self, providers: list[DemProvider]):
        self._providers = sorted(providers, key=lambda p: p.priority, reverse=True)

    async def fetch_best(self, bbox: Bbox, resolution_m: float) -> dict | None:
        for provider in self._providers:
            if provider.covers(bbox):
                grid = await provider.fetch(bbox, resolution_m)
                if grid:
                    return grid
        return None
