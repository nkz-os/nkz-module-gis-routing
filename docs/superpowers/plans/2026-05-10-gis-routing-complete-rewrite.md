# GIS Routing — Complete Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete rewrite of gis-routing module: multi-strategy route patterns, least-cost A-B pathfinding with DEM, pattern persistence for CTF, auto VRA from vegetation-health, and 3-column wizard UI with live Cesium 3D preview.

**Architecture:** Strategy pattern for routing algorithms (AB-line, AB-skip, spiral, headland, contour), unified generate endpoint, async job system for pathfinding, field_patterns persistence in TimescaleDB, React 3-column wizard with live Cesium preview via map-layer slot.

**Tech Stack:** FastAPI + asyncpg + Shapely + pyproj + httpx (backend), React 18 + TS 5 + @nekazari/sdk + @nekazari/viewer-kit + @nekazari/ui-kit + Cesium (frontend), TimescaleDB + Orion-LD (data).

---

## File Structure

```
nkz-module-gis-routing/
├── backend/app/
│   ├── api/
│   │   ├── __init__.py              # Router registration (MODIFY)
│   │   ├── routing.py              # Generate, export, parcels, equipment (REWRITE)
│   │   ├── operations.py           # Session start/close/active/coverage (MODIFY)
│   │   ├── patterns_router.py      # Pattern CRUD endpoints (NEW)
│   │   └── pathfinding_router.py   # Path A-B calculation endpoints (NEW)
│   ├── services/
│   │   ├── routing/
│   │   │   ├── __init__.py         # Strategy factory (NEW)
│   │   │   ├── base.py             # AbstractRoutingStrategy + PatternConfig + RouteResult (NEW)
│   │   │   ├── pattern_ab_line.py  # AB parallel swaths (REFACTOR from geometry.py)
│   │   │   ├── pattern_ab_skip.py  # AB with skip-row for seeding (NEW)
│   │   │   ├── pattern_spiral.py   # Spiral inside-out / outside-in (NEW)
│   │   │   ├── pattern_headland.py # Headland passes (NEW)
│   │   │   ├── pattern_contour.py  # Contour farming (NEW — NotImplemented yet)
│   │   │   ├── dem_correction.py   # DEM slope correction mixin (REFACTOR from geometry.py)
│   │   │   └── intersection.py     # Clipping + union helpers (REFACTOR from geometry.py)
│   │   ├── pathfinding/
│   │   │   ├── __init__.py         # Pathfinder factory (NEW)
│   │   │   ├── least_cost_path.py  # A* on DEM raster (NEW)
│   │   │   └── dem_fetcher.py      # Fetch DEM raster from eu-elevation (NEW)
│   │   ├── pattern_store.py        # field_patterns CRUD (NEW)
│   │   ├── orion_client.py         # Existing, keep as-is
│   │   ├── timescale_client.py     # Add field_patterns DDL (MODIFY)
│   │   ├── sync_service.py         # Keep as-is
│   │   ├── export_service.py       # Add RouteResult export support (MODIFY)
│   │   ├── vra_intersector.py      # Add rate smoothing (MODIFY)
│   │   ├── coverage_service.py     # Keep as-is
│   │   ├── active_operation_service.py  # Keep as-is
│   │   └── pmtiles_generator.py    # Remove (broken subprocess dependency) (DELETE refs)
│   └── config.py                   # Add pathfinding settings (MODIFY)
├── src/
│   ├── components/
│   │   ├── wizard/
│   │   │   ├── WizardShell.tsx        # 3-column layout (NEW)
│   │   │   ├── StepParcel.tsx         # Step 1: parcel selection (NEW)
│   │   │   ├── StepEquipment.tsx      # Step 2: equipment selection (NEW)
│   │   │   ├── StepPattern.tsx        # Step 3: pattern selector (NEW)
│   │   │   ├── StepVRA.tsx            # Step 4: VRA config (NEW)
│   │   │   └── StepGenerate.tsx       # Step 5: generate button (NEW)
│   │   ├── viewer/
│   │   │   ├── RoutePreviewMap.tsx    # Embedded Cesium map for column 2 (NEW)
│   │   │   └── GisRoutingMapLayer.tsx # map-layer slot for unified viewer (NEW)
│   │   ├── panels/
│   │   │   ├── StatsPanel.tsx         # Route statistics (NEW)
│   │   │   ├── AlternativesPanel.tsx  # Trajectory alternatives (NEW)
│   │   │   ├── ExportPanel.tsx        # ISOXML/GeoJSON/GPX export (NEW)
│   │   │   ├── SessionPanel.tsx       # Start/close operations (NEW)
│   │   │   └── HandoffPanel.tsx       # Mobile handoff (NEW)
│   │   ├── pathfinding/
│   │   │   ├── PathfindingTab.tsx     # A-B path tab (NEW)
│   │   │   └── ElevationProfile.tsx   # Elevation profile chart (NEW)
│   │   └── patterns/
│   │       └── PatternSaveLoad.tsx    # Save/load field patterns (NEW)
│   ├── services/
│   │   └── api.ts                     # API client (REWRITE)
│   ├── slots/
│   │   └── index.ts                   # Slot registration — add map-layer (MODIFY)
│   ├── App.tsx                        # 3-column wizard container (REWRITE)
│   ├── moduleEntry.ts                 # Add map-layer slot registration (MODIFY)
│   ├── i18n.ts                        # Keep as-is
│   └── locales/                       # Add new keys (MODIFY all 6 files)
├── backend/tests/                     # Rewrite tests (REWRITE)
└── k8s/
    └── backend-deployment.yaml        # Add pathfinding env vars (MODIFY)
```

---

### Task 1: Backend — Strategy Base Classes and RouteResult

**Files:**
- Create: `backend/app/services/routing/__init__.py`
- Create: `backend/app/services/routing/base.py`

- [ ] **Step 1: Create strategy factory module**

```python
# backend/app/services/routing/__init__.py
"""Routing strategy factory — returns a strategy instance by name."""

from app.services.routing.base import RoutingStrategy, PatternConfig, RouteResult

from app.services.routing.pattern_ab_line import ABLineStrategy
from app.services.routing.pattern_ab_skip import ABSkipStrategy
from app.services.routing.pattern_spiral import SpiralStrategy
from app.services.routing.pattern_headland import HeadlandStrategy

_STRATEGIES: dict[str, type[RoutingStrategy]] = {
    "ab-line": ABLineStrategy,
    "ab-skip": ABSkipStrategy,
    "spiral": SpiralStrategy,
    "headland-only": HeadlandStrategy,
}


def strategy_for(pattern: str) -> RoutingStrategy:
    """Return a routing strategy instance for the given pattern name."""
    cls = _STRATEGIES.get(pattern)
    if cls is None:
        raise ValueError(
            f"Unknown pattern '{pattern}'. "
            f"Available: {', '.join(sorted(_STRATEGIES.keys()))}"
        )
    return cls()
```

- [ ] **Step 2: Create base classes**

```python
# backend/app/services/routing/base.py
"""Abstract base for routing strategies, plus config and result types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Optional

from shapely.geometry import MultiLineString, Polygon
from pyproj import CRS, Transformer
import numpy as np


def get_utm_crs(lon: float, lat: float) -> CRS:
    zone = int((lon + 180) / 6) + 1
    is_north = lat >= 0
    epsg_code = 32600 + zone if is_north else 32700 + zone
    return CRS.from_epsg(epsg_code)


def project_polygon_to_utm(wgs84_poly: Polygon) -> tuple[Polygon, CRS, Transformer, Transformer]:
    """Project a WGS84 polygon to its local UTM zone. Returns (utm_poly, utm_crs, to_utm, to_wgs84)."""
    centroid = wgs84_poly.centroid
    utm_crs = get_utm_crs(centroid.x, centroid.y)
    wgs84_crs = CRS.from_epsg(4326)
    to_utm = Transformer.from_crs(wgs84_crs, utm_crs, always_xy=True).transform
    to_wgs84 = Transformer.from_crs(utm_crs, wgs84_crs, always_xy=True).transform

    if not wgs84_poly.is_valid:
        wgs84_poly = wgs84_poly.buffer(0)

    ext_coords = np.array(wgs84_poly.exterior.coords)
    ext_x, ext_y = to_utm(ext_coords[:, 0], ext_coords[:, 1])
    utm_exterior = np.column_stack((ext_x, ext_y))

    utm_interiors = []
    for interior in wgs84_poly.interiors:
        int_coords = np.array(interior.coords)
        int_x, int_y = to_utm(int_coords[:, 0], int_coords[:, 1])
        utm_interiors.append(np.column_stack((int_x, int_y)))

    utm_poly = Polygon(utm_exterior, utm_interiors)
    return utm_poly, utm_crs, to_utm, to_wgs84


def project_linestrings_to_wgs84(
    lines: list, to_wgs84
) -> MultiLineString:
    """Project a list of UTM LineStrings back to WGS84."""
    from shapely.geometry import LineString
    wgs_lines = []
    for line in lines:
        coords = np.array(line.coords)
        wgs_x, wgs_y = to_wgs84(coords[:, 0], coords[:, 1])
        wgs_lines.append(LineString(np.column_stack((wgs_x, wgs_y))))
    return MultiLineString(wgs_lines)


@dataclass
class PatternConfig:
    heading_deg: float = 0.0
    width_m: float = 24.0
    overlap_pct: float = 0.0       # 0-30%
    headland_passes: int = 0        # 0-3
    skip_rows: int = 0              # 0=off, 1=alternate, 2=skip-2
    direction: Literal["inside-out", "outside-in"] = "outside-in"

    @property
    def effective_width_m(self) -> float:
        return self.width_m * (1.0 - self.overlap_pct / 100.0)


@dataclass
class RouteResult:
    geometry: MultiLineString          # WGS84
    pattern: str
    swath_count: int
    headland_count: int
    total_distance_m: float
    covered_area_ha: float
    pass_order: list[list[int]] = field(default_factory=list)
    turn_points: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class RoutingStrategy(ABC):
    @abstractmethod
    def generate(
        self, polygon: Polygon, config: PatternConfig
    ) -> RouteResult:
        ...
```

- [ ] **Step 3: Run existing tests to confirm no regressions**

```bash
cd backend && python -m pytest tests/ -x -q
```

Expected: any pre-existing test failures should be noted (geometry.py still exists, no imports broken yet).

---

### Task 2: Backend — AB-Line Strategy (Refactor from geometry.py)

**Files:**
- Create: `backend/app/services/routing/pattern_ab_line.py`
- Create: `backend/app/services/routing/intersection.py`

- [ ] **Step 1: Extract intersection/clipping helpers**

```python
# backend/app/services/routing/intersection.py
"""Clipping and geometry intersection utilities shared across strategies."""

import math
import numpy as np
from shapely.geometry import LineString, MultiLineString, Polygon


def generate_parallel_swaths(
    utm_poly: Polygon,
    start_x: float,
    start_y: float,
    heading_rad: float,
    effective_width_m: float,
) -> list[LineString]:
    """Generate parallel swaths clipped to the polygon. Core AB-line algorithm."""
    dx = math.cos(heading_rad)
    dy = math.sin(heading_rad)
    p_dx = math.cos(heading_rad + math.pi / 2)
    p_dy = math.sin(heading_rad + math.pi / 2)

    minx, miny, maxx, maxy = utm_poly.bounds
    diag = math.hypot(maxx - minx, maxy - miny)

    ref_x1 = start_x - dx * diag
    ref_y1 = start_y - dy * diag
    ref_x2 = start_x + dx * diag
    ref_y2 = start_y + dy * diag

    utm_exterior = np.array(utm_poly.exterior.coords)
    offsets = []
    for point in utm_exterior:
        vx = point[0] - start_x
        vy = point[1] - start_y
        offsets.append(vx * p_dx + vy * p_dy)

    max_offset = max(offsets)
    min_offset = min(offsets)
    max_idx = int(math.ceil(max_offset / effective_width_m))
    min_idx = int(math.floor(min_offset / effective_width_m))

    swaths = []
    for i in range(min_idx, max_idx + 1):
        offset_dist = i * effective_width_m
        off_x1 = ref_x1 + p_dx * offset_dist
        off_y1 = ref_y1 + p_dy * offset_dist
        off_x2 = ref_x2 + p_dx * offset_dist
        off_y2 = ref_y2 + p_dy * offset_dist

        swath_line = LineString([(off_x1, off_y1), (off_x2, off_y2)])
        intersected = swath_line.intersection(utm_poly)
        if intersected.is_empty:
            continue
        if intersected.geom_type == "LineString":
            swaths.append(intersected)
        elif intersected.geom_type == "MultiLineString":
            for line in intersected.geoms:
                swaths.append(line)

    return swaths


def compute_total_distance_m(utm_lines: list[LineString]) -> float:
    return sum(line.length for line in utm_lines)
```

