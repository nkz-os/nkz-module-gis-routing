"""Tenant-scoped, TTL-bound in-memory store for generated work plans.

A plan generated with ``persist: false`` is kept here so it can be saved later
by plan_id. Single replica, like the A-B JobStore.
"""
import time
import uuid


class PlanStore:
    def __init__(self, ttl_s: int = 3600, max_per_tenant: int = 20, clock=time.monotonic) -> None:
        self._ttl_s = ttl_s
        self._max_per_tenant = max_per_tenant
        self._clock = clock
        self._plans: dict[str, dict] = {}

    def _expired(self, entry: dict) -> bool:
        return self._clock() - entry["record"]["created_at"] >= self._ttl_s

    def _purge(self) -> None:
        for pid in [p for p, e in self._plans.items() if self._expired(e)]:
            del self._plans[pid]

    def put(self, tenant_id: str, record: dict) -> str:
        """Store record (plan_dict, body, result); returns the new plan_id."""
        self._purge()
        mine = [(e["record"]["created_at"], p) for p, e in self._plans.items()
                if e["tenant_id"] == tenant_id]
        mine.sort()
        for _created, pid in mine[: max(0, len(mine) - self._max_per_tenant + 1)]:
            del self._plans[pid]
        plan_id = uuid.uuid4().hex
        self._plans[plan_id] = {
            "tenant_id": tenant_id,
            "record": {**record, "created_at": self._clock()},
        }
        return plan_id

    def get(self, tenant_id: str, plan_id: str) -> dict | None:
        entry = self._plans.get(plan_id)
        if entry is None or self._expired(entry) or entry["tenant_id"] != tenant_id:
            return None
        return entry["record"]


PLAN_STORE = PlanStore()
