import itertools
import pytest
pytest.importorskip("fields2cover")
from shapely.geometry import Point, Polygon
from shapely.affinity import rotate, scale
from app.services.coverage.ladder import plan_with_fallbacks, LadderInput
from app.services.coverage.f2c_engine import CoverageConfig
from app.services.coverage.robot_model import RobotParams
from app.services.exclusion import ExclusionError
from tests.fixtures_parcels import RECT, L_SHAPE, WITH_HOLE, TWO_LOBES, ZONE_CENTER, ZONE_SPLIT, GATE, wgs84

ROBOT = RobotParams(width=2.0, cov_width=4.0, min_turning_radius=6.0, curve_type="dubins")
PARCELS_CI = {"rect": RECT, "l": L_SHAPE, "hole": WITH_HOLE, "lobes": TWO_LOBES,
              "rot30": rotate(RECT, 30, origin=(100, 50))}
ZONES_CI = {"none": [], "center": [ZONE_CENTER]}
PATTERNS_CI = ("boustrophedon", "snake")
PARCELS_FULL = dict(PARCELS_CI, wide=scale(RECT, 1.5, 0.6, origin=(100, 50)), **{f"rot{a}": rotate(RECT, a, origin=(100, 50)) for a in (10, 45, 60, 75, 90, 120)},
                    **{f"sc{i}": scale(L_SHAPE, 1 + i / 10, 1 - i / 20, origin=(100, 50)) for i in range(1, 9)})
ZONES_FULL = dict(ZONES_CI, split=[ZONE_SPLIT])
PATTERNS_FULL = ("boustrophedon", "snake", "spiral", "auto")


def _assert_guarantees(parcel, zones, pattern):
    inp = LadderInput(parcel_utm=parcel, zones_utm=zones, robot=ROBOT,
                      cfg=CoverageConfig(pattern=pattern, headland_passes=1), access_utm=None, wgs84_poly=wgs84(parcel))
    try:
        plan = plan_with_fallbacks(inp)
    except ExclusionError as e:
        assert e.code == "NO_DRIVABLE_AREA" and e.params
        return
    hard = [c for c in plan.validation.checks if c.id in ("inside_parcel", "outside_zones")]
    assert all(c.ok for c in hard), [(c.id, c.value) for c in hard]
    for z in zones:
        assert plan.route.intersection(z.buffer(ROBOT.cov_width / 2 - 0.1)).length == 0.0
    assert parcel.buffer(-ROBOT.cov_width / 2 + 0.5).covers(plan.route)


@pytest.mark.parametrize("pname,zname,pattern", list(itertools.product(PARCELS_CI, ZONES_CI, PATTERNS_CI)))
def test_matrix_ci(pname, zname, pattern):
    _assert_guarantees(PARCELS_CI[pname], ZONES_CI[zname], pattern)


@pytest.mark.slow
@pytest.mark.parametrize("pname,zname,pattern", list(itertools.product(PARCELS_FULL, ZONES_FULL, PATTERNS_FULL)))
def test_matrix_full(pname, zname, pattern):
    _assert_guarantees(PARCELS_FULL[pname], ZONES_FULL[zname], pattern)