- [ ] **Step 2: Implement AB-Line strategy**

```python
# backend/app/services/routing/pattern_ab_line.py
"""AB-Line: parallel swaths with fixed heading."""

import math
import numpy as np
from shapely.geometry import LineString, MultiLineString, Polygon

from app.services.routing.base import (
    RoutingStrategy, PatternConfig, RouteResult,
    project_polygon_to_utm, project_linestrings_to_wgs84,
)
from app.services.routing.intersection import (
    generate_parallel_swaths, compute_total_distance_m,
)


class ABLineStrategy(RoutingStrategy):
    def generate(self, polygon: Polygon, config: PatternConfig) -> RouteResult:
        utm_poly, _, to_utm, to_wgs84 = project_polygon_to_utm(polygon)
        centroid = polygon.centroid
        start_x, start_y = to_utm(centroid.x, centroid.y)

        heading_rad = math.radians(90 - config.heading_deg)
        swaths_utm = generate_parallel_swaths(
            utm_poly, start_x, start_y, heading_rad, config.effective_width_m,
        )

        geometry = project_linestrings_to_wgs84(swaths_utm, to_wgs84)

        swath_count = len(swaths_utm)
        total_dist = compute_total_distance_m(swaths_utm)
        area = swath_count * config.effective_width_m * (total_dist / max(swath_count, 1))
        area_ha = area / 10000.0

        return RouteResult(
            geometry=geometry,
            pattern="ab-line",
            swath_count=swath_count,
            headland_count=0,
            total_distance_m=round(total_dist, 1),
            covered_area_ha=round(area_ha, 2),
            pass_order=[list(range(swath_count))],
            metadata={
                "heading_deg": config.heading_deg,
                "effective_width_m": round(config.effective_width_m, 2),
            },
        )
```

- [ ] **Step 3: Write AB-line unit test**

```python
# backend/tests/test_routing_strategies.py

import pytest
from shapely.geometry import Polygon
from app.services.routing import strategy_for
from app.services.routing.base import PatternConfig

SQUARE_PARCEL = Polygon([
    (-1.643, 42.816), (-1.641, 42.816),
    (-1.641, 42.818), (-1.643, 42.818),
    (-1.643, 42.816),
])


def test_ab_line_generates_swaths():
    strategy = strategy_for("ab-line")
    config = PatternConfig(heading_deg=0, width_m=24.0)
    result = strategy.generate(SQUARE_PARCEL, config)
    assert result.pattern == "ab-line"
    assert result.swath_count > 0
    assert result.total_distance_m > 0
    assert len(result.geometry.geoms) == result.swath_count


def test_ab_line_with_overlap_reduces_effective_width():
    config_no_overlap = PatternConfig(heading_deg=0, width_m=24.0, overlap_pct=0)
    config_overlap = PatternConfig(heading_deg=0, width_m=24.0, overlap_pct=10)
    s = strategy_for("ab-line")
    r1 = s.generate(SQUARE_PARCEL, config_no_overlap)
    r2 = s.generate(SQUARE_PARCEL, config_overlap)
    # Overlap produces more swaths (narrower effective width)
    assert r2.swath_count >= r1.swath_count
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_routing_strategies.py -v
```

Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
cd /home/g/Documents/nekazari/nkz-module-gis-routing
git add backend/app/services/routing/ backend/tests/test_routing_strategies.py
git commit -m "feat: add routing strategy base classes and AB-line strategy"
```

---

### Task 3: Backend — AB-Skip Strategy (Seeding)

**Files:**
- Create: `backend/app/services/routing/pattern_ab_skip.py`

- [ ] **Step 1: Implement AB-Skip strategy**

```python
# backend/app/services/routing/pattern_ab_skip.py
"""AB-Skip: alternating skip-row pattern for seeding operations."""

import math
import numpy as np
from shapely.geometry import LineString, MultiLineString, Polygon

from app.services.routing.base import (
    RoutingStrategy, PatternConfig, RouteResult,
    project_polygon_to_utm, project_linestrings_to_wgs84,
)
from app.services.routing.intersection import (
    generate_parallel_swaths, compute_total_distance_m,
)


class ABSkipStrategy(RoutingStrategy):
    def generate(self, polygon: Polygon, config: PatternConfig) -> RouteResult:
        utm_poly, _, to_utm, to_wgs84 = project_polygon_to_utm(polygon)
        centroid = polygon.centroid
        start_x, start_y = to_utm(centroid.x, centroid.y)

        heading_rad = math.radians(90 - config.heading_deg)
        spacing = config.effective_width_m * (config.skip_rows + 1)

        all_swaths = generate_parallel_swaths(
            utm_poly, start_x, start_y, heading_rad, spacing,
        )

        # Split into passes: each pass = one swath (skip_rows between)
        # For skip_rows=1: pass 0 = swaths[0,2,4,...], pass 1 = swaths[1,3,5,...]
        passes = []
        for offset in range(config.skip_rows + 1):
            pass_swaths = all_swaths[offset::config.skip_rows + 1]
            if pass_swaths:
                passes.append(pass_swaths)

        all_wgs = []
        for p in passes:
            all_wgs.extend(list(project_linestrings_to_wgs84(p, to_wgs84).geoms))

        geometry = MultiLineString(all_wgs)
        total_dist = sum(compute_total_distance_m(p) for p in passes)
        swath_count = sum(len(p) for p in passes)
        area = swath_count * config.effective_width_m * (total_dist / max(swath_count, 1))
        area_ha = area / 10000.0

        return RouteResult(
            geometry=geometry,
            pattern="ab-skip",
            swath_count=swath_count,
            headland_count=0,
            total_distance_m=round(total_dist, 1),
            covered_area_ha=round(area_ha, 2),
            pass_order=[[i for i in range(len(p))] for p in passes],
            metadata={
                "heading_deg": config.heading_deg,
                "skip_rows": config.skip_rows,
                "num_passes": len(passes),
            },
        )
```

- [ ] **Step 2: Add factory registration**

In `backend/app/services/routing/__init__.py`, add the import and registration:

```python
from app.services.routing.pattern_ab_skip import ABSkipStrategy

_STRATEGIES: dict[str, type[RoutingStrategy]] = {
    "ab-line": ABLineStrategy,
    "ab-skip": ABSkipStrategy,
    # ...
}
```

- [ ] **Step 3: Write test for AB-skip**

```python
# Add to backend/tests/test_routing_strategies.py

def test_ab_skip_generates_more_passes():
    s = strategy_for("ab-skip")
    config = PatternConfig(heading_deg=0, width_m=24.0, skip_rows=1)
    result = s.generate(SQUARE_PARCEL, config)
    assert result.pattern == "ab-skip"
    assert result.swath_count > 0
    assert len(result.pass_order) == 2  # skip_rows=1 means 2 alternating passes
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_routing_strategies.py -v
```

Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/routing/pattern_ab_skip.py backend/app/services/routing/__init__.py backend/tests/test_routing_strategies.py
git commit -m "feat: add AB-skip strategy for seeding with skip-row support"
```

---

### Task 4: Backend — Spiral Strategy (Harvesting)

**Files:**
- Create: `backend/app/services/routing/pattern_spiral.py`

- [ ] **Step 1: Implement spiral strategy**

```python
# backend/app/services/routing/pattern_spiral.py
"""Spiral pattern: inside-out or outside-in for harvesting operations."""

import math
from shapely.geometry import (
    LineString, MultiLineString, Polygon, Point,
)
from shapely.ops import linemerge

from app.services.routing.base import (
    RoutingStrategy, PatternConfig, RouteResult,
    project_polygon_to_utm, project_linestrings_to_wgs84,
)


class SpiralStrategy(RoutingStrategy):
    def generate(self, polygon: Polygon, config: PatternConfig) -> RouteResult:
        utm_poly, _, to_utm, to_wgs84 = project_polygon_to_utm(polygon)

        ew = config.effective_width_m
        offset_step = ew if config.direction == "inside-out" else -ew

        rings = []
        current = utm_poly
        while True:
            eroded = current.buffer(offset_step)
            if eroded.is_empty:
                break
            if not eroded.is_valid:
                eroded = eroded.buffer(0)
            if eroded.is_empty:
                break

            boundary = current.exterior
            if boundary is not None and not boundary.is_empty:
                rings.append(boundary)

            current = eroded
            if current.is_empty:
                break

        if config.direction == "outside-in":
            rings.reverse()

        # Connect rings into a continuous spiral
        spiral_utm = _connect_rings(rings)

        geometry = project_linestrings_to_wgs84(spiral_utm, to_wgs84)

        total_dist = sum(line.length for line in spiral_utm)
        swath_count = len(spiral_utm)
        area = swath_count * ew * (total_dist / max(swath_count, 1))
        area_ha = area / 10000.0

        return RouteResult(
            geometry=geometry,
            pattern=f"spiral-{config.direction}",
            swath_count=swath_count,
            headland_count=0,
            total_distance_m=round(total_dist, 1),
            covered_area_ha=round(area_ha, 2),
            pass_order=[list(range(swath_count))],
            metadata={
                "direction": config.direction,
                "ring_count": len(rings),
            },
        )


def _connect_rings(rings: list) -> list:
    """Connect concentric rings with diagonal transition segments."""
    if len(rings) <= 1:
        return rings

    spiral_lines = []
    for i, ring in enumerate(rings):
        coords = list(ring.coords)
        spiral_lines.append(LineString(coords))
        # Add transition to next ring
        if i < len(rings) - 1:
            next_coords = list(rings[i + 1].coords)
            if coords and next_coords:
                transition = LineString([coords[-1], next_coords[0]])
                spiral_lines.append(transition)

    return spiral_lines
```

- [ ] **Step 2: Register in factory**

```python
# In __init__.py
from app.services.routing.pattern_spiral import SpiralStrategy

_STRATEGIES = {
    # ...
    "spiral": SpiralStrategy,
}
```

- [ ] **Step 3: Write test**

```python
def test_spiral_generates_rings():
    s = strategy_for("spiral")
    config = PatternConfig(width_m=24.0, direction="outside-in")
    result = s.generate(SQUARE_PARCEL, config)
    assert "spiral" in result.pattern
    assert result.swath_count > 0
    assert result.total_distance_m > 0


def test_spiral_inside_out_vs_outside_in():
    s = strategy_for("spiral")
    c_in = PatternConfig(width_m=24.0, direction="inside-out")
    c_out = PatternConfig(width_m=24.0, direction="outside-in")
    r_in = s.generate(SQUARE_PARCEL, c_in)
    r_out = s.generate(SQUARE_PARCEL, c_out)
    # Both should produce valid results; geometry may differ
    assert r_in.swath_count > 0
    assert r_out.swath_count > 0
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_routing_strategies.py -v
```

Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/routing/pattern_spiral.py backend/app/services/routing/__init__.py backend/tests/test_routing_strategies.py
git commit -m "feat: add spiral strategy for harvesting (inside-out / outside-in)"
```

---

### Task 5: Backend — Headland Strategy

**Files:**
- Create: `backend/app/services/routing/pattern_headland.py`

- [ ] **Step 1: Implement headland-only strategy**

The headland strategy generates N perimeter passes. It will later be composable with interior patterns via a separate composed endpoint.

```python
# backend/app/services/routing/pattern_headland.py
"""Headland: perimeter passes around field boundary."""

from shapely.geometry import LineString, MultiLineString, Polygon

from app.services.routing.base import (
    RoutingStrategy, PatternConfig, RouteResult,
    project_polygon_to_utm, project_linestrings_to_wgs84,
)


