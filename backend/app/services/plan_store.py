"""Tenant-scoped, TTL-bound in-memory store for generated work plans.

A plan generated with ``persist: false`` is kept here so it can be saved later
by plan_id. Single replica, like the A-B JobStore.
"""
import json
import time
import uuid

# Memory budget, measured as the length of the JSON-serialised record (the in-memory object
# tree is several times larger): per tenant, then for the whole pod (512 MiB limit).
MAX_TENANT_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024


def _json_default(obj):
    return vars(obj) if hasattr(obj, "__dict__") else str(obj)


def record_size(record: dict) -> int:
    """Bytes of the record as compact JSON."""
    return len(json.dumps(record, separators=(",", ":"), default=_json_default).encode("utf-8"))


class PlanStore:
    def __init__(self, ttl_s: int = 3600, max_per_tenant: int = 20, max_total: int = 500, clock=time.monotonic,
                 max_tenant_bytes: int = MAX_TENANT_BYTES, max_total_bytes: int = MAX_TOTAL_BYTES) -> None:
        self._ttl_s = ttl_s
        self._max_per_tenant = max_per_tenant
        self._max_total = max_total
        self._max_tenant_bytes = max_tenant_bytes
        self._max_total_bytes = max_total_bytes
        self._clock = clock
        self._plans: dict[str, dict] = {}

    def _expired(self, entry: dict) -> bool:
        return self._clock() - entry["record"]["created_at"] >= self._ttl_s

    def _purge(self) -> None:
        for pid in [p for p, e in self._plans.items() if self._expired(e)]:
            del self._plans[pid]

    def _evict_oldest(self, pids: list[str], needed_free: int, used: int, cap: int) -> None:
        """Drop the oldest of pids until used + needed_free fits in cap."""
        pids = sorted(pids, key=lambda p: self._plans[p]["record"]["created_at"])
        for pid in pids:
            if used + needed_free <= cap:
                break
            used -= self._plans[pid]["bytes"]
            del self._plans[pid]

    def put(self, tenant_id: str, record: dict) -> str | None:
        """Store record (plan_dict, body, result); returns the new plan_id.

        Returns None, storing nothing, when the record alone exceeds the tenant byte budget.
        Older plans are evicted (oldest first) to make room: by count, then per-tenant bytes,
        then pod-wide bytes.
        """
        size = record_size(record)
        if size > self._max_tenant_bytes or size > self._max_total_bytes:
            return None
        self._purge()
        mine = [(e["record"]["created_at"], p) for p, e in self._plans.items()
                if e["tenant_id"] == tenant_id]
        mine.sort()
        for _created, pid in mine[: max(0, len(mine) - self._max_per_tenant + 1)]:
            del self._plans[pid]
        overflow = len(self._plans) - self._max_total + 1
        if overflow > 0:
            oldest = sorted(self._plans, key=lambda p: self._plans[p]["record"]["created_at"])
            for pid in oldest[:overflow]:
                del self._plans[pid]
        mine_ids = [p for p, e in self._plans.items() if e["tenant_id"] == tenant_id]
        self._evict_oldest(mine_ids, size, sum(self._plans[p]["bytes"] for p in mine_ids),
                           self._max_tenant_bytes)
        self._evict_oldest(list(self._plans), size, sum(e["bytes"] for e in self._plans.values()),
                           self._max_total_bytes)
        plan_id = uuid.uuid4().hex
        self._plans[plan_id] = {
            "tenant_id": tenant_id,
            "bytes": size,
            "record": {**record, "created_at": self._clock()},
        }
        return plan_id

    def get(self, tenant_id: str, plan_id: str) -> dict | None:
        entry = self._plans.get(plan_id)
        if entry is None or self._expired(entry) or entry["tenant_id"] != tenant_id:
            return None
        return entry["record"]


PLAN_STORE = PlanStore()
