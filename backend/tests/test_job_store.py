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


def test_finished_ttl_counts_from_completion():
    t, clock = _clock()
    s = JobStore(ttl_s=3600, finished_ttl_s=900, clock=clock)
    jid = s.create("tenant-a")
    t["now"] = 3000.0
    s.set(jid, {"status": "completed"})
    t["now"] = 3000.0 + 899
    assert s.get(jid, "tenant-a") is not None
    t["now"] = 3000.0 + 901
    assert s.get(jid, "tenant-a") is None and s.purge() == 0


def test_finished_jobs_capped_per_tenant_oldest_first():
    t, clock = _clock()
    s = JobStore(max_per_tenant=10, max_finished_per_tenant=5, clock=clock)
    ids = []
    for i in range(7):
        t["now"] = float(i)
        j = s.create("tenant-a")
        s.set(j, {"status": "completed"})
        ids.append(j)
    assert [s.get(j, "tenant-a") is not None for j in ids] == [False, False] + [True] * 5


def test_finished_jobs_capped_globally():
    t, clock = _clock()
    s = JobStore(max_finished_per_tenant=5, max_finished_global=8, clock=clock)
    kept = []
    for n in range(4):
        for i in range(3):
            t["now"] += 1
            j = s.create(f"tenant-{n}")
            s.set(j, {"status": "failed"})
            kept.append((f"tenant-{n}", j))
    alive = [k for k in kept if s.get(k[1], k[0]) is not None]
    assert len(alive) == 8 and alive == kept[-8:]


def test_active_jobs_are_never_evicted_by_the_finished_cap():
    t, clock = _clock()
    s = JobStore(max_per_tenant=10, max_finished_per_tenant=1, clock=clock)
    running = s.create("tenant-a")
    s.set(running, {"status": "running"})
    for _ in range(3):
        t["now"] += 1
        s.set(s.create("tenant-a"), {"status": "completed"})
    assert s.get(running, "tenant-a")["status"] == "running"


def test_get_purges_expired_jobs_of_other_tenants():
    t, clock = _clock()
    s = JobStore(ttl_s=10, clock=clock)
    s.create("tenant-b")
    jid = s.create("tenant-a")
    t["now"] = 11.0
    s.get(jid, "tenant-a")
    assert len(s._jobs) == 0
