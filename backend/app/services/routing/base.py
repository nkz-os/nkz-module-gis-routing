"""Abstract base for routing strategies, plus config and result types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import LineString, MultiLineString, Polygon


def get_utm_crs(lon: float, lat: float) -> CRS:
    """Return the local UTM CRS for a given WGS84 coordinate."""
    zone = int((lon + 180) / 6) + 1
    is_north = lat >= 0
    epsg_code = 32600 + zone if is_north else 32700 + zone
    return CRS.from_epsg(epsg_code)


def project_polygon_to_utm(
    wgs84_poly: Polygon,
) -> tuple[Polygon, CRS, Transformer, Transformer]:
    """Project a WGS84 polygon to its local UTM zone.

    Returns (utm_poly, utm_crs, to_utm_transform, to_wgs84_transform).
    The transform callables accept (x, y) and return projected coordinates.
    """
    if not wgs84_poly.is_valid:
        wgs84_poly = wgs84_poly.buffer(0)

    centroid = wgs84_poly.centroid
    utm_crs = get_utm_crs(centroid.x, centroid.y)
    wgs84_crs = CRS.from_epsg(4326)
    to_utm = Transformer.from_crs(wgs84_crs, utm_crs, always_xy=True).transform
    to_wgs84 = Transformer.from_crs(utm_crs, wgs84_crs, always_xy=True).transform

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


def project_linestrings_to_wgs84(lines: list, to_wgs84) -> MultiLineString:
    """Project a list of UTM LineStrings back to WGS84."""
    wgs_lines = []
    for line in lines:
        coords = np.array(line.coords)
        wgs_x, wgs_y = to_wgs84(coords[:, 0], coords[:, 1])
        wgs_lines.append(LineString(np.column_stack((wgs_x, wgs_y))))
    return MultiLineString(wgs_lines)


@dataclass
class PatternConfig:
    """Configuration parameters for a routing pattern.

    Attributes:
        heading_deg: Azimuth of the primary working direction (0-360, 0=North).
        width_m: Nominal implement width in meters.
        overlap_pct: Overlap between adjacent passes (0-30%).
        headland_passes: Number of headland passes (0-3).
        skip_rows: Row skipping pattern (0=off, 1=alternate, 2=skip-2).
        direction: Expansion direction for the pattern.
    """

    heading_deg: float = 0.0
    width_m: float = 24.0
    overlap_pct: float = 0.0
    headland_passes: int = 0
    skip_rows: int = 0
    direction: Literal["inside-out", "outside-in"] = "outside-in"

    def __post_init__(self) -> None:
        if self.overlap_pct < 0 or self.overlap_pct > 100:
            raise ValueError(
                f"overlap_pct must be 0-100, got {self.overlap_pct}"
            )
        if self.width_m <= 0:
            raise ValueError(f"width_m must be > 0, got {self.width_m}")
        if self.headland_passes < 0 or self.headland_passes > 3:
            raise ValueError(
                f"headland_passes must be 0-3, got {self.headland_passes}"
            )
        if self.skip_rows < 0 or self.skip_rows > 2:
            raise ValueError(
                f"skip_rows must be 0-2, got {self.skip_rows}"
            )
        self.heading_deg = self.heading_deg % 360.0

    @property
    def effective_width_m(self) -> float:
        """Actual working width after accounting for overlap."""
        return self.width_m * (1.0 - self.overlap_pct / 100.0)


@dataclass
class RouteResult:
    """Result of a routing strategy computation.

    Attributes:
        geometry: The generated route as WGS84 MultiLineString.
        pattern: Name of the pattern used.
        swath_count: Number of working swaths.
        headland_count: Number of headland passes.
        total_distance_m: Total route distance in meters.
        covered_area_ha: Total covered area in hectares.
        pass_order: Ordered list of swath indices per pass group.
        turn_points: List of turn waypoints between passes.
        metadata: Additional strategy-specific data.
    """

    geometry: MultiLineString
    pattern: str
    swath_count: int
    headland_count: int
    total_distance_m: float
    covered_area_ha: float
    pass_order: list[list[int]] = field(default_factory=list)
    turn_points: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    path_continuous: MultiLineString | None = None
    maneuver_segments: list[dict] = field(default_factory=list)


class RoutingStrategy(ABC):
    """Abstract base for all routing pattern strategies."""

    @abstractmethod
    def generate(self, polygon: Polygon, config: PatternConfig) -> RouteResult:
        """Generate a route for the given polygon and configuration."""