class HeadlandStrategy(RoutingStrategy):
    def generate(self, polygon: Polygon, config: PatternConfig) -> RouteResult:
        utm_poly, _, _to_utm, to_wgs84 = project_polygon_to_utm(polygon)

        ew = config.effective_width_m
        passes = config.headland_passes or 2  # default 2

        headland_lines = []
        current = utm_poly
        for i in range(passes):
            offset = -ew * (0.5 + i)  # first pass at 0.5*width from edge
            eroded = current.buffer(offset)
            if eroded.is_empty:
                break
            if not eroded.is_valid:
                eroded = eroded.buffer(0)
            boundary = current.exterior
            if boundary and not boundary.is_empty:
                headland_lines.append(boundary)
            current = eroded

        geometry = project_linestrings_to_wgs84(headland_lines, to_wgs84)

        total_dist = sum(line.length for line in headland_lines)
        area = len(headland_lines) * ew * total_dist / max(len(headland_lines), 1)
        area_ha = area / 10000.0

        return RouteResult(
            geometry=geometry,
            pattern="headland-only",
            swath_count=len(headland_lines),
            headland_count=len(headland_lines),
            total_distance_m=round(total_dist, 1),
            covered_area_ha=round(area_ha, 2),
            pass_order=[list(range(len(headland_lines)))],
        )
```

- [ ] **Step 2: Register in factory**

```python
from app.services.routing.pattern_headland import HeadlandStrategy

_STRATEGIES = {
    # ...
    "headland-only": HeadlandStrategy,
}
```

- [ ] **Step 3: Write test**

```python
def test_headland_generates_perimeter_passes():
    s = strategy_for("headland-only")
    config = PatternConfig(width_m=24.0, headland_passes=3)
    result = s.generate(SQUARE_PARCEL, config)
    assert result.pattern == "headland-only"
    assert result.headland_count > 0
    assert result.swath_count > 0
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_routing_strategies.py -v
```

Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/routing/pattern_headland.py backend/app/services/routing/__init__.py backend/tests/test_routing_strategies.py
git commit -m "feat: add headland-only strategy for perimeter passes"
```

---

### Task 6: Backend — DEM Correction as Mixin

**Files:**
- Create: `backend/app/services/routing/dem_correction.py`

- [ ] **Step 1: Extract DEM correction from old geometry.py**

```python
# backend/app/services/routing/dem_correction.py
"""DEM slope correction — adjusts swath spacing based on terrain slope."""

import math
import httpx
import numpy as np
from shapely.geometry import MultiLineString

from app.services.routing.base import get_utm_crs
from pyproj import CRS, Transformer


async def apply_dem_correction(
    swaths_wgs84: MultiLineString,
    start_point: list[float],
    heading_deg: float,
    width_m: float,
    dem_url: str,
    dem_sample_spacing_m: float = 10.0,
) -> MultiLineString:
    """Sample elevation along AB reference line, compute mean slope,
    and adjust swath spacing so terrain distance equals width_m."""
    ref_points = _sample_ab_line(
        start_point, heading_deg, swaths_wgs84, dem_sample_spacing_m,
    )

    elevations = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for pt in ref_points:
            try:
                resp = await client.get(
                    f"{dem_url}/point",
                    params={"lat": pt[1], "lon": pt[0], "source": "auto"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    elevations.append(data["elevation_m"])
            except Exception:
                pass

    if len(elevations) < 2:
        return swaths_wgs84

    slopes = []
    for i in range(1, len(elevations)):
        dz = abs(elevations[i] - elevations[i - 1])
        slopes.append(math.atan(dz / dem_sample_spacing_m))
    mean_slope = sum(slopes) / len(slopes)

    if mean_slope <= math.radians(1.0):
        return swaths_wgs84

    corrected_width = width_m / math.cos(mean_slope)
    # Return corrected width — caller regenerates swaths with this width
    # We don't regenerate here to avoid circular dependency; return multiplier
    return corrected_width


def _sample_ab_line(
    start_point: list[float],
    heading_deg: float,
    swaths,
    spacing_m: float,
) -> list[list[float]]:
    if swaths.is_empty:
        return []
    ref_line = list(swaths.geoms)[0]
    centroid = ref_line.centroid
    utm_crs = get_utm_crs(centroid.x, centroid.y)
    wgs84 = CRS.from_epsg(4326)
    to_utm = Transformer.from_crs(wgs84, utm_crs, always_xy=True).transform
    to_wgs = Transformer.from_crs(utm_crs, wgs84, always_xy=True).transform

    coords = np.array(ref_line.coords)
    x, y = to_utm(coords[:, 0], coords[:, 1])

    points = []
    cumulative = 0.0
    target = 0.0
    for i in range(1, len(x)):
        dx = x[i] - x[i - 1]
        dy = y[i] - y[i - 1]
        seg_len = math.hypot(dx, dy)
        while target < cumulative + seg_len:
            t = (target - cumulative) / seg_len if seg_len > 0 else 0
            px = x[i - 1] + dx * t
            py = y[i - 1] + dy * t
            wgs_x, wgs_y = to_wgs(px, py)
            points.append([wgs_x, wgs_y])
            target += spacing_m
        cumulative += seg_len
    return points
```

- [ ] **Step 2: Write DEM correction test**

```python
# backend/tests/test_dem_correction.py
import pytest
from unittest.mock import AsyncMock, patch
from app.services.routing import strategy_for
from app.services.routing.base import PatternConfig
from shapely.geometry import Polygon

SQUARE = Polygon([
    (-1.643, 42.816), (-1.641, 42.816),
    (-1.641, 42.818), (-1.643, 42.818),
    (-1.643, 42.816),
])


@pytest.mark.asyncio
async def test_dem_correction_returns_corrected_width():
    from app.services.routing.dem_correction import apply_dem_correction
    s = strategy_for("ab-line")
    result = s.generate(SQUARE, PatternConfig(heading_deg=0, width_m=24))
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"elevation_m": 400}
        corrected = await apply_dem_correction(
            result.geometry, [-1.642, 42.817], 0, 24,
            dem_url="http://test/point",
        )
    # With flat terrain, should return original width unchanged (slope < 1°)
    assert isinstance(corrected, float) and corrected > 0
```

- [ ] **Step 3: Run tests**

```bash
cd backend && python -m pytest tests/test_dem_correction.py -v
```

Expected: 1 PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/routing/dem_correction.py backend/tests/test_dem_correction.py
git commit -m "feat: extract DEM correction into standalone mixin"
```

---

### Task 7: Backend — Unified Generate Endpoint

**Files:**
- Rewrite: `backend/app/api/routing.py`

- [ ] **Step 1: Rewrite the generate endpoint with unified request model**

Replace the existing `GenerateRequest`, `GenerateVRARequest`, `/generate`, and `/generate/with-vra` with a single unified endpoint.

```python
# backend/app/api/routing.py  (new generate section)

from pydantic import BaseModel, Field
from typing import Optional, Literal
from app.services.routing import strategy_for
from app.services.routing.base import PatternConfig
from app.services.routing.dem_correction import apply_dem_correction


class PatternConfigRequest(BaseModel):
    heading_deg: float = Field(default=0, ge=0, lt=360)
    width_m: float = Field(default=24, gt=0)
    overlap_pct: float = Field(default=0, ge=0, le=30)
    headland_passes: int = Field(default=0, ge=0, le=3)
    skip_rows: int = Field(default=0, ge=0, le=2)
    direction: Literal["inside-out", "outside-in"] = "outside-in"


class VRAConfig(BaseModel):
    enabled: bool = False
    source: Literal["vegetation-health", "orion", "external"] = "orion"
    base_rate: float = Field(default=100, gt=0)
    rate_unit: str = "l_ha"
    zone_ids: Optional[list[str]] = None
    external_features: Optional[list[dict]] = None


class GenerateRequest(BaseModel):
    parcel_geometry: dict
    parcel_id: Optional[str] = None
    tractor_id: Optional[str] = None
    implement_id: Optional[str] = None
    pattern: Literal["ab-line", "ab-skip", "spiral", "headland-only"] = "ab-line"
    pattern_config: PatternConfigRequest = Field(default_factory=PatternConfigRequest)
    operation_type: str = "spraying"
    coupling_model: str = "rigid"
    dem_correction: bool = False
    persist: bool = True
    selected_alternative_id: Optional[str] = None
    base_pattern_id: Optional[str] = None
    vra: Optional[VRAConfig] = None


@router.post("/generate")
async def generate_routing_plan(request: Request, body: GenerateRequest):
    """Unified route generation endpoint. Supports all patterns + optional VRA."""
    if body.parcel_geometry.get("type") != "Polygon":
        raise HTTPException(status_code=400, detail="parcel_geometry must be a GeoJSON Polygon")

    from shapely.geometry import shape
    wgs84_poly = shape(body.parcel_geometry)

    # Build PatternConfig
    pc = body.pattern_config
    pattern_config = PatternConfig(
        heading_deg=pc.heading_deg,
        width_m=pc.width_m,
        overlap_pct=pc.overlap_pct,
        headland_passes=pc.headland_passes,
        skip_rows=pc.skip_rows,
        direction=pc.direction,
    )

    # If base_pattern_id given, load its config and merge
    if body.base_pattern_id:
        try:
            stored = await _load_pattern_config(body.base_pattern_id)
            if stored:
                pattern_config = _merge_pattern_config(stored, pattern_config)
        except Exception:
            pass  # pattern not found → use provided config

    # Generate alternatives (0°, 45°, 90° offsets)
    strategy = strategy_for(body.pattern)
    alternatives = []
    for offset_deg in [0.0, 45.0, 90.0]:
        pc = PatternConfig(
            heading_deg=(pattern_config.heading_deg + offset_deg) % 360,
            width_m=pattern_config.width_m,
            overlap_pct=pattern_config.overlap_pct,
            headland_passes=pattern_config.headland_passes,
            skip_rows=pattern_config.skip_rows,
            direction=pattern_config.direction,
        )
        result = strategy.generate(wgs84_poly, pc)
        alternatives.append({
            "id": f"alt-{len(alternatives)}",
            "heading_deg": pc.heading_deg,
            "swath_count": result.swath_count,
            "total_distance_m": result.total_distance_m,
            "result": result,
        })

    # Pick selected alternative
    chosen = _pick_alternative(alternatives, body.selected_alternative_id, pattern_config.heading_deg)

    # Apply VRA if enabled
    prescription_map = None
    if body.vra and body.vra.enabled:
        zone_features = await _resolve_vra_zones(body, request)
        if zone_features:
            from app.services.vra_intersector import intersect_swaths_with_zones
            prescription_map = intersect_swaths_with_zones(
                chosen["result"].geometry, zone_features,
                body.vra.base_rate, pattern_config.width_m,
            )

    # Persist to Orion-LD if requested
    operation_id = None
    if body.persist and body.parcel_id:
        operation_id = await _persist_operation(
            chosen["result"], body, request, prescription_map,
        )

    # Build response
    from shapely.geometry import mapping
    return {
        "success": True,
        "alternatives": [
            {
                "id": a["id"],
                "heading_deg": a["heading_deg"],
                "swath_count": a["swath_count"],
                "total_distance_m": a["total_distance_m"],
            }
            for a in alternatives
        ],
        "data": {
            "type": "Feature",
            "geometry": mapping(chosen["result"].geometry),
            "properties": {
                "heading_deg": chosen["heading_deg"],
                "width_m": pattern_config.width_m,
                "swath_count": chosen["swath_count"],
                "total_distance_m": chosen["total_distance_m"],
                "covered_area_ha": chosen["result"].covered_area_ha,
                "pattern": body.pattern,
                "operation_id": operation_id,
                "selected_alternative_id": chosen["id"],
                "vra_enabled": prescription_map is not None,
            },
        },
        "prescription_map": prescription_map,
    }
```

- [ ] **Step 2: Add helper functions**

```python
def _pick_alternative(alternatives: list[dict], selected_id: str | None, heading: float) -> dict:
    if selected_id:
        for a in alternatives:
            if a["id"] == selected_id:
                return a
    for a in alternatives:
        if abs(a["heading_deg"] - heading) < 0.01:
            return a
    return alternatives[0]


async def _resolve_vra_zones(body: GenerateRequest, request: Request) -> list[dict]:
    """Resolve VRA zone features from configured source."""
    if body.vra.source == "external":
        from app.api.routing import _normalize_external_zone_features
        return _normalize_external_zone_features(body.vra.external_features or [])

    if body.vra.source == "vegetation-health":
        # Auto-fetch from vegetation-health service
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"http://vegetation-health-api-service:8000/"
                    f"api/vegetation/zones/{body.parcel_id}",
                    headers={"X-Tenant-ID": _get_tenant_id(request)},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return _zones_from_vegetation_health_response(data)
        except Exception:
            pass  # fall through to Orion-LD

    # Default: Orion-LD
    settings = get_settings()
    orion = OrionLDClient(settings.context_broker_url, settings.ngsi_ld_context)
    zones = await orion.query_entities("AgriManagementZone", _get_tenant_id(request))
    await orion.close()
    return _zones_from_orion(zones, body.parcel_id, body.vra.zone_ids)


