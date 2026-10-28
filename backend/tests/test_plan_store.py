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


def _big(kb, n=0):
    return {"plan_dict": {"n": n, "blob": "x" * (kb * 1024)}, "body": {}, "result": None}


def test_tenant_byte_budget_evicts_oldest_first():
    clock = _Clock()
    s = PlanStore(clock=clock, max_tenant_bytes=100 * 1024, max_total_bytes=10 ** 9)
    ids = []
    for n in range(3):
        clock.t = float(n)
        ids.append(s.put("t1", _big(40, n)))
    # 3 x 40 KB > 100 KB: the oldest went
    assert s.get("t1", ids[0]) is None
    assert s.get("t1", ids[1]) is not None and s.get("t1", ids[2]) is not None


def test_tenant_budget_does_not_touch_other_tenants():
    clock = _Clock()
    s = PlanStore(clock=clock, max_tenant_bytes=100 * 1024, max_total_bytes=10 ** 9)
    other = s.put("t2", _big(80))
    for n in range(5):
        clock.t += 1
        s.put("t1", _big(40, n))
    assert s.get("t2", other) is not None


def test_global_byte_budget_evicts_oldest_across_tenants():
    clock = _Clock()
    s = PlanStore(clock=clock, max_tenant_bytes=10 ** 9, max_total_bytes=100 * 1024)
    a = s.put("t1", _big(40)); clock.t = 1
    b = s.put("t2", _big(40)); clock.t = 2
    c = s.put("t3", _big(40))
    assert s.get("t1", a) is None
    assert s.get("t2", b) is not None and s.get("t3", c) is not None


def test_record_larger_than_budget_is_not_stored():
    s = PlanStore(max_tenant_bytes=10 * 1024, max_total_bytes=10 ** 9)
    assert s.put("t1", _big(20)) is None
    assert s._plans == {}


def test_default_budgets_are_20mb_and_100mb():
    from app.services import plan_store
    assert plan_store.MAX_TENANT_BYTES == 20 * 1024 * 1024
    assert plan_store.MAX_TOTAL_BYTES == 100 * 1024 * 1024


def test_size_is_json_length_and_handles_namespaces():
    from types import SimpleNamespace
    from app.services.plan_store import record_size
    rec = {"plan_dict": {"a": 1}, "result": SimpleNamespace(swath_count=3)}
    assert record_size(rec) == len('{"plan_dict":{"a":1},"result":{"swath_count":3}}')
