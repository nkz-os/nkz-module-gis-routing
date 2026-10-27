"""Tenant-scoped, TTL-bound in-memory store for A-B pathfinding jobs."""
import time
import uuid


class JobLimitError(Exception):
    """The tenant already has the maximum number of live jobs."""


class JobStore:
    def __init__(self, ttl_s: int = 3600, max_per_tenant: int = 20, clock=time.monotonic) -> None:
        self._ttl_s = ttl_s
        self._max_per_tenant = max_per_tenant
        self._clock = clock
        self._jobs: dict[str, dict] = {}

    def _expired(self, entry: dict) -> bool:
        return self._clock() - entry["created_at"] >= self._ttl_s

    def purge(self) -> int:
        """Drop expired jobs; return how many live jobs remain."""
        for job_id in [j for j, e in self._jobs.items() if self._expired(e)]:
            del self._jobs[job_id]
        return len(self._jobs)

    def create(self, tenant_id: str) -> str:
        self.purge()
        live = sum(1 for e in self._jobs.values() if e["tenant_id"] == tenant_id)
        if live >= self._max_per_tenant:
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

    def get(self, job_id: str, tenant_id: str) -> dict | None:
        entry = self._jobs.get(job_id)
        if entry is None or self._expired(entry) or entry["tenant_id"] != tenant_id:
            return None
        return entry["payload"]