def _zones_from_vegetation_health_response(data: dict) -> list[dict]:
    features = []
    for zone in data.get("data", {}).get("zones", []):
        geom = zone.get("geometry")
        if geom:
            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "zone_id": zone.get("zone_id", ""),
                    "zone_class": zone.get("zone_class", ""),
                    "prescription_rate": float(zone.get("prescription_rate", 1.0)),
                },
            })
    return features


def _zones_from_orion(zones: list[dict], parcel_id: str, zone_ids: list[str] | None) -> list[dict]:
    from app.api.routing import _relationship_target
    matched = []
    for z in zones:
        ref = _relationship_target(z, "refAgriParcel")
        if parcel_id not in ref:
            continue
        if zone_ids and z["id"] not in zone_ids:
            continue
        loc = z.get("location", {}).get("value", {})
        if loc:
            matched.append({
                "type": "Feature",
                "geometry": loc,
                "properties": {
                    "zone_id": z.get("zoneId", {}).get("value", z["id"]),
                    "zone_class": z.get("zoneClass", {}).get("value", ""),
                    "prescription_rate": float(z.get("prescriptionRate", {}).get("value", 1.0)),
                },
            })
    return matched
```

- [ ] **Step 3: Run existing tests to check for breakage**

```bash
cd backend && python -m pytest tests/ -x -q
```

Expected: tests that hit old `/generate` endpoint may fail — note them for Task 17 (test rewrite).

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/routing.py
git commit -m "feat: unified generate endpoint with strategy dispatch, VRA, and alternatives"
```

---

### Task 8: Backend — Field Patterns Persistence

**Files:**
- Create: `backend/app/services/pattern_store.py`
- Modify: `backend/app/services/timescale_client.py` (add DDL)
- Create: `backend/app/api/patterns_router.py`

- [ ] **Step 1: Add field_patterns DDL to TimescaleDB client**

In `backend/app/services/timescale_client.py`, add to the DDL string:

```python
DDL = """
-- ... existing tables ...

CREATE TABLE IF NOT EXISTS field_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    parcel_id TEXT NOT NULL,
    name TEXT NOT NULL,
    pattern_type TEXT NOT NULL,
    pattern_config JSONB NOT NULL,
    route_geojson TEXT NOT NULL,
    vra_prescription_map JSONB,
    equipment_tractor_id TEXT,
    equipment_implement_id TEXT,
    source_operation_id TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_field_patterns_parcel
    ON field_patterns(tenant_id, parcel_id);
"""
```

- [ ] **Step 2: Implement pattern store service**

```python
# backend/app/services/pattern_store.py
"""CRUD for field_patterns — reusable route templates."""

import json
import uuid
import time
from typing import Optional

from app.services.timescale_client import TimescaleDBClient


class PatternStore:
    def __init__(self, timescale: TimescaleDBClient):
        self._ts = timescale

    async def save(
        self,
        tenant_id: str,
        parcel_id: str,
        name: str,
        pattern_type: str,
        pattern_config: dict,
        route_geojson: str,
        vra_prescription_map: dict | None,
        equipment_tractor_id: str | None,
        equipment_implement_id: str | None,
        source_operation_id: str | None,
    ) -> str:
        pattern_id = str(uuid.uuid4())
        now = int(time.time() * 1000)
        await self._ts.connect()
        async with self._ts._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO field_patterns
                    (id, tenant_id, parcel_id, name, pattern_type, pattern_config,
                     route_geojson, vra_prescription_map,
                     equipment_tractor_id, equipment_implement_id,
                     source_operation_id, created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                """,
                pattern_id, tenant_id, parcel_id, name, pattern_type,
                json.dumps(pattern_config),
                route_geojson,
                json.dumps(vra_prescription_map) if vra_prescription_map else None,
                equipment_tractor_id, equipment_implement_id,
                source_operation_id, now, now,
            )
        return pattern_id

    async def list_for_parcel(
        self, tenant_id: str, parcel_id: str, active_only: bool = True,
    ) -> list[dict]:
        await self._ts.connect()
        async with self._ts._pool.acquire() as conn:
            query = """
                SELECT * FROM field_patterns
                WHERE tenant_id = $1 AND parcel_id = $2
            """
            params = [tenant_id, parcel_id]
            if active_only:
                query += " AND is_active = true"
            query += " ORDER BY updated_at DESC LIMIT 50"
            rows = await conn.fetch(query, *params)
            return [_row_to_dict(r) for r in rows]

    async def get(self, tenant_id: str, pattern_id: str) -> dict | None:
        await self._ts.connect()
        async with self._ts._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM field_patterns WHERE tenant_id = $1 AND id = $2",
                tenant_id, pattern_id,
            )
            return _row_to_dict(row) if row else None

    async def delete(self, tenant_id: str, pattern_id: str) -> bool:
        await self._ts.connect()
        async with self._ts._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE field_patterns SET is_active = false, updated_at = $3 "
                "WHERE tenant_id = $1 AND id = $2",
                tenant_id, pattern_id, int(time.time() * 1000),
            )
            return result != "UPDATE 0"


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["id"] = str(d["id"])
    if d.get("pattern_config") and isinstance(d["pattern_config"], str):
        d["pattern_config"] = json.loads(d["pattern_config"])
    if d.get("vra_prescription_map") and isinstance(d["vra_prescription_map"], str):
        d["vra_prescription_map"] = json.loads(d["vra_prescription_map"])
    return d
```

- [ ] **Step 3: Create patterns router**

```python
# backend/app/api/patterns_router.py
"""Pattern CRUD endpoints — save/load/reuse field operation templates."""

import logging
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from app.config import get_settings
from app.services.timescale_client import TimescaleDBClient
from app.services.pattern_store import PatternStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/patterns", tags=["patterns"])


def _get_tenant(request: Request) -> str:
    tid = (
        getattr(request.state, "tenant_id", None)
        or request.headers.get("x-tenant-id")
    )
    if not tid or tid == "default":
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tid


class SavePatternRequest(BaseModel):
    parcel_id: str
    name: str
    pattern_type: str
    pattern_config: dict
    route_geojson: str
    vra_prescription_map: Optional[dict] = None
    equipment_tractor_id: Optional[str] = None
    equipment_implement_id: Optional[str] = None
    source_operation_id: Optional[str] = None


@router.get("/patterns")
async def list_patterns(request: Request, parcel_id: str):
    tenant = _get_tenant(request)
    settings = get_settings()
    ts = TimescaleDBClient(dsn=settings.database_url)
    store = PatternStore(ts)
    patterns = await store.list_for_parcel(tenant, parcel_id)
    return {"success": True, "data": patterns}


@router.get("/patterns/{pattern_id}")
async def get_pattern(request: Request, pattern_id: str):
    tenant = _get_tenant(request)
    settings = get_settings()
    ts = TimescaleDBClient(dsn=settings.database_url)
    store = PatternStore(ts)
    pattern = await store.get(tenant, pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return {"success": True, "data": pattern}


@router.post("/patterns")
async def save_pattern(request: Request, body: SavePatternRequest):
    tenant = _get_tenant(request)
    settings = get_settings()
    ts = TimescaleDBClient(dsn=settings.database_url)
    store = PatternStore(ts)
    pattern_id = await store.save(
        tenant_id=tenant,
        parcel_id=body.parcel_id,
        name=body.name,
        pattern_type=body.pattern_type,
        pattern_config=body.pattern_config,
        route_geojson=body.route_geojson,
        vra_prescription_map=body.vra_prescription_map,
        equipment_tractor_id=body.equipment_tractor_id,
        equipment_implement_id=body.equipment_implement_id,
        source_operation_id=body.source_operation_id,
    )
    return {"success": True, "data": {"id": pattern_id}}


@router.delete("/patterns/{pattern_id}")
async def delete_pattern(request: Request, pattern_id: str):
    tenant = _get_tenant(request)
    settings = get_settings()
    ts = TimescaleDBClient(dsn=settings.database_url)
    store = PatternStore(ts)
    deleted = await store.delete(tenant, pattern_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return {"success": True}
```

- [ ] **Step 4: Register router in main**

In `backend/app/api/__init__.py`, add the patterns router:

```python
from app.api import routing, operations, patterns_router, pathfinding_router

router = APIRouter()
router.include_router(routing.router)
router.include_router(operations.router)
router.include_router(patterns_router.router)
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pattern_store.py backend/app/services/timescale_client.py backend/app/api/patterns_router.py backend/app/api/__init__.py
git commit -m "feat: add field pattern persistence (save/load/reuse/reuse route templates)"
```

---

### Task 9: Backend — Least-Cost Pathfinding A-B

**Files:**
- Create: `backend/app/services/pathfinding/__init__.py`
- Create: `backend/app/services/pathfinding/least_cost_path.py`
- Create: `backend/app/services/pathfinding/dem_fetcher.py`
- Create: `backend/app/api/pathfinding_router.py`

- [ ] **Step 1: Create DEM fetcher**

```python
# backend/app/services/pathfinding/dem_fetcher.py
"""Fetch DEM raster data from eu-elevation service."""

import httpx
import logging

logger = logging.getLogger(__name__)


async def fetch_dem_raster(
    dem_url: str, bbox: tuple[float, float, float, float],
) -> dict | None:
    """Fetch a DEM raster for a bounding box from eu-elevation.
    
    Returns a dict with 'elevations' (2D list), 'origin_lon', 'origin_lat',
    'pixel_size_deg', 'cols', 'rows', or None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{dem_url}/raster",
                params={
                    "min_lon": bbox[0], "min_lat": bbox[1],
                    "max_lon": bbox[2], "max_lat": bbox[3],
                    "resolution_m": 10,
                },
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning("DEM raster fetch returned %s", resp.status_code)
            return None
    except Exception as e:
        logger.error("DEM raster fetch failed: %s", e)
        return None
```

- [ ] **Step 2: Implement A* least-cost path**

```python
# backend/app/services/pathfinding/least_cost_path.py
"""A* least-cost path on a DEM grid, minimizing cumulative elevation change."""

import math
import heapq
from dataclasses import dataclass, field
from typing import Optional


@dataclass(order=True)
class _Node:
    f: float
    g: float = field(compare=False)
    h: float = field(compare=False)
    col: int = field(compare=False)
    row: int = field(compare=False)
    parent: Optional["_Node"] = field(compare=False, default=None)


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
    
    Cost function: cost = w_elev * Δz + w_slope * slope_penalty + w_dist * distance
    """
    rows = len(elevations)
    cols = len(elevations[0]) if rows > 0 else 0

    def _cost_weights(alt_idx: int) -> tuple[float, float, float]:
        """Vary weights per alternative to produce diverse paths."""
        if alt_idx == 0:
            return (1.0, 2.0, 0.01)   # min elevation change
        elif alt_idx == 1:
            return (0.3, 0.5, 1.0)    # balanced
        else:
            return (0.1, 0.2, 2.0)    # shortest distance

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
            alternatives.append({
                "id": f"path-{alt_idx}",
                "label": _path_label(alt_idx, path, cumulative_climb),
                "distance_m": round(sum(
                    math.hypot((p2["col"] - p1["col"]) * pixel_size_deg * 111320.0,
                               (p2["row"] - p1["row"]) * pixel_size_deg * 111320.0)
                    for p1, p2 in zip(path, path[1:])
                ), 1),
                "cumulative_climb_m": round(cumulative_climb, 1),
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[p["lon"], p["lat"]] for p in path],
                },
                "elevation_profile": [[p["lon"], p["lat"], p["elevation"]] for p in path],
            })

    return alternatives


def _reconstruct_path(
    node: _Node, elevations: list[list[float]],
    origin_lon: float, origin_lat: float, pixel_size_deg: float,
) -> list[dict]:
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


def _path_label(alt_idx: int, path: list, climb: float) -> str:
    d = round(sum(
        math.hypot(
            (p2["col"] - p1["col"]) * 111320.0 * 0.00001,
            (p2["row"] - p1["row"]) * 111320.0 * 0.00001,
        )
        for p1, p2 in zip(path, path[1:])
    ), 0)
    if alt_idx == 0:
        return f"Mínimo desnivel ({climb:.1f}m acumulado)"
    elif alt_idx == 1:
        return f"Balanceado ({d:.0f}m, {climb:.1f}m)"
    else:
        return f"Ruta más corta ({d:.0f}m)"
```

