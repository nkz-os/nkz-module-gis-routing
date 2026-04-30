import pytest
from shapely.geometry import MultiLineString, LineString, Polygon, mapping
from app.services.vra_intersector import intersect_swaths_with_zones


def make_square_swaths():
    return MultiLineString(
        [
            LineString([(-1.0, 42.0), (-0.9, 42.0)]),
            LineString([(-1.0, 42.005), (-0.9, 42.005)]),
        ]
    )


def make_two_zones():
    return [
        {
            "type": "Feature",
            "geometry": mapping(
                Polygon(
                    [
                        (-1.0, 42.0),
                        (-0.95, 42.0),
                        (-0.95, 42.01),
                        (-1.0, 42.01),
                        (-1.0, 42.0),
                    ]
                )
            ),
            "properties": {
                "zone_id": 1,
                "zone_class": "high",
                "prescription_rate": 1.5,
            },
        },
        {
            "type": "Feature",
            "geometry": mapping(
                Polygon(
                    [
                        (-0.95, 42.0),
                        (-0.9, 42.0),
                        (-0.9, 42.01),
                        (-0.95, 42.01),
                        (-0.95, 42.0),
                    ]
                )
            ),
            "properties": {
                "zone_id": 2,
                "zone_class": "low",
                "prescription_rate": 0.5,
            },
        },
    ]


def test_intersect_produces_segments():
    result = intersect_swaths_with_zones(
        make_square_swaths(), make_two_zones(), 100.0, 10.0
    )
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) > 0
    rates = {f["properties"]["rate"] for f in result["features"]}
    assert rates.issubset({150.0, 50.0})


def test_empty_swaths_returns_empty():
    assert (
        intersect_swaths_with_zones(
            MultiLineString([]), make_two_zones(), 100.0, 10.0
        )["features"]
        == []
    )


def test_no_zones_returns_empty():
    assert (
        intersect_swaths_with_zones(
            make_square_swaths(), [], 100.0, 10.0
        )["features"]
        == []
    )
