import pytest
from shapely.geometry import (GeometryCollection, LineString, MultiLineString, Point, Polygon)

from app.services.coverage.plan import CoveragePlan, Swath, Turn, geojson_wgs84
from app.services.coverage.validation import (
    check_inside_parcel, check_outside_zones, split_working_area, validate_plan)
from app.services.exclusion import ExclusionError
from tests.fixtures_parcels import RECT, ZONE_CENTER, GATE

IDENT = lambda x, y: (x, y)  # noqa: E731


def _plan(route=None):
    s0 = LineString([(10, 10), (190, 10)])
    s1 = LineString([(190, 30), (10, 30)])
    route = route or LineString([(10, 10), (190, 10), (190, 30), (10, 30)])
    return CoveragePlan(
        pattern="boustrophedon", curve_type="dubins", headland_passes=1,
        swaths=[Swath(0, "work", s0), Swath(1, "work", s1)],
        turns=[Turn(0, 0, 1, LineString([(190, 10), (190, 30)]))],
        route=route, working_area=RECT, unreached=[Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])],
        parcel_area_m2=20000.0, access_point=GATE, access_path=LineString([(10, 50), (10, 10)]),
        exit_point=Point(10, 30), exclusion_zones=[ZONE_CENTER], access_leg=LineString([(0, 50), (10, 50)]))


def test_geojson_rounding_lists_and_none():
    g = geojson_wgs84(LineString([(0.123456789, 1.0), (2.0, 3.0)]), IDENT)
    assert g == {"type": "LineString", "coordinates": [[0.1234568, 1.0], [2.0, 3.0]]}
    assert isinstance(g["coordinates"][0], list)
    assert geojson_wgs84(None, IDENT) is None


def test_geojson_geometry_collection():
    g = geojson_wgs84(GeometryCollection([LineString([(0, 0), (1, 1)]), Point(2, 2)]), IDENT)
    assert g["type"] == "GeometryCollection"
    assert [x["type"] for x in g["geometries"]] == ["LineString", "Point"]


def test_metrics():
    m = _plan().metrics(20.0)
    assert m["worked_distance_m"] == 360.0
    assert m["non_working_distance_m"] == 20.0
    assert m["access_distance_m"] == 50.0 and m["access_leg_distance_m"] == 10.0
    assert m["return_distance_m"] == 0.0
    assert m["field_efficiency"] == round(360 / 380, 4)
    assert m["covered_area_ha"] == 0.72
    assert m["parcel_area_ha"] == 2.0 and m["working_area_ha"] == 2.0


def test_as_api_dict():
    plan = _plan()
    d = plan.as_api_dict(IDENT, 20.0)
    assert d["prescription"] is None
    assert d["exclusion_zones"]["type"] == "FeatureCollection"
    assert d["exclusion_zones"]["features"][0]["geometry"]["type"] == "Polygon"
    assert d["exclusion_zones"]["features"][0]["properties"] == {}
    assert d["validation"] is None
    assert d["swath_count"] == 2 and d["swaths"][0]["kind"] == "work"
    assert d["route"]["coordinates"][0] == [10.0, 10.0]
    assert d["access_point"] == {"type": "Point", "coordinates": [0.0, 50.0]}
    assert d["unreached_parts"][0]["area_ha"] == 1.0
    plan.validation = validate_plan(plan, RECT, [], 20.0)
    assert plan.as_api_dict(IDENT, 20.0)["validation"]["ok"] is True


def test_to_route_result():
    n = 2
    r = _plan().to_route_result(IDENT, 20.0)
    assert r.geometry.geom_type == "MultiLineString" and len(r.geometry.geoms) == 1
    assert r.pass_order == [list(range(n))] and r.swath_count == 2 and r.headland_count == 1
    assert r.total_distance_m == 380.0 and r.metadata == {"curve_type": "dubins"}
    multi = MultiLineString([LineString([(0, 0), (1, 0)]), LineString([(5, 5), (6, 5)])])
    assert len(_plan(multi).to_route_result(IDENT, 20.0).geometry.geoms) == 2


def test_collection_check_geometry_serialises():
    route = LineString([(0, 30), (100, 30)])
    zones = [Polygon([(10, 20), (20, 20), (20, 40), (10, 40)]),
             Polygon([(50, 30), (55, 40), (45, 40)])]          # touches the route at one point
    c = check_outside_zones(route, zones, 0.2)
    assert not c.ok and c.geometry.geom_type == "GeometryCollection"
    from app.services.coverage.validation import ValidationReport
    d = ValidationReport(False, [c], [], []).to_dict(IDENT)
    assert d["checks"][0]["geometry"]["type"] == "GeometryCollection"


def test_split_filters_non_polygons():
    gc = GeometryCollection([LineString([(0, 0), (1, 1)]), Polygon([(0, 0), (2, 0), (2, 2)])])
    piece, rest = split_working_area(gc, None)
    assert piece.area == 2.0 and rest == []
    with pytest.raises(ExclusionError) as e:
        split_working_area(GeometryCollection([Point(1, 1)]), None)
    assert e.value.code == "NO_DRIVABLE_AREA"
    with pytest.raises(ExclusionError):
        split_working_area(Polygon(), None)


def test_inside_check_narrow_parcel_is_finite():
    narrow = Polygon([(0, 0), (200, 0), (200, 10), (0, 10)])
    route = LineString([(10, 5), (190, 5)])
    c = check_inside_parcel(route, narrow, 20.0)
    assert not c.ok and c.value == 180.0 and c.geometry is route


def test_access_leg_and_return_path_in_metrics_and_api():
    from dataclasses import replace
    leg = LineString([(0, 50), (5, 50)])
    path = LineString([(5, 50), (10, 10)])
    back = LineString([(10, 30), (5, 50)])
    assert _plan().access_leg is not None
    plan = replace(_plan(), access_leg=leg, access_path=path, return_path=back, exit_point=GATE)
    m = plan.metrics(20.0)
    assert m["access_leg_distance_m"] == 5.0
    assert m["access_distance_m"] == pytest.approx(5.0 + path.length, abs=0.05)
    assert m["return_distance_m"] == pytest.approx(back.length + 5.0, abs=0.05)
    d = plan.as_api_dict(IDENT, 20.0)
    assert d["access_path"]["coordinates"] == [[0.0, 50.0], [5.0, 50.0], [10.0, 10.0]]
    assert d["return_path"]["coordinates"] == [[10.0, 30.0], [5.0, 50.0], [0.0, 50.0]]
    assert d["exit_point"]["coordinates"] == [0.0, 50.0]


def test_api_without_transit_has_null_paths_and_zero_distances():
    from dataclasses import replace
    plan = replace(_plan(), access_path=None, access_leg=None)
    d = plan.as_api_dict(IDENT, 20.0)
    assert d["access_path"] is None and d["return_path"] is None
    assert d["metrics"]["access_distance_m"] == 0.0 and d["metrics"]["access_leg_distance_m"] == 0.0
    assert d["metrics"]["return_distance_m"] == 0.0
