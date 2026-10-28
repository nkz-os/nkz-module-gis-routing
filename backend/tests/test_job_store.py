import pytest
from app.services.pathfinding.job_store import JobStore, JobLimitError


def _clock():
    t = {"now": 0.0}
    return t, (lambda: t["now"])


def test_job_store_scopes_by_tenant():
    t, clock = _clock()
    s = JobStore(ttl_s=10, clock=clock)
    jid = s.create("tenant-a")
    s.set(jid, {"status": "completed", "alternatives": []})
    assert s.get(jid, "tenant-a")["status"] == "completed"
    assert s.get(jid, "tenant-b") is None


def test_job_store_expires():
    t, clock = _clock()
    s = JobStore(ttl_s=10, clock=clock)
    jid = s.create("tenant-a")
    t["now"] = 11.0
    assert s.get(jid, "tenant-a") is None and s.purge() == 0


def test_job_store_limit_per_tenant():
    t, clock = _clock()
    s = JobStore(ttl_s=10, max_per_tenant=2, clock=clock)
    s.create("tenant-a"); s.create("tenant-a")
    with pytest.raises(JobLimitError):
        s.create("tenant-a")
    s.create("tenant-b")
    t["now"] = 11.0
    s.create("tenant-a")   # after expiry there is room again


def test_job_store_default_limit_is_three():
    assert JobStore()._max_per_tenant == 3


def test_job_store_limit_counts_only_queued_and_running():
    t, clock = _clock()
    s = JobStore(ttl_s=10, max_per_tenant=2, clock=clock)
    a, b = s.create("tenant-a"), s.create("tenant-a")
    s.set(a, {"status": "completed", "alternatives": []})
    s.set(b, {"status": "failed", "error": "x"})
    # two finished jobs: still room for the full quota of live ones
    c, d = s.create("tenant-a"), s.create("tenant-a")
    s.set(c, {"status": "running"})
    with pytest.raises(JobLimitError):
        s.create("tenant-a")
    s.set(d, {"status": "completed"})
    s.create("tenant-a")
    assert s.get(a, "tenant-a")["status"] == "completed"   # finished jobs stay readable