- [ ] **Step 3: Create pathfinding router**

```python
# backend/app/api/pathfinding_router.py
"""A-B pathfinding with DEM-based least-cost routing."""

import asyncio
import logging
import uuid
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Literal

from app.config import get_settings
from app.services.pathfinding.least_cost_path import compute_least_cost_paths
from app.services.pathfinding.dem_fetcher import fetch_dem_raster

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/path", tags=["pathfinding"])

_JOBS: dict[str, dict] = {}


class PathRequest(BaseModel):
    point_a: list[float]  # [lon, lat]
    point_b: list[float]  # [lon, lat]
    machine_width_m: float = Field(default=3.0, gt=0)
    max_slope_deg: float = Field(default=15.0, gt=0, le=45)
    min_turn_radius_m: float = Field(default=8.0, gt=0)
    elevation_source: Literal["eu-dem", "external"] = "eu-dem"
    num_alternatives: int = Field(default=3, ge=1, le=5)


@router.post("/calculate")
async def start_path_calculation(request: Request, body: PathRequest):
    """Start async A* pathfinding job. Returns job_id for polling."""
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {"status": "queued", "result": None}

    asyncio.create_task(_run_pathfinding(job_id, body))
    return {"job_id": job_id, "status": "queued"}


@router.get("/{job_id}")
async def get_path_result(job_id: str):
    """Poll for pathfinding results."""
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _run_pathfinding(job_id: str, body: PathRequest):
    try:
        settings = get_settings()
        dem_url = settings.eu_elevation_url if body.elevation_source == "eu-dem" else None
        if not dem_url:
            _JOBS[job_id] = {"status": "failed", "error": "No DEM source configured"}
            return

        lon_a, lat_a = body.point_a
        lon_b, lat_b = body.point_b
        margin = 0.005  # ~500m
        bbox = (
            min(lon_a, lon_b) - margin, min(lat_a, lat_b) - margin,
            max(lon_a, lon_b) + margin, max(lat_a, lat_b) + margin,
        )

        raster = await fetch_dem_raster(dem_url, bbox)
        if not raster:
            _JOBS[job_id] = {"status": "failed", "error": "DEM raster fetch failed"}
            return

        elevations = raster["elevations"]
        origin_lon = raster["origin_lon"]
        origin_lat = raster["origin_lat"]
        pixel_size = raster["pixel_size_deg"]

        start_col = int((lon_a - origin_lon) / pixel_size)
        start_row = int((lat_a - origin_lat) / pixel_size)
        end_col = int((lon_b - origin_lon) / pixel_size)
        end_row = int((lat_b - origin_lat) / pixel_size)

        alternatives = compute_least_cost_paths(
            elevations, origin_lon, origin_lat, pixel_size,
            max(0, min(start_col, len(elevations[0]) - 1)),
            max(0, min(start_row, len(elevations) - 1)),
            max(0, min(end_col, len(elevations[0]) - 1)),
            max(0, min(end_row, len(elevations) - 1)),
            max_slope_deg=body.max_slope_deg,
            num_alternatives=body.num_alternatives,
        )

        _JOBS[job_id] = {"status": "completed", "alternatives": alternatives}
    except Exception as e:
        logger.exception("Pathfinding job %s failed", job_id)
        _JOBS[job_id] = {"status": "failed", "error": str(e)}
```

- [ ] **Step 4: Register in API**

```python
# In backend/app/api/__init__.py, add:
from app.api import pathfinding_router
router.include_router(pathfinding_router.router)
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pathfinding/ backend/app/api/pathfinding_router.py backend/app/api/__init__.py
git commit -m "feat: add A* least-cost pathfinding with DEM-based elevation routing"
```

---

### Task 10: Backend — VRA Intersector Improvements

**Files:**
- Modify: `backend/app/services/vra_intersector.py`

- [ ] **Step 1: Add rate smoothing between adjacent zones**

```python
# Add to backend/app/services/vra_intersector.py

def _smooth_boundary_rates(segments: list[dict]) -> list[dict]:
    """Apply edge blending: segments at zone boundaries get averaged rates."""
    # Group by swath segment proximity
    for i, seg in enumerate(segments):
        if i == 0 or i == len(segments) - 1:
            continue
        prev_zone = segments[i - 1]["properties"].get("zone_id")
        curr_zone = seg["properties"].get("zone_id")
        next_zone = segments[i + 1]["properties"].get("zone_id")
        # If at zone boundary, smooth
        if prev_zone != curr_zone or curr_zone != next_zone:
            neighbors = [segments[i - 1], segments[i + 1]]
            avg_rate = sum(n["properties"]["rate"] for n in neighbors) / 2
            seg["properties"]["rate"] = round(
                seg["properties"]["rate"] * 0.7 + avg_rate * 0.3, 2,
            )
    return segments
```

- [ ] **Step 2: Add unit conversion support**

```python
# Add unit mapping to intersect_swaths_with_zones

_UNIT_CONVERSION = {
    "l_ha": 1.0,
    "kg_ha": 1.0,
    "ml_ha": 0.001,
    "g_ha": 0.001,
}

def intersect_swaths_with_zones(
    swaths, zones, base_rate, width_m, rate_unit="l_ha",
) -> dict:
    # ... existing intersection logic ...
    # Apply unit conversion when calculating rates
    factor = _UNIT_CONVERSION.get(rate_unit, 1.0)
    # ... use factor when computing segment rates ...
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/vra_intersector.py
git commit -m "feat: add rate smoothing at zone boundaries and unit conversion to VRA intersector"
```

---

### Task 11: Frontend — Wizard Shell (3-Column Layout)

**Files:**
- Create: `src/components/wizard/WizardShell.tsx`
- Rewrite: `src/App.tsx`

- [ ] **Step 1: Create the 3-column wizard shell**

```typescript
// src/components/wizard/WizardShell.tsx

import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import manifest from '../../../manifest.json';

const NS = 'gis-routing';
const { accent } = manifest;

interface WizardShellProps {
  left: React.ReactNode;
  center: React.ReactNode;
  right: React.ReactNode;
}

export const WizardShell: React.FC<WizardShellProps> = ({ left, center, right }) => {
  const { t } = useTranslation(NS);

  return (
    <div className="flex h-full min-h-screen bg-nkz-surface-alt text-nkz-text-primary font-sans">
      {/* Left: Configuration Panel */}
      <div
        className="flex-shrink-0 overflow-y-auto border-r border-nkz-default bg-nkz-surface"
        style={{ width: '30%', minWidth: 360, maxWidth: 480 }}
      >
        <div className="p-nkz-md space-y-nkz-stack">
          <div className="flex items-center gap-nkz-sm pb-nkz-md border-b border-nkz-default">
            <div
              className="w-8 h-8 rounded-nkz-md flex items-center justify-center text-white font-bold text-nkz-sm"
              style={{ backgroundColor: accent.base }}
            >
              G
            </div>
            <div>
              <h1 className="text-nkz-lg font-bold">{t('title')}</h1>
              <p className="text-nkz-xs text-nkz-text-secondary">{t('subtitle')}</p>
            </div>
          </div>
          {left}
        </div>
      </div>

      {/* Center: Map Preview */}
      <div className="flex-1 relative bg-slate-900 min-w-0">
        {center}
      </div>

      {/* Right: Stats & Export */}
      <div
        className="flex-shrink-0 overflow-y-auto border-l border-nkz-default bg-nkz-surface"
        style={{ width: '25%', minWidth: 280, maxWidth: 400 }}
      >
        <div className="p-nkz-md space-y-nkz-stack">
          {right}
        </div>
      </div>
    </div>
  );
};
```

- [ ] **Step 2: Rewrite App.tsx to use the wizard**

