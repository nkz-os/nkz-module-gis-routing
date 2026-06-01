import pytest
from shapely.geometry import Polygon, MultiLineString
from app.services.routing.base import project_polygon_to_utm
from app.services.coverage.geometry_adapter import (
    shapely_to_f2c_cells, f2c_path_to_wgs84,
)


def _square_utm():
    # A WGS84 square near 43N, projected to UTM.
    wgs = Polygon([(-2.0, 43.0), (-1.999, 43.0), (-1.999, 43.001), (-2.0, 43.001)])
    utm_poly, _crs, _to_utm, to_wgs84 = project_polygon_to_utm(wgs)
    return utm_poly, to_wgs84


def test_shapely_polygon_becomes_f2c_cells_with_matching_area():
    utm_poly, _ = _square_utm()
    cells = shapely_to_f2c_cells(utm_poly)
    assert cells.area() == pytest.approx(utm_poly.area, rel=1e-6)


def test_polygon_with_hole_preserves_inner_ring():
    from shapely.geometry import Polygon as P
    outer = [(0, 0), (100, 0), (100, 100), (0, 100)]
    hole = [(40, 40), (60, 40), (60, 60), (40, 60)]
    poly = P(outer, [hole])
    cells = shapely_to_f2c_cells(poly)
    assert cells.area() == pytest.approx(poly.area, rel=1e-6)  # 10000 - 400


def test_path_export_roundtrips_to_wgs84_multilinestring():
    utm_poly, to_wgs84 = _square_utm()
    import fields2cover as f2c
    sw = f2c.LineString()
    for x, y in list(utm_poly.exterior.coords):
        sw.addPoint(f2c.Point(x, y))
    geom = f2c_path_to_wgs84([sw], to_wgs84)
    assert isinstance(geom, MultiLineString)
    xs = [c[0] for line in geom.geoms for c in line.coords]
    assert min(xs) == pytest.approx(-2.0, abs=1e-4)
