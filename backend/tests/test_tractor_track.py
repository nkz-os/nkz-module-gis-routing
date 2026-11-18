"""Where the tractor drives when the implement works off to one side."""
import pytest
from shapely.geometry import LineString, Polygon

from app.services.coverage.plan import Swath
from app.services.coverage.tractor_track import tractor_track

FIELD = Polygon([(0, 0), (100, 0), (100, 50), (0, 50)])


def test_tractor_runs_on_the_other_side_of_a_right_hand_implement_whatever_the_direction():
    east = Swath(0, "work", LineString([(10, 25), (90, 25)]))
    west = Swath(1, "work", LineString([(90, 29), (10, 29)]))
    lines, warnings = tractor_track([east, west], e=1.5, half_track=0.9, parcel=FIELD, zones=[])
    assert lines[0].coords[0] == pytest.approx((10, 26.5))   # heading east, left = north
    assert lines[1].coords[0] == pytest.approx((90, 27.5))   # heading west, left = south
    assert warnings == []


def test_tractor_leaving_the_parcel_is_reported_with_where():
    edge = Swath(0, "headland", LineString([(10, 49.0), (90, 49.0)]))  # implement right, tractor left: north
    lines, warnings = tractor_track([edge], e=-1.5, half_track=0.9, parcel=FIELD, zones=[])
    assert lines[0].coords[0] == pytest.approx((10, 47.5))  # e < 0: implement left, tractor right (south) -> inside
    assert warnings == []
    lines, warnings = tractor_track([edge], e=1.5, half_track=0.9, parcel=FIELD, zones=[])
    assert [w.code for w in warnings] == ["TRACTOR_TRACK_OUTSIDE"]
    assert warnings[0].params == {"swaths": [0]} and warnings[0].geometry is not None


def test_tractor_crossing_a_no_go_zone_is_reported():
    zone = Polygon([(40, 26), (60, 26), (60, 30), (40, 30)])
    swath = Swath(0, "work", LineString([(10, 25), (90, 25)]))
    _, warnings = tractor_track([swath], e=1.5, half_track=0.9, parcel=FIELD, zones=[zone])
    assert [w.code for w in warnings] == ["TRACTOR_TRACK_OUTSIDE"]


def test_centred_implement_needs_no_tractor_track():
    lines, warnings = tractor_track([Swath(0, "work", LineString([(10, 25), (90, 25)]))],
                                    e=0.0, half_track=0.9, parcel=FIELD, zones=[])
    assert lines == [] and warnings == []