```typescript
// src/App.tsx

import React, { useState, useCallback } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { WizardShell } from './components/wizard/WizardShell';
import { StepParcel } from './components/wizard/StepParcel';
import { StepEquipment } from './components/wizard/StepEquipment';
import { StepPattern } from './components/wizard/StepPattern';
import { StepVRA } from './components/wizard/StepVRA';
import { StepGenerate } from './components/wizard/StepGenerate';
import { RoutePreviewMap } from './components/viewer/RoutePreviewMap';
import { StatsPanel } from './components/panels/StatsPanel';
import { AlternativesPanel } from './components/panels/AlternativesPanel';
import { ExportPanel } from './components/panels/ExportPanel';
import { SessionPanel } from './components/panels/SessionPanel';
import { HandoffPanel } from './components/panels/HandoffPanel';
import { PatternSaveLoad } from './components/patterns/PatternSaveLoad';
import { PathfindingTab } from './components/pathfinding/PathfindingTab';
import { api, type GenerateResult } from './services/api';
import manifest from '../manifest.json';

const NS = 'gis-routing';

export interface WizardState {
  parcelId: string | null;
  parcelGeometry: any | null;
  parcelName: string;
  tractorId: string | null;
  implementId: string | null;
  pattern: string;
  patternConfig: {
    headingDeg: number;
    widthM: number;
    overlapPct: number;
    headlandPasses: number;
    skipRows: number;
    direction: 'inside-out' | 'outside-in';
  };
  operationType: string;
  demCorrection: boolean;
  vraEnabled: boolean;
  vraSource: 'vegetation-health' | 'orion' | 'external';
  vraBaseRate: number;
  vraRateUnit: string;
  vraZoneIds: string[];
  vraExternalFile: any;
  basePatternId: string | null;
}

const App: React.FC = () => {
  const { t } = useTranslation(NS);
  const [activeTab, setActiveTab] = useState<'routing' | 'pathfinding'>('routing');
  const [result, setResult] = useState<GenerateResult | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewGeometry, setPreviewGeometry] = useState<any>(null);

  const [wizard, setWizard] = useState<WizardState>({
    parcelId: null,
    parcelGeometry: null,
    parcelName: '',
    tractorId: null,
    implementId: null,
    pattern: 'ab-line',
    patternConfig: {
      headingDeg: 0,
      widthM: 24,
      overlapPct: 0,
      headlandPasses: 0,
      skipRows: 1,
      direction: 'outside-in',
    },
    operationType: 'spraying',
    demCorrection: false,
    vraEnabled: false,
    vraSource: 'vegetation-health',
    vraBaseRate: 100,
    vraRateUnit: 'l_ha',
    vraZoneIds: [],
    vraExternalFile: null,
    basePatternId: null,
  });

  const updateWizard = useCallback((patch: Partial<WizardState>) => {
    setWizard(prev => ({ ...prev, ...patch }));
  }, []);

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setError(null);
    try {
      const body: any = {
        parcel_geometry: wizard.parcelGeometry,
        parcel_id: wizard.parcelId,
        tractor_id: wizard.tractorId,
        implement_id: wizard.implementId,
        pattern: wizard.pattern,
        pattern_config: {
          heading_deg: wizard.patternConfig.headingDeg,
          width_m: wizard.patternConfig.widthM,
          overlap_pct: wizard.patternConfig.overlapPct,
          headland_passes: wizard.patternConfig.headlandPasses,
          skip_rows: wizard.patternConfig.skipRows,
          direction: wizard.patternConfig.direction,
        },
        operation_type: wizard.operationType,
        dem_correction: wizard.demCorrection,
        persist: true,
        base_pattern_id: wizard.basePatternId || undefined,
        vra: wizard.vraEnabled ? {
          enabled: true,
          source: wizard.vraSource,
          base_rate: wizard.vraBaseRate,
          rate_unit: wizard.vraRateUnit,
          zone_ids: wizard.vraSource !== 'external' ? wizard.vraZoneIds : undefined,
          external_features: wizard.vraSource === 'external' ? wizard.vraExternalFile : undefined,
        } : undefined,
      };
      const res = await api.generate(body);
      setResult(res);
      setPreviewGeometry(res.data?.geometry || null);
    } catch (err: any) {
      setError(err?.message || t('errors.generateFailed'));
    } finally {
      setGenerating(false);
    }
  }, [wizard, t]);

  return (
    <WizardShell
      left={
        <>
          {/* Tab switcher: Routing | Pathfinding */}
          <div className="flex rounded-nkz-md bg-nkz-surface-alt p-1 gap-1">
            <button
              onClick={() => setActiveTab('routing')}
              className={`flex-1 text-nkz-xs py-2 rounded-nkz-sm font-medium transition-colors ${
                activeTab === 'routing'
                  ? 'bg-nkz-surface text-nkz-text-accent shadow-sm'
                  : 'text-nkz-text-secondary hover:text-nkz-text-primary'
              }`}
            >
              {t('tabs.routing')}
            </button>
            <button
              onClick={() => setActiveTab('pathfinding')}
              className={`flex-1 text-nkz-xs py-2 rounded-nkz-sm font-medium transition-colors ${
                activeTab === 'pathfinding'
                  ? 'bg-nkz-surface text-nkz-text-accent shadow-sm'
                  : 'text-nkz-text-secondary hover:text-nkz-text-primary'
              }`}
            >
              {t('tabs.pathfinding')}
            </button>
          </div>

          {activeTab === 'routing' ? (
            <>
              <StepParcel
                parcelId={wizard.parcelId}
                onParcelChange={(id, geom, name) =>
                  updateWizard({ parcelId: id, parcelGeometry: geom, parcelName: name })}
              />
              <StepEquipment
                tractorId={wizard.tractorId}
                implementId={wizard.implementId}
                operationType={wizard.operationType}
                onTractorChange={id => updateWizard({ tractorId: id })}
                onImplementChange={id => updateWizard({ implementId: id })}
                onOperationTypeChange={op => updateWizard({ operationType: op })}
              />
              <StepPattern
                config={wizard.patternConfig}
                pattern={wizard.pattern}
                operationType={wizard.operationType}
                onPatternChange={p => updateWizard({ pattern: p })}
                onConfigChange={c => updateWizard({ patternConfig: { ...wizard.patternConfig, ...c } })}
                onDemCorrectionChange={d => updateWizard({ demCorrection: d })}
                demCorrection={wizard.demCorrection}
                basePatternId={wizard.basePatternId}
                onBasePatternChange={id => updateWizard({ basePatternId: id })}
                parcelId={wizard.parcelId}
                onConfigLoaded={config => updateWizard({
                  patternConfig: {
                    headingDeg: config.heading_deg ?? wizard.patternConfig.headingDeg,
                    widthM: config.width_m ?? wizard.patternConfig.widthM,
                    overlapPct: config.overlap_pct ?? wizard.patternConfig.overlapPct,
                    headlandPasses: config.headland_passes ?? wizard.patternConfig.headlandPasses,
                    skipRows: config.skip_rows ?? wizard.patternConfig.skipRows,
                    direction: config.direction ?? wizard.patternConfig.direction,
                  },
                  pattern: config.pattern_type ?? wizard.pattern,
                })}
              />
              <StepVRA
                enabled={wizard.vraEnabled}
                source={wizard.vraSource}
                baseRate={wizard.vraBaseRate}
                rateUnit={wizard.vraRateUnit}
                zoneIds={wizard.vraZoneIds}
                parcelId={wizard.parcelId}
                onEnabledChange={v => updateWizard({ vraEnabled: v })}
                onSourceChange={s => updateWizard({ vraSource: s })}
                onBaseRateChange={r => updateWizard({ vraBaseRate: r })}
                onZoneIdsChange={ids => updateWizard({ vraZoneIds: ids })}
                onExternalFileChange={f => updateWizard({ vraExternalFile: f })}
              />
              <StepGenerate
                onGenerate={handleGenerate}
                generating={generating}
                canGenerate={Boolean(wizard.parcelId && wizard.parcelGeometry)}
                error={error}
              />
              <PatternSaveLoad
                result={result}
                parcelId={wizard.parcelId}
                tractorId={wizard.tractorId}
                implementId={wizard.implementId}
                pattern={wizard.pattern}
                patternConfig={wizard.patternConfig}
              />
            </>
          ) : (
            <PathfindingTab />
          )}
        </>
      }
      center={
        <RoutePreviewMap
          parcelGeometry={wizard.parcelGeometry}
          previewGeometry={previewGeometry}
          result={result}
          onGeometryChange={setPreviewGeometry}
        />
      }
      right={
        result ? (
          <>
            <StatsPanel result={result} />
            <AlternativesPanel
              alternatives={result.alternatives || []}
              selectedId={result.data?.properties?.selected_alternative_id || null}
              onSelect={() => {}}  // handled via re-generate
            />
            <ExportPanel operationId={result.data?.properties?.operation_id} />
            <SessionPanel operationId={result.data?.properties?.operation_id} />
            <HandoffPanel operationId={result.data?.properties?.operation_id} />
          </>
        ) : (
          <div className="flex flex-col items-center justify-center h-64 text-nkz-text-secondary text-nkz-sm">
            <p>{t('panels.emptyState')}</p>
            <p className="text-nkz-xs mt-1">{t('panels.emptyStateHint')}</p>
          </div>
        )
      }
    />
  );
};

export default App;
```

- [ ] **Step 2: Commit**

```bash
git add src/components/wizard/WizardShell.tsx src/App.tsx
git commit -m "feat: add 3-column wizard shell and App container"
```

---

### Task 12: Frontend — Step Components (Column 1)

**Files:**
- Create: `src/components/wizard/StepParcel.tsx`
- Create: `src/components/wizard/StepEquipment.tsx`
- Create: `src/components/wizard/StepPattern.tsx`
- Create: `src/components/wizard/StepVRA.tsx`
- Create: `src/components/wizard/StepGenerate.tsx`

- [ ] **Step 1: StepParcel — parcel selector with live geometry fetch**

```typescript
// src/components/wizard/StepParcel.tsx

import React, { useState, useEffect } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { MapPin, Loader2, AlertCircle, ChevronDown } from 'lucide-react';
import { api } from '../../services/api';

const NS = 'gis-routing';

interface Props {
  parcelId: string | null;
  onParcelChange: (id: string, geometry: any, name: string) => void;
}

export const StepParcel: React.FC<Props> = ({ parcelId, onParcelChange }) => {
  const { t } = useTranslation(NS);
  const [parcels, setParcels] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(true);
  const selectedName = parcels.find(p => p.id === parcelId)?.name || '';

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.listParcels()
      .then(d => { if (!cancelled) setParcels(d || []); })
      .catch(e => { if (!cancelled) setError(e?.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const handleSelect = async (id: string) => {
    if (!id) return;
    try {
      const data = await api.getParcelGeometry(id);
      onParcelChange(id, data?.geometry || null, data?.name || '');
    } catch {
      onParcelChange(id, null, '');
    }
  };

  return (
    <div className="rounded-nkz-lg border border-nkz-default bg-nkz-surface-alt">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-nkz-md py-3 text-nkz-sm font-semibold"
      >
        <span className="flex items-center gap-nkz-sm">
          <span className="w-6 h-6 rounded-full bg-nkz-text-accent text-white text-nkz-xs flex items-center justify-center">1</span>
          <MapPin className="w-4 h-4 text-nkz-text-accent" />
          {t('parcel.label')}
        </span>
        <ChevronDown className={`w-4 h-4 transition-transform ${expanded ? '' : '-rotate-90'}`} />
      </button>
      {expanded && (
        <div className="px-nkz-md pb-3 space-y-2">
          {loading ? (
            <Loader2 className="w-4 h-4 animate-spin text-nkz-text-secondary" />
          ) : error ? (
            <p className="text-nkz-xs text-nkz-text-error flex items-center gap-1">
              <AlertCircle className="w-3 h-3" />{error}
            </p>
          ) : (
            <select
              value={parcelId || ''}
              onChange={e => handleSelect(e.target.value)}
              className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm bg-nkz-surface"
            >
              <option value="">{t('parcel.select')}</option>
              {parcels.map(p => (
                <option key={p.id} value={p.id}>
                  {p.name}{p.area ? ` (${p.area.toFixed(1)} ha)` : ''}
                </option>
              ))}
            </select>
          )}
          {selectedName && (
            <p className="text-nkz-xs text-nkz-text-success">
              {t('parcel.selected')}: {selectedName}
            </p>
          )}
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 2: StepEquipment — tractor + implement selectors with SDM kinematics**

Same pattern as StepParcel: collapsible section, step number badge, selects for tractor/implement, operation type dropdown, kinematics info card.

(Full implementation code as above pattern — fetches from `api.listEquipment()`, filters by `machine_role`, shows kinematics when both selected.)

- [ ] **Step 3: StepPattern — visual pattern selector with parameter sliders**

Visual selector with SVG icons for each pattern type, sliders for heading/width/overlap/headland passes, skip rows (shown only when pattern is `ab-skip`), direction (shown only for `spiral`). Load saved patterns via `api.listPatterns(parcelId)`.

(Full implementation with debounced preview updates.)

- [ ] **Step 4: StepVRA — auto-fetch zones from vegetation-health**

Toggle VRA, auto-fetch zones when parcel selected and VRA enabled, show zone list with checkboxes, base rate input, external file upload fallback.

(Full implementation — `api.getVRAZones(parcelId)` fetches from vegetation-health first, falls back to Orion-LD.)

- [ ] **Step 5: StepGenerate — big generate button with validation summary**

Shows checklist of prerequisites (parcel ✓, equipment ✓, pattern configured ✓), generate button, error display.

(Full implementation.)

- [ ] **Step 6: Commit**

```bash
git add src/components/wizard/Step*.tsx
git commit -m "feat: add wizard step components (parcel, equipment, pattern, VRA, generate)"
```

---

### Task 13: Frontend — Cesium Map Preview & Map-Layer Slot

**Files:**
- Create: `src/components/viewer/RoutePreviewMap.tsx`
- Create: `src/components/viewer/GisRoutingMapLayer.tsx`
- Modify: `src/slots/index.ts`

- [ ] **Step 1: Create map-layer slot component for unified viewer**

```typescript
// src/components/viewer/GisRoutingMapLayer.tsx

import React, { useEffect, useRef } from 'react';
import { useViewer, useTranslation } from '@nekazari/sdk';

const NS = 'gis-routing';

interface Props {
  viewer?: any;  // Cesium viewer instance from SlotRenderer additionalProps
}

export const GisRoutingMapLayer: React.FC<Props> = ({ viewer }) => {
  const { t } = useTranslation(NS);
  const { selectedEntityId } = useViewer();
  const entitiesRef = useRef<string[]>([]);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed?.()) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    // Listen for custom event from the module: route generated
    const handler = (e: CustomEvent) => {
      const { geometry, prescriptionMap } = e.detail || {};
      // Clear previous entities
      entitiesRef.current.forEach(id => viewer.entities.removeById(id));
      entitiesRef.current = [];

      if (geometry?.type === 'MultiLineString') {
        geometry.coordinates.forEach((coords: number[][], idx: number) => {
          const entityId = `gis-routing-swatch-${idx}`;
          entitiesRef.current.push(entityId);
          viewer.entities.add({
            id: entityId,
            polyline: {
              positions: Cesium.Cartesian3.fromDegreesArray(
                coords.flatMap(([lon, lat]) => [lon, lat]),
              ),
              width: 3,
              material: Cesium.Color.fromCssColorString('#F59E0B'),
              clampToGround: true,
            },
          });
        });
      }

      if (prescriptionMap?.features) {
        prescriptionMap.features.forEach((feat: any, idx: number) => {
          if (feat.geometry?.type === 'Polygon') {
            const entityId = `gis-routing-vra-${idx}`;
            entitiesRef.current.push(entityId);
            const rings = feat.geometry.coordinates.map((ring: number[][]) =>
              ring.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat)),
            );
            const rate = feat.properties?.rate || 0;
            const alpha = 0.3 + Math.min(rate / 200, 0.5);
            viewer.entities.add({
              id: entityId,
              polygon: {
                hierarchy: rings[0],
                material: Cesium.Color.fromCssColorString('#ef4444').withAlpha(alpha),
                clampToGround: true,
              },
            });
          }
        });
      }
    };

    window.addEventListener('nekazari:gis-routing:routeGenerated', handler as EventListener);
    return () => {
      window.removeEventListener('nekazari:gis-routing:routeGenerated', handler as EventListener);
      entitiesRef.current.forEach(id => {
        if (!viewer.isDestroyed?.()) viewer.entities.removeById(id);
      });
    };
  }, [viewer, t]);

  return null; // Invisible — only manipulates Cesium entities
};
```

- [ ] **Step 2: Register map-layer slot**

```typescript
// In src/slots/index.ts, add:
import { GisRoutingMapLayer } from '../components/viewer/GisRoutingMapLayer';

