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
import traceback
from concurrent.futures import ThreadPoolExecutor
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
# One waiting thread per child, in a pool of its own: queued generations hold no
# thread of the loop's default executor (DNS lookups, other to_thread work) and
# the pool size is the cap on children. Not tied to any event loop.
_ENGINE_POOL = ThreadPoolExecutor(max_workers=MAX_CHILDREN, thread_name_prefix="engine")
_CTX = multiprocessing.get_context("spawn")


class EngineCrashed(RuntimeError):
    """The engine process ended without sending a result."""


class EngineTimeout(RuntimeError):
    """The engine process ran past the hard timeout and was killed."""


async def run_ladder_isolated(
    inp: LadderInput, *, time_budget_s: float | None, hard_timeout_s: float,
    log_level: str = "INFO", target: Callable = plan_with_fallbacks,
    tenant_id: str | None = None, parcel_id: str | None = None,
):
    """Run target(inp, time_budget_s=...) in a child process and return its result.

    Raises the child's ExclusionError/PlanError with the same code and params,
    RuntimeError for any other exception in the child, EngineCrashed when the
    child dies without a result and EngineTimeout after hard_timeout_s.
    """
    context = {"tenant_id": tenant_id, "parcel_id": parcel_id}
    msg = await asyncio.get_running_loop().run_in_executor(
        _ENGINE_POOL, _run_child, target, inp, time_budget_s, hard_timeout_s, log_level, context)
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


def _run_child(target, inp, time_budget_s, hard_timeout_s, log_level, context: dict) -> tuple:
    recv_conn, send_conn = _CTX.Pipe(duplex=False)
    proc = _CTX.Process(target=_child_main,
                        args=(send_conn, target, inp, time_budget_s, log_level),
                        daemon=True)
    started = monotonic()
    proc.start()
    send_conn.close()   # only the child holds the write end: its death reads as EOF
    try:
        return _wait(proc, recv_conn, started, hard_timeout_s, context)
    finally:
        recv_conn.close()
        proc.join(_REAP_S)
        if proc.is_alive():
            proc.kill()
            proc.join(_REAP_S)


def _wait(proc, conn, started: float, hard_timeout_s: float, context: dict) -> tuple:
    deadline = started + hard_timeout_s
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            proc.kill()
            proc.join(_REAP_S)
            _log_failure("timeout", proc, started, context)
            raise EngineTimeout(f"engine ran past {hard_timeout_s:.0f}s and was killed")
        # Read before join: a plan of several MB does not fit the pipe buffer.
        if conn.poll(min(_POLL_S, remaining)):
            try:
                return conn.recv()
            except (EOFError, OSError):   # OSError: child died part-way through the message
                proc.join(_REAP_S)
                _log_failure("crashed", proc, started, context)
                raise EngineCrashed(f"engine ended without a result: exitcode={proc.exitcode}")


def _log_failure(reason: str, proc, started: float, context: dict) -> None:
    logger.error("engine child failed: reason=%s exitcode=%s pid=%s elapsed=%.1fs "
                 "tenant_id=%s parcel_id=%s", reason, proc.exitcode, proc.pid,
                 monotonic() - started, context.get("tenant_id"), context.get("parcel_id"))


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
