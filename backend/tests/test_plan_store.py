from app.services.plan_store import PlanStore


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _rec(n=0):
    return {"plan_dict": {"n": n}, "body": {}, "result": None}


def test_put_get_roundtrip_and_created_at():
    clock = _Clock()
    s = PlanStore(clock=clock)
    pid = s.put("t1", _rec(1))
    rec = s.get("t1", pid)
    assert rec["plan_dict"] == {"n": 1}
    assert rec["created_at"] == 0.0


def test_other_tenant_gets_none():
    s = PlanStore()
    pid = s.put("t1", _rec())
    assert s.get("t2", pid) is None


def test_unknown_id_none():
    assert PlanStore().get("t1", "nope") is None


def test_ttl_expires_after_one_hour():
    clock = _Clock()
    s = PlanStore(clock=clock)
    pid = s.put("t1", _rec())
    clock.t = 3599
    assert s.get("t1", pid) is not None
    clock.t = 3600
    assert s.get("t1", pid) is None


def test_oldest_evicted_beyond_twenty_per_tenant():
    clock = _Clock()
    s = PlanStore(clock=clock)
    ids = []
    for i in range(21):
        clock.t = i
        ids.append(s.put("t1", _rec(i)))
    assert s.get("t1", ids[0]) is None
    assert s.get("t1", ids[1]) is not None
    assert s.get("t1", ids[20]) is not None


def test_eviction_is_per_tenant():
    s = PlanStore()
    other = s.put("t2", _rec())
    for i in range(25):
        s.put("t1", _rec(i))
    assert s.get("t2", other) is not None


def test_global_cap_evicts_oldest_across_tenants():
    clock = _Clock()
    s = PlanStore(max_total=3, clock=clock)
    ids = []
    for i in range(4):
        clock.t = i
        ids.append(s.put(f"t{i}", _rec(i)))
    assert s.get("t0", ids[0]) is None
    assert all(s.get(f"t{i}", ids[i]) for i in (1, 2, 3))
