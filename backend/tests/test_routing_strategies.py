"""Tests for routing strategy implementations."""

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