export const moduleSlots: ModuleViewerSlots = {
  'map-layer': [
    {
      id: 'gis-routing-map-layer',
      moduleId: MODULE_ID,
      component: 'GisRoutingMapLayer',
      localComponent: GisRoutingMapLayer,
      priority: 10,
    },
  ],
  // ... existing context-panel slot ...
};
```

- [ ] **Step 3: Create embedded preview map for the wizard**

```typescript
// src/components/viewer/RoutePreviewMap.tsx

import React, { useRef, useEffect } from 'react';

interface Props {
  parcelGeometry: any;
  previewGeometry: any;
  result: any;
  onGeometryChange: (geom: any) => void;
}

export const RoutePreviewMap: React.FC<Props> = ({
  parcelGeometry, previewGeometry, result,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);

  // Dispatch route geometry to map-layer slot via custom event
  useEffect(() => {
    if (result) {
      window.dispatchEvent(new CustomEvent('nekazari:gis-routing:routeGenerated', {
        detail: {
          geometry: result.data?.geometry,
          prescriptionMap: result.prescription_map,
        },
      }));
    }
  }, [result]);

  return (
    <div ref={containerRef} className="w-full h-full relative bg-slate-900">
      {/* Reuse CesiumMap component from host — this is mounted inside
          the module page which lives in an iframe-like context.
          For the IIFE bundle, we use a lightweight Cesium viewer directly. */}
      <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-nkz-sm">
        {!parcelGeometry ? (
          <div className="text-center">
            <p>Selecciona una parcela para ver la previsualización</p>
          </div>
        ) : !previewGeometry ? (
          <div className="text-center">
            <p>Configura el patrón y pulsa Generar</p>
          </div>
        ) : null}
      </div>
    </div>
  );
};
```

- [ ] **Step 4: Commit**

```bash
git add src/components/viewer/ src/slots/index.ts
git commit -m "feat: add Cesium map-layer slot and route preview map component"
```

---

### Task 14: Frontend — Stats, Export, Session, Handoff Panels (Column 3)

**Files:**
- Create: `src/components/panels/StatsPanel.tsx`
- Create: `src/components/panels/AlternativesPanel.tsx`
- Create: `src/components/panels/ExportPanel.tsx`
- Create: `src/components/panels/SessionPanel.tsx`
- Create: `src/components/panels/HandoffPanel.tsx`

- [ ] **Step 1: Create all 5 panel components**

```typescript
// src/components/panels/StatsPanel.tsx
import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { BarChart3 } from 'lucide-react';

const NS = 'gis-routing';

interface Props {
  result: any;
}

export const StatsPanel: React.FC<Props> = ({ result }) => {
  const { t } = useTranslation(NS);
  const p = result?.data?.properties || {};
  return (
    <div className="rounded-nkz-lg border border-nkz-default p-nkz-md bg-nkz-surface-alt">
      <h3 className="text-nkz-xs font-semibold text-nkz-text-secondary uppercase flex items-center gap-1 mb-3">
        <BarChart3 className="w-3.5 h-3.5" />
        {t('stats.title')}
      </h3>
      <dl className="space-y-2 text-nkz-sm">
        <div className="flex justify-between">
          <dt className="text-nkz-text-secondary">{t('stats.swaths')}</dt>
          <dd className="font-bold text-nkz-text-primary">{p.swath_count ?? '-'}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-nkz-text-secondary">{t('stats.distance')}</dt>
          <dd className="font-bold text-nkz-text-primary">
            {p.total_distance_m ? `${(p.total_distance_m / 1000).toFixed(2)} km` : '-'}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-nkz-text-secondary">{t('stats.area')}</dt>
          <dd className="font-bold text-nkz-text-primary">
            {p.covered_area_ha ? `${p.covered_area_ha.toFixed(1)} ha` : '-'}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-nkz-text-secondary">{t('stats.pattern')}</dt>
          <dd className="font-bold text-nkz-text-accent">{p.pattern ?? '-'}</dd>
        </div>
        {p.vra_enabled && (
          <div className="flex justify-between">
            <dt className="text-nkz-text-secondary">{t('stats.vra')}</dt>
            <dd className="font-bold text-nkz-text-success">{t('common.enabled')}</dd>
          </div>
        )}
      </dl>
    </div>
  );
};

// AlternativesPanel, ExportPanel, SessionPanel, HandoffPanel follow same pattern
// with appropriate icons, API calls via api.*, and loading states
```

- [ ] **Step 2: Commit**

```bash
git add src/components/panels/
git commit -m "feat: add right-column panels (stats, alternatives, export, session, handoff)"
```

---

### Task 15: Frontend — Pattern Save/Load & PathfindingTab

**Files:**
- Create: `src/components/patterns/PatternSaveLoad.tsx`
- Create: `src/components/pathfinding/PathfindingTab.tsx`
- Create: `src/components/pathfinding/ElevationProfile.tsx`

- [ ] **Step 1: PatternSaveLoad component**

Save button that appears after successful generation, load dropdown with saved patterns for the parcel.

```typescript
// src/components/patterns/PatternSaveLoad.tsx
import React, { useState, useEffect } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Save, FolderOpen, Loader2 } from 'lucide-react';
import { api } from '../../services/api';

const NS = 'gis-routing';

interface Props {
  result: any;
  parcelId: string | null;
  tractorId: string | null;
  implementId: string | null;
  pattern: string;
  patternConfig: any;
}

export const PatternSaveLoad: React.FC<Props> = ({
  result, parcelId, tractorId, implementId, pattern, patternConfig,
}) => {
  const { t } = useTranslation(NS);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [name, setName] = useState('');

  if (!result || !parcelId) return null;

  const handleSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await api.savePattern({
        parcel_id: parcelId,
        name: name.trim(),
        pattern_type: pattern,
        pattern_config: patternConfig,
        route_geojson: JSON.stringify(result.data?.geometry),
        vra_prescription_map: result.prescription_map || null,
        equipment_tractor_id: tractorId,
        equipment_implement_id: implementId,
        source_operation_id: result.data?.properties?.operation_id || null,
      });
      setSaved(true);
    } catch {} finally { setSaving(false); }
  };

  return (
    <div className="rounded-nkz-lg border border-nkz-default p-nkz-md bg-nkz-surface-alt space-y-2">
      <h3 className="text-nkz-xs font-semibold text-nkz-text-secondary uppercase flex items-center gap-1">
        <Save className="w-3.5 h-3.5" />
        {t('patterns.saveTitle')}
      </h3>
      {saved ? (
        <p className="text-nkz-xs text-nkz-text-success">{t('patterns.saved')}</p>
      ) : (
        <>
          <input
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder={t('patterns.namePlaceholder')}
            className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm bg-nkz-surface"
          />
          <button
            onClick={handleSave}
            disabled={saving || !name.trim()}
            className="w-full py-2 rounded-nkz-md text-nkz-xs font-semibold text-nkz-text-on-accent disabled:opacity-50"
            style={{ backgroundColor: '#CA8A04' }}
          >
            {saving ? <Loader2 className="w-3 h-3 animate-spin inline mr-1" /> : null}
            {t('patterns.save')}
          </button>
        </>
      )}
    </div>
  );
};
```

- [ ] **Step 2: PathfindingTab component**

Two-point selector (click on map or enter coordinates), machine constraints (width, max slope, turn radius), "Calculate" button, results display with elevation profile chart.

```typescript
// src/components/pathfinding/PathfindingTab.tsx
// Full implementation with:
// - Point A / Point B inputs (lat/lon)
// - Machine constraints sliders
// - Calculate button → POST /api/routing/path/calculate
// - Polling GET /api/routing/path/{job_id}
// - Results: 3 alternatives with elevation profile
// - Export selected path as GeoJSON/GPX
```

- [ ] **Step 3: ElevationProfile component**

Simple SVG line chart showing distance vs elevation for a path alternative.

- [ ] **Step 4: Commit**

```bash
git add src/components/patterns/ src/components/pathfinding/
git commit -m "feat: add pattern save/load and A-B pathfinding UI with elevation profile"
```

---

### Task 16: Frontend — API Client Rewrite

**Files:**
- Rewrite: `src/services/api.ts`

- [ ] **Step 1: Rewrite API client with all new endpoints**

```typescript
// src/services/api.ts (complete rewrite)

const BASE_URL = (() => {
  const env = (window as any).__ENV__;
  return (env?.VITE_API_URL || 'https://nkz.robotika.cloud') + '/api/routing';
})();

function getTenantId(): string | undefined {
  const ctx = (window as any).__nekazariAuthContext;
  return ctx?.tenantId || ctx?.tenantProfile?.id || undefined;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };
  const tid = getTenantId();
  if (tid) headers['X-Tenant-ID'] = tid;
  const resp = await fetch(`${BASE_URL}${path}`, { ...options, headers, credentials: 'include' });
  if (!resp.ok) {
    const error = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new ApiError(resp.status, error);
  }
  return resp.json();
}

export class ApiError extends Error {
  status: number; body: any;
  constructor(status: number, body: any) {
    const detail = body?.detail;
    const msg = typeof detail === 'string' ? detail
      : detail?.error?.message || `HTTP ${status}`;
    super(msg);
    this.status = status;
    this.body = body;
  }
}

export interface GenerateResult {
  success: boolean;
  alternatives: Array<{ id: string; heading_deg: number; swath_count: number; total_distance_m: number }>;
  data: { type: string; geometry: any; properties: Record<string, any> };
  prescription_map: any;
}

export interface PatternSummary {
  id: string;
  name: string;
  pattern_type: string;
  pattern_config: any;
  created_at: number;
}

export const api = {
  // Generation
  generate(body: any): Promise<GenerateResult> {
    return request('/generate', { method: 'POST', body: JSON.stringify(body) });
  },

  // Parcels
  listParcels() { return request<any[]>('/parcels'); },
  getParcelGeometry(parcelId: string) {
    return request<{ id: string; name: string; geometry: any }>(`/parcels/${encodeURIComponent(parcelId)}/geometry`);
  },

  // Equipment
  listEquipment() { return request<any[]>('/equipment'); },

  // VRA Zones
  getVRAZones(parcelId: string) {
    return request<any>(`/zones/${encodeURIComponent(parcelId)}`);
  },

  // Operations
  listOperations(limit = 20) { return request<any[]>(`/operations?limit=${limit}`); },
  startOperation(operationId: string) {
    return request('/operations/session/start', {
      method: 'POST',
      body: JSON.stringify({ operation_id: operationId, start_date: new Date().toISOString(), status: 'in_progress' }),
    });
  },
  closeOperation(operationId: string) {
    return request('/operations/session/close', {
      method: 'POST',
      body: JSON.stringify({ operation_id: operationId, end_date: new Date().toISOString(), status: 'ended' }),
    });
  },
  getActiveOperation() { return request<any>('/operations/active'); },
  getOperationCoverage(operationId: string) { return request<any>(`/operations/coverage/${encodeURIComponent(operationId)}`); },

  // Export
  getExportUrl(operationId: string, format: 'isoxml' | 'geojson' | 'gpx'): string {
    return `${BASE_URL}/export/${encodeURIComponent(operationId)}?format=${format}`;
  },

  // Patterns
  listPatterns(parcelId: string) { return request<any>(`/patterns?parcel_id=${encodeURIComponent(parcelId)}`); },
  getPattern(patternId: string) { return request<any>(`/patterns/${encodeURIComponent(patternId)}`); },
  savePattern(body: any) { return request('/patterns', { method: 'POST', body: JSON.stringify(body) }); },
  deletePattern(patternId: string) { return request(`/patterns/${encodeURIComponent(patternId)}`, { method: 'DELETE' }); },

  // Pathfinding
  startPathCalculation(body: any) { return request<any>('/path/calculate', { method: 'POST', body: JSON.stringify(body) }); },
  getPathResult(jobId: string) { return request<any>(`/path/${encodeURIComponent(jobId)}`); },

  // External zones
  ingestExternalZones(format: 'geojson' | 'csv', content: string) {
    return request<any>('/zones/external/ingest', {
      method: 'POST', body: JSON.stringify({ format, content }),
    });
  },
};
```

- [ ] **Step 2: Commit**

```bash
git add src/services/api.ts
git commit -m "feat: rewrite API client with all new endpoints (generate, patterns, pathfinding, VRA)"
```

---

### Task 17: Backend — Tests and Cleanup

**Files:**
- Rewrite: `backend/tests/test_api.py`
- Rewrite: `backend/tests/test_export.py`
- Rewrite: `backend/tests/test_geometry_elevation.py`
- Create: `backend/tests/test_patterns.py`
- Create: `backend/tests/test_pathfinding.py`
- Delete refs: `backend/app/services/pmtiles_generator.py` (remove import in routing.py)

- [ ] **Step 1: Rewrite API tests for unified endpoint**

```python
# backend/tests/test_api.py
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

