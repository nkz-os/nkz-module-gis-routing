"""
WatermelonDB-compatible sync protocol implementation.

Provides pull (delta download) and push (delta upload + conflict detection)
operations that bridge the mobile WatermelonDB layer with the server-side
NGSI-LD entities via Orion-LD and TimescaleDB materialized sync tables.
"""

import time
import logging
from app.services.timescale_client import TimescaleDBClient
from app.services.orion_client import OrionLDClient

logger = logging.getLogger(__name__)

VALID_COLLECTIONS = {"parcels", "equipment", "operations"}
SUPPORTED_SCHEMA_VERSIONS = {3}


class SyncConflictError(Exception):
    """Raised when the client timestamp is behind the server timestamp,
    indicating that a pull must be performed before another push."""

    def __init__(self, message: str, server_timestamp: int):
        super().__init__(message)
        self.server_timestamp = server_timestamp


class SyncService:
    """WatermelonDB-compatible sync service.

    Uses TimescaleDB materialized sync tables for pull (delta query)
    and Orion-LD for push (create/update/delete entities).

    The protocol is:
        1. Client calls ``pull()`` with ``last_pulled_at`` (epoch ms).
        2. Client calls ``push()`` with local changes.
        3. If the client timestamp is stale, ``SyncConflictError`` is raised
           and the client must pull again before pushing.
    """

    def __init__(self, timescale: TimescaleDBClient, orion: OrionLDClient):
        self._ts = timescale
        self._orion = orion
        self._server_timestamps: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _now_ms(self) -> int:
        """Current time in epoch milliseconds."""
        return int(time.time() * 1000)

    def _validate_collections(self, collections: list[str]):
        """Raise ValueError if any collection is not in VALID_COLLECTIONS."""
        invalid = set(collections) - VALID_COLLECTIONS
        if invalid:
            raise ValueError(f"INVALID_COLLECTION: {', '.join(sorted(invalid))}")

    def _validate_schema(self, schema_version: int):
        """Raise ValueError if the schema version is not supported."""
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"INVALID_SCHEMA: version {schema_version} not supported. "
                f"Supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )

    # ------------------------------------------------------------------
    # Pull  --  client downloads changes
    # ------------------------------------------------------------------

    async def pull(
        self,
        collections: list[str],
        tenant_id: str,
        last_pulled_at: int,
        schema_version: int,
    ) -> dict:
        """Return changes newer than *last_pulled_at* for each collection.

        Returns
            ``{"changes": {col: {created, updated, deleted}}, "timestamp": int}``
        """
        self._validate_collections(collections)
        self._validate_schema(schema_version)

        changes = {}
        for col in collections:
            changes[col] = await self._ts.get_changes(col, tenant_id, last_pulled_at)

        now = self._now_ms()
        self._server_timestamps[tenant_id] = now
        return {"changes": changes, "timestamp": now}

    # ------------------------------------------------------------------
    # Push  --  client uploads changes
    # ------------------------------------------------------------------

    async def push(
        self,
        collections: list[str],
        tenant_id: str,
        changes: dict,
        last_pulled_at: int,
    ) -> dict:
        """Apply client changes to Orion-LD entities.

        *last_pulled_at* is compared against the stored server timestamp to
        detect stale clients.  If stale, ``SyncConflictError`` is raised.

        Returns
            ``{"changes": {col: {created, updated, deleted}}, "timestamp": int}``
        """
        self._validate_collections(collections)

        # Conflict detection
        server_ts = self._server_timestamps.get(tenant_id, 0)
        if last_pulled_at < server_ts:
            raise SyncConflictError(
                f"Client timestamp {last_pulled_at} is behind server "
                f"timestamp {server_ts}. Pull first.",
                server_timestamp=server_ts,
            )

        result_changes = {}
        for col in collections:
            col_changes = changes.get(col, {})
            created_remote: list[dict] = []
            deleted_ids: list[str] = []

            for record in col_changes.get("created", []):
                remote_id = await self._create_in_orion(col, record, tenant_id)
                created_remote.append({**record, "remote_id": remote_id})
                deleted_ids.append(record.get("id", ""))

            for record in col_changes.get("updated", []):
                await self._update_in_orion(col, record, tenant_id)

            for record_id in col_changes.get("deleted", []):
                await self._delete_in_orion(col, record_id, tenant_id)

            result_changes[col] = {
                "created": created_remote,
                "updated": [],
                "deleted": deleted_ids,
            }

        now = self._now_ms()
        self._server_timestamps[tenant_id] = now
        return {"changes": result_changes, "timestamp": now}

    # ------------------------------------------------------------------
    # Orion-LD delegate methods
    # ------------------------------------------------------------------

    async def _create_in_orion(self, collection: str, record: dict, tenant_id: str) -> str:
        """Create a new NGSI-LD entity from a client record and return its ID."""
        entity = self._to_ngsild(collection, record, tenant_id)
        entity_id = await self._orion.create_entity(entity, tenant_id)
        return entity_id

    async def _update_in_orion(self, collection: str, record: dict, tenant_id: str):
        """Update an existing NGSI-LD entity from a client record."""
        remote_id = record.get("remote_id")
        if not remote_id:
            return
        attrs = self._to_ngsild_attrs(collection, record)
        await self._orion.patch_entity(remote_id, attrs, tenant_id)

    async def _delete_in_orion(self, collection: str, record_id: str, tenant_id: str):
        """Delete an NGSI-LD entity."""
        await self._orion.delete_entity(record_id, tenant_id)

    # ------------------------------------------------------------------
    # NGSI-LD payload builders
    # ------------------------------------------------------------------

    def _to_ngsild(self, collection: str, record: dict, tenant_id: str) -> dict:
        """Build a full NGSI-LD entity payload from a client record."""
        import json as _json
        import uuid as _uuid

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if collection == "parcels":
            return {
                "id": (
                    f"urn:ngsi-ld:AgriParcel:{tenant_id}:"
                    f"{record.get('id', _uuid.uuid4().hex)[:8]}"
                ),
                "type": "AgriParcel",
                "name": {"type": "Property", "value": record.get("name", "")},
                "location": {
                    "type": "GeoProperty",
                    "value": _parse_json(record.get("geojson", "{}")),
                },
                "area": {
                    "type": "Property",
                    "value": record.get("area", 0),
                    "unitCode": "HAR",
                },
                "category": {
                    "type": "Property",
                    "value": record.get("crop_type", ""),
                },
                "cropStatus": {
                    "type": "Property",
                    "value": record.get("status", "active"),
                },
                "dateModified": {
                    "type": "Property",
                    "value": {"@type": "DateTime", "@value": now_iso},
                },
            }

        elif collection == "equipment":
            etype = (
                "AgriculturalTractor"
                if record.get("equipment_type") == "tractor"
                else "AgriculturalImplement"
            )
            return {
                "id": (
                    f"urn:ngsi-ld:{etype}:{tenant_id}:"
                    f"{record.get('id', '')[:8]}"
                ),
                "type": etype,
                "name": {"type": "Property", "value": record.get("name", "")},
                "implementWidth": {
                    "type": "Property",
                    "value": record.get("implement_width", 3.0),
                },
                "status": {
                    "type": "Property",
                    "value": record.get("status", "available"),
                },
                "steeringType": {
                    "type": "Property",
                    "value": record.get("steering_type", "ackermann"),
                },
                "steeringAxles": {
                    "type": "Property",
                    "value": record.get("steering_axles", "front"),
                },
                "trackWidth": {
                    "type": "Property",
                    "value": record.get("track_width", 0),
                },
                "wheelbase": {
                    "type": "Property",
                    "value": record.get("wheelbase", 0),
                },
                "gpsOffsetX": {
                    "type": "Property",
                    "value": record.get("gps_offset_x", 0),
                },
                "gpsOffsetY": {
                    "type": "Property",
                    "value": record.get("gps_offset_y", 0),
                },
                "gpsOffsetZ": {
                    "type": "Property",
                    "value": record.get("gps_offset_z", 0),
                },
                "hitchType": {
                    "type": "Property",
                    "value": record.get("hitch_type", "none"),
                },
                "hitchOffsetX": {
                    "type": "Property",
                    "value": record.get("hitch_offset_x", 0),
                },
                "implementLength": {
                    "type": "Property",
                    "value": record.get("implement_length", 0),
                },
                "implementOffsetX": {
                    "type": "Property",
                    "value": record.get("implement_offset_x", 0),
                },
                "dateModified": {
                    "type": "Property",
                    "value": {"@type": "DateTime", "@value": now_iso},
                },
            }

        else:  # operations
            return {
                "id": (
                    f"urn:ngsi-ld:AgriParcelOperation:{tenant_id}:"
                    f"{record.get('id', '')[:8]}"
                ),
                "type": "AgriParcelOperation",
                "name": {
                    "type": "Property",
                    "value": (
                        f"{record.get('operation_type', '')} - "
                        f"{record.get('id', '')[:8]}"
                    ),
                },
                "operationType": {
                    "type": "Property",
                    "value": record.get("operation_type", ""),
                },
                "status": {
                    "type": "Property",
                    "value": record.get("status", "planned"),
                },
                "location": {
                    "type": "GeoProperty",
                    "value": _parse_json(record.get("ab_line_geojson", "{}")),
                },
                "dateModified": {
                    "type": "Property",
                    "value": {"@type": "DateTime", "@value": now_iso},
                },
            }

    def _to_ngsild_attrs(self, collection: str, record: dict) -> dict:
        """Build a partial NGSI-LD attribute fragment for PATCH operations."""
        if collection == "parcels":
            return {
                "name": {"type": "Property", "value": record.get("name")},
                "status": {"type": "Property", "value": record.get("status")},
            }
        elif collection == "equipment":
            return {
                "name": {"type": "Property", "value": record.get("name")},
                "status": {"type": "Property", "value": record.get("status")},
                "implementWidth": {
                    "type": "Property",
                    "value": record.get("implement_width"),
                },
            }
        else:  # operations
            return {
                "status": {
                    "type": "Property",
                    "value": record.get("status", "planned"),
                },
            }


def _parse_json(s: str) -> dict:
    """Safely parse a JSON string, returning {} on failure."""
    import json as _json

    try:
        return _json.loads(s)
    except (_json.JSONDecodeError, TypeError):
        return {}
