"""Engine stand-ins for the isolated runner tests.

Top-level functions so the spawned child can import them by name. Each takes the
runner's call shape: target(inp, time_budget_s=...).
"""
import os
import signal
import time

from shapely.geometry import LineString


def segv(inp, time_budget_s=None):
    os.kill(os.getpid(), signal.SIGSEGV)


def exit_quietly(inp, time_budget_s=None):
    os._exit(0)


def sleep_forever(inp, time_budget_s=None):
    time.sleep(3600)


def raise_exclusion(inp, time_budget_s=None):
    from app.services.exclusion import ExclusionError
    raise ExclusionError("x", code="NO_DRIVABLE_AREA", params={"a": 1})


def raise_runtime(inp, time_budget_s=None):
    raise RuntimeError("engine stand-in failed")


def big_result(inp, time_budget_s=None):
    """About 8 MB pickled: bigger than any pipe buffer."""
    return LineString([(float(i), float(i % 7)) for i in range(500_000)])


def record_overlap(inp, time_budget_s=None):
    """Append start/end timestamps to the file named by ISOLATION_OVERLAP_FILE."""
    path = os.environ["ISOLATION_OVERLAP_FILE"]
    with open(path, "a") as f:
        f.write(f"start {time.monotonic()}\n")
    time.sleep(1.0)
    with open(path, "a") as f:
        f.write(f"end {time.monotonic()}\n")
    return os.getpid()
