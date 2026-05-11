"""CRUD for field_patterns -- reusable route templates."""

import json
import uuid
import time
from typing import Optional


class PatternStore:
    def __init__(self, timescale):
        self._ts = timescale

    async def save(
        self, tenant_id, parcel_id, name, pattern_type,
        pattern_config, route_geojson, vra_prescription_map,
        equipment_tractor_id, equipment_implement_id, source_operation_id,
    ) -> str:
        pattern_id = str(uuid.uuid4())
        now = int(time.time() * 1000)
        await self._ts.connect()
        async with self._ts._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO field_patterns
                    (id, tenant_id, parcel_id, name, pattern_type, pattern_config,
                     route_geojson, vra_prescription_map,
                     equipment_tractor_id, equipment_implement_id,
                     source_operation_id, created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)""",
                pattern_id, tenant_id, parcel_id, name, pattern_type,
                json.dumps(pattern_config),
                route_geojson,
                json.dumps(vra_prescription_map) if vra_prescription_map else None,
                equipment_tractor_id, equipment_implement_id,
                source_operation_id, now, now,
            )
        return pattern_id

    async def list_for_parcel(self, tenant_id, parcel_id, active_only=True) -> list[dict]:
        await self._ts.connect()
        async with self._ts._pool.acquire() as conn:
            query = "SELECT * FROM field_patterns WHERE tenant_id = $1 AND parcel_id = $2"
            if active_only:
                query += " AND is_active = true"
            query += " ORDER BY updated_at DESC LIMIT 50"
            rows = await conn.fetch(query, tenant_id, parcel_id)
            return [_row_to_dict(r) for r in rows]

    async def get(self, tenant_id, pattern_id) -> dict | None:
        await self._ts.connect()
        async with self._ts._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM field_patterns WHERE tenant_id = $1 AND id = $2",
                tenant_id, pattern_id,
            )
            return _row_to_dict(row) if row else None

    async def delete(self, tenant_id, pattern_id) -> bool:
        await self._ts.connect()
        async with self._ts._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE field_patterns SET is_active = false, updated_at = $3 "
                "WHERE tenant_id = $1 AND id = $2",
                tenant_id, pattern_id, int(time.time() * 1000),
            )
            return result != "UPDATE 0"


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["id"] = str(d["id"])
    if d.get("pattern_config") and isinstance(d["pattern_config"], str):
        d["pattern_config"] = json.loads(d["pattern_config"])
    if d.get("vra_prescription_map") and isinstance(d["vra_prescription_map"], str):
        d["vra_prescription_map"] = json.loads(d["vra_prescription_map"])
    for ts_field in ("created_at", "updated_at"):
        if ts_field in d and d[ts_field] is not None:
            d[ts_field] = int(d[ts_field])
    return d
