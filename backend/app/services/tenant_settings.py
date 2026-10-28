"""Per-tenant module settings, stored in the module's own database.

Today one setting: how the tractor operator is told about a new operation.
The store is an interface so tests run without Postgres.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Protocol

import asyncpg

from app.config import get_settings

logger = logging.getLogger(__name__)

DISPATCH_VALUES = ("immediate", "digest", "none")
DEFAULT_DISPATCH = "immediate"

DDL = """
CREATE TABLE IF NOT EXISTS gis_routing_tenant_settings (
    tenant_id TEXT PRIMARY KEY,
    dispatch_notification TEXT NOT NULL DEFAULT 'immediate'
        CHECK (dispatch_notification IN ('immediate', 'digest', 'none')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by TEXT
);
"""


class SettingsStore(Protocol):
    async def get_dispatch(self, tenant_id: str) -> Optional[str]: ...

    async def put_dispatch(self, tenant_id: str, value: str, user_id: str) -> None: ...

    async def close(self) -> None: ...


class PgSettingsStore:
    """asyncpg pool created on first use; idempotent DDL runs at connect."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None
        self._lock = asyncio.Lock()

    async def _acquire_pool(self) -> asyncpg.Pool:
        async with self._lock:
            if self._pool is None:
                pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
                try:
                    async with pool.acquire() as conn:
                        # CREATE needs privileges on the schema even for an existing
                        # table, so a role without them works once the table exists.
                        if await conn.fetchval("SELECT to_regclass('gis_routing_tenant_settings')") is None:
                            await conn.execute(DDL)
                except BaseException:
                    await pool.close()
                    raise
                self._pool = pool
                logger.info("gis_routing_tenant_settings pool created and DDL applied")
            return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def get_dispatch(self, tenant_id: str) -> Optional[str]:
        pool = await self._acquire_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT dispatch_notification FROM gis_routing_tenant_settings WHERE tenant_id = $1",
                tenant_id)

    async def put_dispatch(self, tenant_id: str, value: str, user_id: str) -> None:
        pool = await self._acquire_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO gis_routing_tenant_settings (tenant_id, dispatch_notification, updated_by)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (tenant_id) DO UPDATE
                   SET dispatch_notification = EXCLUDED.dispatch_notification,
                       updated_at = now(), updated_by = EXCLUDED.updated_by""",
                tenant_id, value, user_id)


_STORE: Optional[SettingsStore] = None


def get_store() -> SettingsStore:
    global _STORE
    if _STORE is None:
        _STORE = PgSettingsStore(get_settings().database_url)
    return _STORE


def set_store(store: Optional[SettingsStore]) -> None:
    """Replace the store (tests); None resets to the Postgres default."""
    global _STORE
    _STORE = store


async def dispatch_setting(tenant_id: str) -> str:
    """The tenant's setting; a tenant without a row gets the default."""
    return (await get_store().get_dispatch(tenant_id)) or DEFAULT_DISPATCH


async def close_store() -> None:
    """Close the store's pool (application shutdown)."""
    if _STORE is not None:
        try:
            await _STORE.close()
        except Exception:
            logger.warning("settings store close failed", exc_info=True)
