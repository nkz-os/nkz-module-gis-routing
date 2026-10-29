"""Tenant-scoped, TTL-bound in-memory store for A-B pathfinding jobs."""
import time
import uuid


_TERMINAL = ("completed", "failed")


class JobLimitError(Exception):
    """The tenant already has the maximum number of queued or running jobs."""


class JobStore:
    def __init__(self, ttl_s: int = 3600, max_per_tenant: int = 3, clock=time.monotonic,
                 finished_ttl_s: int = 900, max_finished_per_tenant: int = 5,
                 max_finished_global: int = 50) -> None:
        # ttl_s bounds a job that never finishes; finished_ttl_s counts from completion.
        self._ttl_s = ttl_s
        self._finished_ttl_s = finished_ttl_s
        self._max_per_tenant = max_per_tenant
        self._max_finished_per_tenant = max_finished_per_tenant
        self._max_finished_global = max_finished_global
        self._clock = clock
        self._jobs: dict[str, dict] = {}

    @property
    def max_per_tenant(self) -> int:
        return self._max_per_tenant

    @staticmethod
    def _finished(entry: dict) -> bool:
        return entry["payload"].get("status") in _TERMINAL

    def _expired(self, entry: dict) -> bool:
        finished_at = entry.get("finished_at")
        if finished_at is not None:
            return self._clock() - finished_at >= self._finished_ttl_s
        return self._clock() - entry["created_at"] >= self._ttl_s

    def _evict_finished(self) -> None:
        """Oldest finished first: per tenant, then globally. Active jobs are never evicted."""
        done = sorted((e["finished_at"], j) for j, e in self._jobs.items()
                      if e.get("finished_at") is not None)
        per_tenant: dict[str, list[str]] = {}
        for _, j in done:
            per_tenant.setdefault(self._jobs[j]["tenant_id"], []).append(j)
        for ids in per_tenant.values():
            for j in ids[:max(0, len(ids) - self._max_finished_per_tenant)]:
                del self._jobs[j]
        left = [j for _, j in done if j in self._jobs]
        for j in left[:max(0, len(left) - self._max_finished_global)]:
            del self._jobs[j]

    def purge(self) -> int:
        """Drop expired jobs; return how many live jobs remain."""
        for job_id in [j for j, e in self._jobs.items() if self._expired(e)]:
            del self._jobs[job_id]
        return len(self._jobs)

    def create(self, tenant_id: str) -> str:
        self.purge()
        # Finished jobs stay readable until the TTL but do not count against the limit.
        active = sum(1 for e in self._jobs.values()
                     if e["tenant_id"] == tenant_id and e["payload"].get("status") in ("queued", "running"))
        if active >= self._max_per_tenant:
            raise JobLimitError(tenant_id)
        job_id = uuid.uuid4().hex[:12]
        self._jobs[job_id] = {
            "tenant_id": tenant_id,
            "created_at": self._clock(),
            "payload": {"status": "queued", "result": None},
        }
        return job_id

    def set(self, job_id: str, payload: dict) -> None:
        entry = self._jobs.get(job_id)
        if entry is not None:
            entry["payload"] = payload
            if self._finished(entry) and entry.get("finished_at") is None:
                entry["finished_at"] = self._clock()
                self._evict_finished()

    def get(self, job_id: str, tenant_id: str) -> dict | None:
        self.purge()
        entry = self._jobs.get(job_id)
        if entry is None or self._expired(entry) or entry["tenant_id"] != tenant_id:
            return None
        return entry["payload"]
