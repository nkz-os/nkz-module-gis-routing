"""Wall-time guard for a large concave parcel (nightly, CI image only)."""
import math
import time

import pytest
pytest.importorskip("fields2cover")
from shapely.geometry import Point, Polygon

from app.services.coverage.f2c_engine import CoverageConfig
from app.services.coverage.ladder import LadderInput, plan_with_fallbacks
from app.config import Settings
from app.services.coverage.robot_model import build_robot
from tests.fixtures_parcels import wgs84

BUDGET_S = Settings.model_fields["LADDER_TIME_BUDGET_S"].default
WALL_BOUND_S = 120.0   # regression guard, not an SLA: CI runners are slower than a workstation


def _wavy_parcel(n: int = 250) -> Polygon:
    """~38 ha wavy ellipse with a notch cut from the south (concave), ~250 vertices."""
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        r = 1 + 0.05 * math.sin(9 * t)
        pts.append((500 + 420 * r * math.cos(t), 400 + 320 * r * math.sin(t)))
    notch = Polygon([(460, 0), (540, 0), (540, 550), (460, 550)])
    return Polygon(pts).difference(notch)


@pytest.mark.slow
def test_large_concave_parcel_plans_within_budget():
    parcel = _wavy_parcel()
    assert 35 < parcel.area / 1e4 < 42 and 200 < len(parcel.exterior.coords) < 300
    zone = Point(700, 400).buffer(25)
    gate = Point(parcel.exterior.coords[60])
    robot = build_robot({"implementWidth": 6, "minTurningRadius": 5}, overlap_pct=0)
    inp = LadderInput(parcel_utm=parcel, zones_utm=[zone], robot=robot,
                      cfg=CoverageConfig(pattern="auto"), access_utm=gate, wgs84_poly=wgs84(parcel))
    t0 = time.monotonic()
    plan = plan_with_fallbacks(inp, time_budget_s=BUDGET_S)
    elapsed = time.monotonic() - t0
    print(f"large parcel: {parcel.area / 1e4:.1f} ha, {elapsed:.1f} s, pattern={plan.pattern}, "
          f"fallbacks={plan.validation.fallbacks_applied}")
    assert elapsed < WALL_BOUND_S
    hard = [c for c in plan.validation.checks if c.id.split(":")[0] in ("inside_parcel", "outside_zones")]
    assert hard and all(c.ok for c in hard), [(c.id, c.value) for c in hard]
