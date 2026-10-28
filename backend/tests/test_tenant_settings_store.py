import asyncio
import os
import uuid

import pytest

from app.services import tenant_settings
from app.services.tenant_settings import PgSettingsStore


def test_failing_init_closes_the_pool(monkeypatch):
    state = {"closed": False}

    class Conn:
        async def fetchval(self, *a):
            raise RuntimeError("ddl denied")

    class Acq:
        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, *a):
            return False

    class Pool:
        def acquire(self):
            return Acq()

        async def close(self):
            state["closed"] = True

    async def create_pool(*a, **k):
        return Pool()
    monkeypatch.setattr(tenant_settings.asyncpg, "create_pool", create_pool)
    store = PgSettingsStore("postgresql://x/y")
    with pytest.raises(RuntimeError):
        asyncio.run(store.get_dispatch("t"))
    assert state["closed"] is True and store._pool is None


DSN = os.environ.get("NKZ_TEST_PG_DSN")


@pytest.mark.skipif(not DSN, reason="NKZ_TEST_PG_DSN not set")
def test_postgres_roundtrip_and_ddl_twice():
    import asyncpg

    tid = "pg-" + uuid.uuid4().hex

    async def run():
        a = PgSettingsStore(DSN)
        assert await a.get_dispatch(tid) is None
        await a.put_dispatch(tid, "digest", "u")
        await a.put_dispatch(tid, "none", "u")
        b = PgSettingsStore(DSN)   # table exists: no DDL needed
        assert await b.get_dispatch(tid) == "none"
        with pytest.raises(asyncpg.CheckViolationError):
            await b.put_dispatch(tid + "-2", "sms", "u")
        await a.close()
        await b.close()
    asyncio.run(run())
