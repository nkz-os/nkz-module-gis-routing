import math
import pytest
from app.services.coverage.contour import best_contour_heading_deg


def test_contour_heading_runs_across_the_slope():
    # Elevation rises towards the east (increasing longitude). Contour lines run
    # N-S, so the across-slope working heading should be ~north (0) or ~180.
    def sampler(lon, lat):
        return lon * 1000.0
    centroid = (-2.0, 43.0)
    bbox = (-2.001, 42.999, -1.999, 43.001)
    heading = best_contour_heading_deg(centroid, bbox, sampler, n=8)
    assert min(abs(heading % 180 - 0), abs(heading % 180 - 180)) < 25