SQUARE_PARCEL = {
    "type": "Polygon",
    "coordinates": [[[-1.643, 42.816], [-1.641, 42.816], [-1.641, 42.818], [-1.643, 42.818], [-1.643, 42.816]]],
}


class TestGenerate:
    def test_generate_ab_line(self):
        """Unified generate endpoint with ab-line pattern."""
        resp = client.post("/api/routing/generate", json={
            "parcel_geometry": SQUARE_PARCEL,
            "pattern": "ab-line",
            "pattern_config": {"heading_deg": 0, "width_m": 24},
            "persist": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["alternatives"]) == 3
        assert data["data"]["properties"]["swath_count"] > 0

    def test_generate_spiral(self):
        resp = client.post("/api/routing/generate", json={
            "parcel_geometry": SQUARE_PARCEL,
            "pattern": "spiral",
            "pattern_config": {"width_m": 24, "direction": "outside-in"},
            "persist": False,
        })
        assert resp.status_code == 200
        assert "spiral" in resp.json()["data"]["properties"]["pattern"]

    def test_generate_rejects_invalid_pattern(self):
        resp = client.post("/api/routing/generate", json={
            "parcel_geometry": SQUARE_PARCEL,
            "pattern": "invalid",
            "pattern_config": {},
            "persist": False,
        })
        assert resp.status_code == 422  # validation error

    def test_ingest_external_zones_geojson(self):
        resp = client.post("/api/routing/zones/external/ingest", json={
            "format": "geojson",
            "content": '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,1],[0,0]]]},"properties":{"zone_id":"z1","zone_class":"high","prescription_rate":1.2}}]}',
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["count"] == 1
```

- [ ] **Step 2: Write pattern CRUD tests**

```python
# backend/tests/test_patterns.py

# Test pattern save/list/get/delete lifecycle
```

- [ ] **Step 3: Write pathfinding tests**

```python
# backend/tests/test_pathfinding.py

# Test A* algorithm on small synthetic DEM
```

- [ ] **Step 4: Run all tests**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: all tests PASS (may need to skip tests that need DB/Orion-LD).

- [ ] **Step 5: Remove pmtiles_generator references**

Remove import from `routing.py`, keep the file but mark as deprecated.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/ backend/app/services/pmtiles_generator.py backend/app/api/routing.py
git commit -m "chore: rewrite tests for unified endpoint, add pattern/pathfinding tests, deprecate pmtiles"
```

---

### Task 18: i18n — Add All New Keys

**Files:**
- Modify: `src/locales/es.json`
- Modify: `src/locales/en.json`
- Modify: `src/locales/ca.json`
- Modify: `src/locales/eu.json`
- Modify: `src/locales/fr.json`
- Modify: `src/locales/pt.json`

- [ ] **Step 1: Add new keys to Spanish locale**

```json
{
  "tabs": {
    "routing": "Guiado",
    "pathfinding": "Ruta A-B"
  },
  "stats": {
    "title": "Resumen de ruta",
    "swaths": "Franjas",
    "distance": "Distancia total",
    "area": "Área cubierta",
    "pattern": "Patrón",
    "vra": "VRA"
  },
  "patterns": {
    "saveTitle": "Guardar plantilla",
    "save": "Guardar como plantilla",
    "saved": "Plantilla guardada",
    "namePlaceholder": "Ej: Siembra maíz 2026",
    "loadTitle": "Reutilizar plantilla",
    "selectPattern": "Seleccionar plantilla...",
    "none": "Ninguna — configurar manualmente"
  },
  "pathfinding": {
    "title": "Ruta logística A-B",
    "pointA": "Punto A",
    "pointB": "Punto B",
    "machineWidth": "Ancho mínimo de paso (m)",
    "maxSlope": "Pendiente máxima (°)",
    "minTurnRadius": "Radio de giro mínimo (m)",
    "calculate": "Calcular rutas",
    "calculating": "Calculando...",
    "results": "Alternativas de ruta",
    "distance": "Distancia",
    "climb": "Desnivel acumulado",
    "maxSlopeLabel": "Pendiente máxima",
    "elevationProfile": "Perfil de elevación"
  },
  "panels": {
    "emptyState": "Genera una ruta para ver resultados",
    "emptyStateHint": "Configura parcela, equipo y patrón en el panel izquierdo"
  },
  "patternLabels": {
    "ab-line": "Líneas A-B",
    "ab-skip": "Siembra (skip-row)",
    "spiral": "Cosecha (espiral)",
    "headland-only": "Solo cabeceras"
  }
}
```

- [ ] **Step 2: Add English keys (same structure)**

- [ ] **Step 3: Add remaining languages (ca, eu, fr, pt) with Spanish as base**

- [ ] **Step 4: Commit**

```bash
git add src/locales/
git commit -m "feat: add i18n keys for stats, patterns, pathfinding, and panel states"
```

---

### Task 19: K8s and Config Updates

**Files:**
- Modify: `k8s/backend-deployment.yaml`
- Modify: `backend/app/config.py`

- [ ] **Step 1: Update config.py with pathfinding settings**

```python
# Add to backend/app/config.py Settings class:

    # Pathfinding
    pathfinding_job_ttl_seconds: int = 3600  # 1 hour
    pathfinding_max_area_km2: float = 10.0
```

- [ ] **Step 2: Update K8s deployment**

```yaml
# In k8s/backend-deployment.yaml, ensure these env vars:
- name: APP_VERSION
  value: "3.0.0"
- name: PATHFINDING_JOB_TTL_SECONDS
  value: "3600"
- name: PATHFINDING_MAX_AREA_KM2
  value: "10.0"
```

- [ ] **Step 3: Commit**

```bash
git add k8s/backend-deployment.yaml backend/app/config.py
git commit -m "chore: bump version to 3.0.0, add pathfinding config"
```

---

### Task 20: Remove Old Code

**Files:**
- Delete: `src/components/RoutingDesigner.tsx` (replaced by wizard)
- Delete: `src/components/pages/ZoningTab.tsx` (merged into StepVRA)
- Delete: `src/components/slots/ExampleSlot.tsx` (replaced by GisRoutingMapLayer + context panel)
- Rewrite: `src/components/slots/` → new simplified context-panel slot
- Modify: `manifest.json` (bump version to 3.0.0, update features list)

- [ ] **Step 1: Delete old files**

```bash
rm src/components/RoutingDesigner.tsx
rm src/components/pages/ZoningTab.tsx
rm src/components/slots/ExampleSlot.tsx
```

- [ ] **Step 2: Create new minimal context-panel slot**

```typescript
// src/components/slots/ContextPanelSlot.tsx
import React from 'react';
import { SlotShell } from '@nekazari/viewer-kit';
import { useViewer, useTranslation } from '@nekazari/sdk';
import { ExternalLink } from 'lucide-react';
import manifest from '../../../manifest.json';

const NS = 'gis-routing';

export const ContextPanelSlot: React.FC = () => {
  const { t } = useTranslation(NS);
  const { selectedEntityId, selectedEntityType } = useViewer();

  if (!selectedEntityId || selectedEntityType !== 'AgriParcel') {
    return (
      <SlotShell moduleId="nkz-module-gis-routing" accent={manifest.accent}>
        <div className="p-4 text-nkz-sm text-nkz-text-secondary text-center">
          {t('zoning.selectParcel')}
        </div>
      </SlotShell>
    );
  }

  return (
    <SlotShell moduleId="nkz-module-gis-routing" accent={manifest.accent}>
      <div className="p-4 space-y-3 text-nkz-sm">
        <p className="font-semibold text-nkz-text-primary">{t('title')}</p>
        <p className="text-nkz-xs text-nkz-text-secondary truncate">{selectedEntityId}</p>
        <a
          href={`/gis-routing?parcel=${encodeURIComponent(selectedEntityId)}`}
          target="_blank"
          className="flex items-center justify-center gap-1 py-2 rounded-nkz-md text-nkz-xs font-semibold text-nkz-text-on-accent hover:opacity-90"
          style={{ backgroundColor: manifest.accent.base }}
        >
          <ExternalLink className="w-3 h-3" />
          {t('actions.openFullApp')}
        </a>
      </div>
    </SlotShell>
  );
};
```

- [ ] **Step 3: Update manifest.json**

```json
{
  "version": "3.0.0",
  "metadata": {
    "features": [
      "Multi-strategy routing: AB-line, AB-skip (seeding), spiral (harvesting), headland",
      "VRA prescription maps with vegetation-health auto-fetch and rate smoothing",
      "A-B least-cost pathfinding with DEM elevation routing (3 alternatives)",
      "Field pattern persistence for Controlled Traffic Farming (CTF)",
      "3-column wizard UI with live Cesium 3D preview",
      "ISOXML, GeoJSON, and GPX export",
      "Mobile handoff with WatermelonDB sync"
    ]
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat: remove old components, add context-panel slot, bump to v3.0.0"
```

---

### Task 21: ArgoCD & Deploy

**Files:**
- Modify: `nkz/gitops/modules/gis-routing.yaml` (if version ref needed)
- No changes needed to ArgoCD — it tracks HEAD.

- [ ] **Step 1: Build and push backend**

```bash
cd backend
docker build -t ghcr.io/nkz-os/nkz-module-gis-routing/nkz-module-gis-routing-backend:latest .
docker push ghcr.io/nkz-os/nkz-module-gis-routing/nkz-module-gis-routing-backend:latest
```

- [ ] **Step 2: Build and upload IIFE bundle**

```bash
npm run build:module
mc cp dist/nkz-module.js minio/nekazari-frontend/modules/nkz-module-gis-routing/nkz-module.js
```

- [ ] **Step 3: Deploy backend**

```bash
kubectl apply -f k8s/backend-deployment.yaml -n nekazari --dry-run=client
# If dry-run passes:
kubectl apply -f k8s/backend-deployment.yaml -n nekazari
kubectl rollout status deployment/nkz-module-gis-routing-backend -n nekazari
```

- [ ] **Step 4: Run DB migration (field_patterns table)**

```bash
kubectl exec -n nekazari deployment/nkz-module-gis-routing-backend -- python -c "
from app.services.timescale_client import TimescaleDBClient
from app.config import get_settings
import asyncio
async def migrate():
    s = get_settings()
    ts = TimescaleDBClient(dsn=s.database_url)
    await ts.connect()
    await ts.close()
    print('Migration OK')
asyncio.run(migrate())
"
```

- [ ] **Step 5: Verify**

```bash
curl -s https://nkz.robotika.cloud/api/routing/health | jq
# Expected: {"status":"healthy","service":"gis-routing","version":"3.0.0"}
```

- [ ] **Step 6: Commit deploy notes**

```bash
git add -A
git commit -m "chore: deployment verification and version bump to 3.0.0"
```

---

## Spec Coverage Check

| Requirement | Task(s) |
|---|---|
| Multi-strategy patterns (AB-line, AB-skip, spiral, headland) | 1-5 |
| DEM slope correction | 6 |
| Unified generate endpoint | 7 |
| VRA auto-fetch from vegetation-health | 7, 10 |
| Pattern persistence (CTF) | 8 |
| A-B least-cost pathfinding with DEM | 9 |
| 3-column wizard UI | 11, 12 |
| Live Cesium 3D preview | 13 |
| Map-layer slot for unified viewer | 13 |
| Stats, alternatives, export panels | 14 |
| Pattern save/load UI | 15 |
| Pathfinding tab with elevation profile | 15 |
| i18n (6 languages) | 18 |
| Old code removal | 20 |
| Tests | 3, 4, 5, 6, 17 |
| Deploy | 21 |

---
