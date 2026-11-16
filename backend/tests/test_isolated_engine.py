import asyncio
import multiprocessing
import time
from dataclasses import replace

import pytest
pytest.importorskip("fields2cover")

from app.services.coverage.contour import best_contour_heading_deg
from app.services.coverage.f2c_engine import CoverageConfig
from app.services.coverage.isolated import (
    EngineCrashed, EngineTimeout, freeze_contour_heading, run_ladder_isolated)
from app.services.coverage.ladder import LadderInput, plan_with_fallbacks
from app.services.coverage.robot_model import RobotParams
from app.services.exclusion import ExclusionError
from tests import isolation_targets as targets
from tests.fixtures_parcels import GATE, RECT, _shift_project, wgs84

ROBOT = RobotParams(width=2.0, cov_width=4.0, min_turning_radius=6.0, curve_type="dubins")


def _inp(**cfg):
    return LadderInput(parcel_utm=RECT, zones_utm=[], robot=ROBOT,
                       cfg=CoverageConfig(pattern="boustrophedon", headland_passes=2, **cfg),
                       access_utm=GATE, wgs84_poly=wgs84(RECT))


def _run(inp=None, target=plan_with_fallbacks, hard_timeout_s=120.0):
    return asyncio.run(run_ladder_isolated(
        inp if inp is not None else _inp(), time_budget_s=60.0,
        hard_timeout_s=hard_timeout_s, target=target))


def test_ok_returns_plan_equal_to_in_process():
    plan = _run()
    direct = plan_with_fallbacks(_inp(), time_budget_s=60.0)
    assert plan.as_api_dict(_shift_project, 4.0) == direct.as_api_dict(_shift_project, 4.0)


def test_large_result_crosses_the_pipe():
    line = _run(target=targets.big_result)
    assert len(line.coords) == 500_000


def test_exclusion_error_keeps_code_and_params():
    with pytest.raises(ExclusionError) as e:
        _run(target=targets.raise_exclusion)
    assert e.value.code == "NO_DRIVABLE_AREA"
    assert e.value.params == {"a": 1}


def test_runtime_error_becomes_runtime_error(caplog):
    with pytest.raises(RuntimeError) as e:
        _run(target=targets.raise_runtime)
    assert not isinstance(e.value, (EngineCrashed, EngineTimeout))
    assert "engine stand-in failed" in caplog.text


def test_segfault_raises_engine_crashed():
    with pytest.raises(EngineCrashed) as e:
        _run(target=targets.segv)
    assert "-11" in str(e.value)


def test_child_exits_without_result():
    with pytest.raises(EngineCrashed):
        _run(target=targets.exit_quietly)


def test_hard_timeout_kills_child():
    t = time.monotonic()
    with pytest.raises(EngineTimeout):
        _run(target=targets.sleep_forever, hard_timeout_s=2.0)
    assert time.monotonic() - t < 10
    assert multiprocessing.active_children() == []


def test_at_most_two_children(tmp_path, monkeypatch):
    log = tmp_path / "overlap.log"
    monkeypatch.setenv("ISOLATION_OVERLAP_FILE", str(log))

    async def four():
        return await asyncio.gather(*[
            run_ladder_isolated(_inp(), time_budget_s=60.0, hard_timeout_s=60.0,
                                target=targets.record_overlap) for _ in range(4)])

    pids = asyncio.run(four())
    assert len(set(pids)) == 4
    events = sorted((float(t), kind) for kind, t in (ln.split() for ln in log.read_text().splitlines()))
    now = peak = 0
    for _t, kind in events:
        now += 1 if kind == "start" else -1
        peak = max(peak, now)
    assert peak == 2


def _sampler(lon, lat):
    return lat * 1000.0


def test_contour_heading_resolved_in_parent():
    bbox = wgs84(RECT).bounds
    inp = _inp(heading_objective="contour", dem_sampler=_sampler, parcel_bbox=bbox)
    frozen = freeze_contour_heading(inp)
    c = inp.wgs84_poly.centroid
    assert frozen.cfg.dem_sampler is None
    assert frozen.cfg.heading_deg == best_contour_heading_deg((c.x, c.y), bbox, _sampler)
    # A closure sampler cannot be pickled: the runner must still work.
    lam = replace(inp, cfg=replace(inp.cfg, dem_sampler=lambda lon, lat: lat * 1000.0))
    plan = _run(lam)
    direct = plan_with_fallbacks(inp, time_budget_s=60.0)
    assert plan.as_api_dict(_shift_project, 4.0) == direct.as_api_dict(_shift_project, 4.0)


def test_explicit_heading_is_kept():
    inp = _inp(heading_deg=30.0, heading_objective="contour", dem_sampler=_sampler,
               parcel_bbox=wgs84(RECT).bounds)
    frozen = freeze_contour_heading(inp)
    assert frozen.cfg.heading_deg == 30.0 and frozen.cfg.dem_sampler is None


def test_child_logs_reach_parent_stream(capfd):
    _run()
    out, err = capfd.readouterr()
    assert "ladder attempt" in out + err
