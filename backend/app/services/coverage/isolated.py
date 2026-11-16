"""Run the coverage ladder in a child process.

Fields2Cover is native code: a crash inside it (SIGSEGV) ends the whole
process, and a worker thread does not contain it. Each generation therefore
runs in its own spawned process; the server only sees the result, a planning
error with its code, or the fact that the engine died. Spawn (not fork): the
server is multi-threaded and a forked child could inherit a held lock.
"""
from __future__ import annotations

import asyncio
import logging
import multiprocessing
import threading
import traceback
from dataclasses import replace
from time import monotonic
from typing import Callable

from app.logging_setup import configure_logging
from app.services.coverage.errors import PlanError
from app.services.coverage.ladder import LadderInput, plan_with_fallbacks
from app.services.exclusion import ExclusionError

logger = logging.getLogger(__name__)

MAX_CHILDREN = 2
_POLL_S = 0.5
_REAP_S = 5.0
# Threading, not asyncio: the wait runs in worker threads and must not be tied
# to one event loop.
_CHILD_SLOTS = threading.BoundedSemaphore(MAX_CHILDREN)
_CTX = multiprocessing.get_context("spawn")


class EngineCrashed(RuntimeError):
    """The engine process ended without sending a result."""


class EngineTimeout(RuntimeError):
    """The engine process ran past the hard timeout and was killed."""


def freeze_contour_heading(inp: LadderInput) -> LadderInput:
    """Resolve a contour heading here, so the child gets a plain angle.

    The DEM sampler is a closure and cannot cross a process boundary; the copy
    never carries it. An explicit heading wins, as in f2c_engine._resolve_angle.
    """
    cfg = inp.cfg
    heading = cfg.heading_deg
    if (heading is None and cfg.heading_objective == "contour"
            and cfg.dem_sampler and cfg.parcel_bbox):
        from app.services.coverage.contour import best_contour_heading_deg
        c = inp.wgs84_poly.centroid
        heading = best_contour_heading_deg((c.x, c.y), cfg.parcel_bbox, cfg.dem_sampler)
    return replace(inp, cfg=replace(cfg, heading_deg=heading, dem_sampler=None))


async def run_ladder_isolated(
    inp: LadderInput, *, time_budget_s: float | None, hard_timeout_s: float,
    log_level: str = "INFO", target: Callable = plan_with_fallbacks,
):
    """Run target(inp, time_budget_s=...) in a child process and return its result.

    Raises the child's ExclusionError/PlanError with the same code and params,
    RuntimeError for any other exception in the child, EngineCrashed when the
    child dies without a result and EngineTimeout after hard_timeout_s.
    """
    frozen = freeze_contour_heading(inp)
    msg = await asyncio.to_thread(_run_child, target, frozen, time_budget_s,
                                  hard_timeout_s, log_level)
    kind = msg[0]
    if kind == "ok":
        return msg[1]
    if kind == "plan_error":
        _, cls, code, detail, params = msg
        if cls == "exclusion":
            raise ExclusionError(detail, code=code, params=params)
        raise PlanError(code, detail, params)
    logger.error("engine child raised:\n%s", msg[1])
    raise RuntimeError("route engine failed in child")


def _run_child(target, inp, time_budget_s, hard_timeout_s, log_level) -> tuple:
    with _CHILD_SLOTS:
        recv_conn, send_conn = _CTX.Pipe(duplex=False)
        proc = _CTX.Process(target=_child_main,
                            args=(send_conn, target, inp, time_budget_s, log_level),
                            daemon=True)
        started = monotonic()
        proc.start()
        send_conn.close()   # only the child holds the write end: its death reads as EOF
        try:
            return _wait(proc, recv_conn, started, hard_timeout_s)
        finally:
            recv_conn.close()
            proc.join(_REAP_S)
            if proc.is_alive():
                proc.kill()
                proc.join(_REAP_S)


def _wait(proc, conn, started: float, hard_timeout_s: float) -> tuple:
    deadline = started + hard_timeout_s
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            proc.kill()
            proc.join(_REAP_S)
            _log_failure("timeout", proc, started)
            raise EngineTimeout(f"engine ran past {hard_timeout_s:.0f}s and was killed")
        # Read before join: a plan of several MB does not fit the pipe buffer.
        if conn.poll(min(_POLL_S, remaining)):
            try:
                return conn.recv()
            except EOFError:
                proc.join(_REAP_S)
                _log_failure("crashed", proc, started)
                raise EngineCrashed(f"engine ended without a result: exitcode={proc.exitcode}")


def _log_failure(reason: str, proc, started: float) -> None:
    logger.error("engine child failed: reason=%s exitcode=%s pid=%s elapsed=%.1fs",
                 reason, proc.exitcode, proc.pid, monotonic() - started)


def _child_main(conn, target, inp, time_budget_s, log_level) -> None:
    configure_logging(log_level)
    try:
        msg = ("ok", target(inp, time_budget_s=time_budget_s))
    except ExclusionError as e:
        msg = ("plan_error", "exclusion", e.code, e.detail, e.params)
    except PlanError as e:
        msg = ("plan_error", "plan", e.code, e.detail, e.params)
    except Exception:
        msg = ("error", traceback.format_exc())
    try:
        conn.send(msg)
    except Exception:
        conn.send(("error", traceback.format_exc()))
    finally:
        conn.close()
