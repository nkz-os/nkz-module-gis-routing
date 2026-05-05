"""Coverage service — aggregates GPS telemetry into operation track lines."""
import json as _json
import logging

from app.services.timescale_client import TimescaleDBClient

logger = logging.getLogger(__name__)


class CoverageService:
    def __init__(self, timescale: TimescaleDBClient):
        self._ts = timescale

    async def get_operation_coverage(
        self, operation_id: str, tenant_id: str
    ) -> dict | None:
        try:
            row = await self._ts.fetchrow(
                """
                WITH pts AS (
                    SELECT (telemetry->>'lng')::float AS lng,
                           (telemetry->>'lat')::float AS lat,
                           (telemetry->>'timestamp')::bigint AS ts
                    FROM telemetry_events
                    WHERE tenant_id = $1 AND (telemetry->>'operation_id' = $2 OR $2 IS NULL)
                    ORDER BY ts ASC
                )
                SELECT ST_AsGeoJSON(ST_Multi(ST_MakeLine(ST_MakePoint(lng, lat) ORDER BY ts ASC))) AS coverage_geom
                FROM pts HAVING COUNT(*) >= 2
            """,
                tenant_id,
                operation_id,
            )
            if row and row["coverage_geom"]:
                return _json.loads(row["coverage_geom"])
        except Exception as e:
            logger.error("Coverage query failed: %s", e)
        return None
