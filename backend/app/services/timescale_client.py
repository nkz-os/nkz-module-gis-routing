"""
TimescaleDB client for GIS Routing -- asyncpg-powered materialized sync tables.

Maintains three materialized tables (sync_parcels, sync_equipment,
sync_operations) sourced from Orion-LD entities via the sync pipeline.
Uses UPSERT semantics so the tables act as a read-optimised materialised
view of the current NGSI-LD state.
"""

import logging
from typing import Any, Optional

import asyncpg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL -- idempotent table creation
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS sync_parcels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    remote_id TEXT NOT NULL UNIQUE,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    geojson TEXT NOT NULL,
    area DOUBLE PRECISION NOT NULL,
    crop_type TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    centroid_lat DOUBLE PRECISION,
    centroid_lng DOUBLE PRECISION,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);
ALTER TABLE sync_parcels ADD COLUMN IF NOT EXISTS access_point JSONB;
ALTER TABLE sync_parcels ADD COLUMN IF NOT EXISTS exclusion_zones JSONB;
CREATE INDEX IF NOT EXISTS idx_sync_parcels_tenant ON sync_parcels(tenant_id);
CREATE INDEX IF NOT EXISTS idx_sync_parcels_updated ON sync_parcels(tenant_id, updated_at);

CREATE TABLE IF NOT EXISTS sync_equipment (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    remote_id TEXT NOT NULL UNIQUE,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    equipment_type TEXT NOT NULL,
    implement_width DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL DEFAULT 'available',
    steering_type TEXT DEFAULT 'ackermann',
    steering_axles TEXT DEFAULT 'front',
    track_width DOUBLE PRECISION,
    wheelbase DOUBLE PRECISION,
    gps_offset_x DOUBLE PRECISION DEFAULT 0,
    gps_offset_y DOUBLE PRECISION DEFAULT 0,
    gps_offset_z DOUBLE PRECISION DEFAULT 0,
    hitch_type TEXT DEFAULT 'none',
    hitch_offset_x DOUBLE PRECISION DEFAULT 0,
    implement_length DOUBLE PRECISION DEFAULT 0,
    implement_offset_x DOUBLE PRECISION DEFAULT 0,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sync_equipment_tenant ON sync_equipment(tenant_id);
CREATE INDEX IF NOT EXISTS idx_sync_equipment_updated ON sync_equipment(tenant_id, updated_at);

CREATE TABLE IF NOT EXISTS sync_operations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    remote_id TEXT UNIQUE,
    tenant_id TEXT NOT NULL,
    parcel_id TEXT NOT NULL,
    equipment_id TEXT,
    tractor_id TEXT,
    implement_id TEXT,
    operation_type TEXT NOT NULL,
    ab_line_geojson TEXT NOT NULL,
    implement_width DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    vra_enabled BOOLEAN DEFAULT FALSE,
    prescription_map TEXT,
    base_rate DOUBLE PRECISION,
    rate_unit TEXT,
    coverage_geojson TEXT,
    area_covered_ha DOUBLE PRECISION,
    started_at BIGINT,
    completed_at BIGINT,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sync_operations_tenant ON sync_operations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_sync_operations_updated ON sync_operations(tenant_id, updated_at);
"""

# ---------------------------------------------------------------------------
# UPSERT statements  (parameterised -- $1, $2, …)
# ---------------------------------------------------------------------------

UPSERT_PARCEL = """
INSERT INTO sync_parcels (remote_id, tenant_id, name, geojson, area, crop_type, status,
    centroid_lat, centroid_lng, access_point, exclusion_zones, created_at, updated_at)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
ON CONFLICT (remote_id) DO UPDATE SET
    name = EXCLUDED.name, geojson = EXCLUDED.geojson, area = EXCLUDED.area,
    crop_type = EXCLUDED.crop_type, status = EXCLUDED.status,
    centroid_lat = EXCLUDED.centroid_lat, centroid_lng = EXCLUDED.centroid_lng,
    access_point = EXCLUDED.access_point, exclusion_zones = EXCLUDED.exclusion_zones,
    updated_at = EXCLUDED.updated_at
"""

UPSERT_EQUIPMENT = """
INSERT INTO sync_equipment (remote_id, tenant_id, name, equipment_type, implement_width,
    status, steering_type, steering_axles, track_width, wheelbase,
    gps_offset_x, gps_offset_y, gps_offset_z,
    hitch_type, hitch_offset_x, implement_length, implement_offset_x,
    created_at, updated_at)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
ON CONFLICT (remote_id) DO UPDATE SET
    name = EXCLUDED.name, equipment_type = EXCLUDED.equipment_type,
    implement_width = EXCLUDED.implement_width, status = EXCLUDED.status,
    steering_type = EXCLUDED.steering_type, steering_axles = EXCLUDED.steering_axles,
    track_width = EXCLUDED.track_width, wheelbase = EXCLUDED.wheelbase,
    gps_offset_x = EXCLUDED.gps_offset_x, gps_offset_y = EXCLUDED.gps_offset_y,
    gps_offset_z = EXCLUDED.gps_offset_z,
    hitch_type = EXCLUDED.hitch_type, hitch_offset_x = EXCLUDED.hitch_offset_x,
    implement_length = EXCLUDED.implement_length, implement_offset_x = EXCLUDED.implement_offset_x,
    updated_at = EXCLUDED.updated_at
"""

UPSERT_OPERATION = """
INSERT INTO sync_operations (remote_id, tenant_id, parcel_id, equipment_id, tractor_id,
    implement_id, operation_type, ab_line_geojson, implement_width, status,
    vra_enabled, prescription_map, base_rate, rate_unit,
    started_at, completed_at, created_at, updated_at)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
ON CONFLICT (remote_id) DO UPDATE SET
    status = EXCLUDED.status, vra_enabled = EXCLUDED.vra_enabled,
    prescription_map = EXCLUDED.prescription_map,
    coverage_geojson = EXCLUDED.coverage_geojson,
    area_covered_ha = EXCLUDED.area_covered_ha,
    started_at = EXCLUDED.started_at, completed_at = EXCLUDED.completed_at,
    updated_at = EXCLUDED.updated_at
"""

# ---------------------------------------------------------------------------
# Delta query  (used by get_changes)
# ---------------------------------------------------------------------------

DELTA_QUERY = """
SELECT *,
    CASE
        WHEN updated_at > $2 AND created_at = updated_at THEN 'created'
        WHEN updated_at > $2 THEN 'updated'
    END AS _change_type
FROM {table}
WHERE tenant_id = $1 AND updated_at > $2
ORDER BY updated_at ASC
LIMIT $3
"""

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_NUMERIC_FIELDS = frozenset({
    "area", "implement_width", "track_width", "wheelbase",
    "gps_offset_x", "gps_offset_y", "gps_offset_z",
    "hitch_offset_x", "implement_length", "implement_offset_x",
    "base_rate", "area_covered_ha", "centroid_lat", "centroid_lng",
})

_TIMESTAMP_FIELDS = frozenset({
    "created_at", "updated_at", "started_at", "completed_at",
})

_TABLE_MAP: dict[str, str] = {
    "parcels": "sync_parcels",
    "equipment": "sync_equipment",
    "operations": "sync_operations",
}


class TimescaleDBClient:
    """Asyncpg-backed TimescaleDB client with sync materialisation tables.

    Maintains three UPSERT-based materialised tables (sync_parcels,
    sync_equipment, sync_operations) and exposes a unified ``get_changes``
    delta API used by the sync endpoint.
    """

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None

    # ----- lifecycle -----------------------------------------------------

    async def connect(self) -> None:
        """Create the connection pool and run DDL."""
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(self.dsn, min_size=2, max_size=10)
        async with self._pool.acquire() as conn:
            await conn.execute(DDL)
        logger.info("TimescaleDB pool created and DDL applied")

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("TimescaleDB pool closed")

    # ----- public query helper -------------------------------------------

    async def fetchrow(self, query: str, *args):
        """Execute a query and return a single row.

        Handles connection lifecycle so callers don't need to manage
        connect()/close() or access the internal pool.
        """
        await self.connect()
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    # ----- materialisation (upsert) --------------------------------------

    async def materialize_parcel(
        self,
        remote_id: str,
        tenant_id: str,
        name: str,
        geojson: str,
        area: float,
        crop_type: str | None,
        status: str,
        centroid_lat: float | None,
        centroid_lng: float | None,
        updated_at: int,
        access_point: str | None = None,
        exclusion_zones: str | None = None,
    ) -> None:
        now = updated_at
        async with self._pool.acquire() as conn:
            await conn.execute(
                UPSERT_PARCEL,
                remote_id, tenant_id, name, geojson, area, crop_type, status,
                centroid_lat, centroid_lng, access_point, exclusion_zones, now, now,
            )

    async def materialize_equipment(
        self,
        remote_id: str,
        tenant_id: str,
        name: str,
        equipment_type: str,
        implement_width: float,
        status: str,
        steering_type: str,
        steering_axles: str,
        track_width: float | None,
        wheelbase: float | None,
        gps_offset_x: float,
        gps_offset_y: float,
        gps_offset_z: float,
        hitch_type: str,
        hitch_offset_x: float,
        implement_length: float,
        implement_offset_x: float,
        updated_at: int,
    ) -> None:
        now = updated_at
        async with self._pool.acquire() as conn:
            await conn.execute(
                UPSERT_EQUIPMENT,
                remote_id, tenant_id, name, equipment_type, implement_width, status,
                steering_type, steering_axles, track_width, wheelbase,
                gps_offset_x, gps_offset_y, gps_offset_z,
                hitch_type, hitch_offset_x, implement_length, implement_offset_x,
                now, now,
            )

    async def materialize_operation(
        self,
        remote_id: str | None,
        tenant_id: str,
        parcel_id: str,
        equipment_id: str | None,
        tractor_id: str | None,
        implement_id: str | None,
        operation_type: str,
        ab_line_geojson: str,
        implement_width: float,
        status: str,
        vra_enabled: bool,
        prescription_map: str | None,
        base_rate: float | None,
        rate_unit: str | None,
        started_at: int | None,
        completed_at: int | None,
        updated_at: int,
    ) -> None:
        now = updated_at
        async with self._pool.acquire() as conn:
            await conn.execute(
                UPSERT_OPERATION,
                remote_id, tenant_id, parcel_id, equipment_id, tractor_id,
                implement_id, operation_type, ab_line_geojson, implement_width, status,
                vra_enabled, prescription_map, base_rate, rate_unit,
                started_at, completed_at, now, now,
            )

    # ----- delta query ---------------------------------------------------

    async def get_changes(
        self,
        table: str,
        tenant_id: str,
        last_pulled_at: int,
        limit: int = 1000,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return ``{created, updated, deleted}`` records newer than
        *last_pulled_at* for the given sync *table* name.

        ``deleted`` is always an empty list in this implementation (soft-delete
        discipline is handled at the application layer).
        """
        db_table = _TABLE_MAP.get(table)
        if db_table is None:
            raise ValueError(f"Unknown collection: {table}")

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                DELTA_QUERY.format(table=db_table),
                tenant_id,
                last_pulled_at,
                limit,
            )

        created: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []

        for row in rows:
            record = dict(row)
            change_type = record.pop("_change_type")

            # Convert UUID -> str for JSON serialisation
            record["id"] = str(record["id"])

            # Normalise numeric fields
            for k in _NUMERIC_FIELDS:
                if k in record and record[k] is not None:
                    record[k] = float(record[k])

            # Normalise integer timestamps
            for k in _TIMESTAMP_FIELDS:
                if k in record and record[k] is not None:
                    record[k] = int(record[k])

            if change_type == "created":
                created.append(record)
            else:
                updated.append(record)

        return {"created": created, "updated": updated, "deleted": []}



