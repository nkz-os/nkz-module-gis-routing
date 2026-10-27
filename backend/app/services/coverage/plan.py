"""Coverage plan types. All geometries are UTM metres; WGS84 only on output."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from shapely.geometry import LineString, MultiLineString, Point, Polygon, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from app.services.routing.base import RouteResult

if TYPE_CHECKING:
    from app.services.coverage.validation import ValidationReport


def _round_coords(c):
    if isinstance(c, (list, tuple)):
        if c and isinstance(c[0], (int, float)):
            return [round(float(v), 7) for v in c]
        return [_round_coords(i) for i in c]
    return c


def geojson_wgs84(geom: BaseGeometry | None, to_wgs84) -> dict | None:
    """Project a UTM geometry and return GeoJSON with 7-decimal list coordinates."""
    if geom is None:
        return None
    return _geojson(transform(to_wgs84, geom))


def _geojson(geom: BaseGeometry) -> dict:
    gj = mapping(geom)
    if gj["type"] == "GeometryCollection":
        return {"type": "GeometryCollection",
                "geometries": [_geojson(g) for g in geom.geoms]}
    return {"type": gj["type"], "coordinates": _round_coords(gj["coordinates"])}


@dataclass(frozen=True)
class Swath:
    index: int
    kind: Literal["work", "headland"]
    geometry: LineString


@dataclass(frozen=True)
class Turn:
    index: int
    from_swath: int
    to_swath: int
    geometry: LineString


def _parts(route: LineString | MultiLineString) -> list[LineString]:
    return list(route.geoms) if isinstance(route, MultiLineString) else [route]


@dataclass
class CoveragePlan:
    pattern: str
    curve_type: str
    headland_passes: int
    swaths: list[Swath]
    turns: list[Turn]
    route: LineString | MultiLineString
    working_area: Polygon
    unreached: list[Polygon]
    parcel_area_m2: float
    access_point: Point | None
    access_path: LineString | None
    exit_point: Point
    exclusion_zones: list[Polygon]
    fallbacks: list[str] = field(default_factory=list)
    validation: "ValidationReport | None" = None
    # Straight leg from the gate on the fence to the eroded area; access_path
    # continues from its end, inside the eroded area, to the route start.
    access_leg: LineString | None = None
    # Route end -> leg end, inside the eroded area (not a Turn, not in route).
    return_path: LineString | None = None

    def _worked(self) -> float:
        return sum(s.geometry.length for s in self.swaths)

    def _non_working(self) -> float:
        return sum(t.geometry.length for t in self.turns)

    def full_access_path(self) -> LineString | None:
        """Gate -> route start: the fence leg followed by the inner path."""
        if self.access_path is None:
            return None
        if self.access_leg is None:
            return self.access_path
        return LineString(list(self.access_leg.coords) + list(self.access_path.coords)[1:])

    def full_return_path(self) -> LineString | None:
        """Route end -> gate: the inner return path followed by the leg reversed."""
        if self.return_path is None:
            return None
        if self.access_leg is None:
            return self.return_path
        return LineString(list(self.return_path.coords) + [self.access_leg.coords[0]])

    def metrics(self, cov_width: float) -> dict:
        worked = self._worked()
        non_working = self._non_working()
        total = worked + non_working
        working_ha = self.working_area.area / 1e4
        covered_ha = min(worked * cov_width / 1e4, working_ha)
        access = self.full_access_path()
        back = self.full_return_path()
        leg = self.access_leg.length if self.access_leg is not None and self.access_path is not None else 0.0
        return {
            "worked_distance_m": round(worked, 1),
            "non_working_distance_m": round(non_working, 1),
            "access_distance_m": round(access.length if access is not None else 0.0, 1),
            "access_leg_distance_m": round(leg, 1),
            "return_distance_m": round(back.length if back is not None else 0.0, 1),
            "field_efficiency": round(worked / total, 4) if total > 0 else 0.0,
            "covered_area_ha": round(covered_ha, 3),
            "parcel_area_ha": round(self.parcel_area_m2 / 1e4, 3),
            "working_area_ha": round(working_ha, 3),
        }

    def as_api_dict(self, to_wgs84, cov_width: float) -> dict:
        return {
            "pattern": self.pattern,
            "curve_type": self.curve_type,
            "swath_count": len(self.swaths),
            "headland_passes": self.headland_passes,
            "route": geojson_wgs84(self.route, to_wgs84),
            "swaths": [
                {"index": s.index, "kind": s.kind, "geometry": geojson_wgs84(s.geometry, to_wgs84)}
                for s in self.swaths
            ],
            "access_path": geojson_wgs84(self.full_access_path(), to_wgs84),
            "return_path": geojson_wgs84(self.full_return_path(), to_wgs84),
            "access_point": geojson_wgs84(self.access_point, to_wgs84),
            "exit_point": geojson_wgs84(self.exit_point, to_wgs84),
            "working_area": geojson_wgs84(self.working_area, to_wgs84),
            "unreached_parts": [
                {"geometry": geojson_wgs84(p, to_wgs84), "area_ha": round(p.area / 1e4, 3)}
                for p in self.unreached
            ],
            "metrics": self.metrics(cov_width),
            "validation": self.validation.to_dict(to_wgs84) if self.validation else None,
            "exclusion_zones": {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {}, "geometry": geojson_wgs84(z, to_wgs84)}
                    for z in self.exclusion_zones
                ],
            },
            "prescription": None,
        }

    def to_route_result(self, to_wgs84, cov_width: float) -> RouteResult:
        parts = [transform(to_wgs84, p) for p in _parts(self.route)]
        return RouteResult(
            geometry=MultiLineString(parts),
            pattern=self.pattern,
            swath_count=len(self.swaths),
            headland_count=self.headland_passes,
            total_distance_m=round(self._worked() + self._non_working(), 1),
            covered_area_ha=self.metrics(cov_width)["covered_area_ha"],
            pass_order=[list(range(len(self.swaths)))],
            metadata={"curve_type": self.curve_type},
            metrics=self.metrics(cov_width),
        )
