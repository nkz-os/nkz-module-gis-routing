"""Synthetic parcels in UTM metres (origin 0,0) for geometry tests."""
from pyproj import Transformer
from shapely.geometry import Point, Polygon
from shapely.ops import transform

RECT = Polygon([(0, 0), (200, 0), (200, 100), (0, 100)])
L_SHAPE = Polygon([(0, 0), (200, 0), (200, 50), (100, 50), (100, 100), (0, 100)])
WITH_HOLE = Polygon(RECT.exterior.coords, [[(90, 40), (110, 40), (110, 60), (90, 60)]])
TWO_LOBES = Polygon([(0, 0), (80, 0), (80, 40), (120, 40), (120, 0), (200, 0), (200, 100),
                     (120, 100), (120, 60), (80, 60), (80, 100), (0, 100)])
ZONE_CENTER = Polygon([(90, 40), (110, 40), (110, 60), (90, 60)])
ZONE_SPLIT = Polygon([(95, 0), (105, 0), (105, 100), (95, 100)])
GATE = Point(0, 50)
GATE_INSIDE = Point(3, 50)

_ORIGIN = (600000.0, 4760000.0)
_TO_WGS84 = Transformer.from_crs("EPSG:32630", "EPSG:4326", always_xy=True).transform


def _shift_project(x, y):
    return _TO_WGS84(x + _ORIGIN[0], y + _ORIGIN[1])


def wgs84(poly_utm: Polygon) -> Polygon:
    """Translate a local-metre polygon to a real UTM 30N spot and project to WGS84."""
    return transform(_shift_project, poly_utm)


def wgs84_point(p: Point) -> tuple[float, float]:
    return _shift_project(p.x, p.y)
