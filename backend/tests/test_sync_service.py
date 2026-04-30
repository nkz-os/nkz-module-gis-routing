"""
Tests for SyncService -- WatermelonDB-compatible sync protocol.

Covers pull (delta download), push (delta upload), collection/schema
validation, and stale-client conflict detection.
"""

import pytest
from unittest.mock import AsyncMock

from app.services.sync_service import SyncService, SyncConflictError


@pytest.fixture
def sync_svc():
    """SyncService fixture with mocked TimescaleDB and Orion-LD clients."""
    ts = AsyncMock()
    ts.get_changes.return_value = {"created": [], "updated": [], "deleted": []}
    orion = AsyncMock()
    orion.create_entity.return_value = "urn:ngsi-ld:Test:new-entity"
    return SyncService(timescale=ts, orion=orion)


class TestSyncServicePull:
    """Pull operation tests."""

    @pytest.mark.asyncio
    async def test_pull_initial_sync_returns_all_collections(self, sync_svc):
        """pull() with last_pulled_at=0 must return all 3 collections."""
        result = await sync_svc.pull(
            ["parcels", "equipment", "operations"], "test", 0, 3
        )
        assert "changes" in result
        assert "timestamp" in result
        assert result["timestamp"] > 0
        for col in ["parcels", "equipment", "operations"]:
            assert col in result["changes"]

    @pytest.mark.asyncio
    async def test_pull_invalid_collection_raises(self, sync_svc):
        """An unknown collection name must raise ValueError."""
        with pytest.raises(ValueError, match="INVALID_COLLECTION"):
            await sync_svc.pull(["invalid"], "test", 0, 3)

    @pytest.mark.asyncio
    async def test_pull_unsupported_schema_raises(self, sync_svc):
        """An unsupported schema version must raise ValueError."""
        with pytest.raises(ValueError, match="INVALID_SCHEMA"):
            await sync_svc.pull(["parcels"], "test", 0, 99)

    @pytest.mark.asyncio
    async def test_pull_records_server_timestamp(self, sync_svc):
        """pull() must store and return a server timestamp per tenant."""
        assert "test" not in sync_svc._server_timestamps
        result = await sync_svc.pull(["parcels"], "test", 0, 3)
        assert sync_svc._server_timestamps["test"] == result["timestamp"]


class TestSyncServicePush:
    """Push operation tests."""

    @pytest.mark.asyncio
    async def test_push_stale_timestamp_raises_conflict(self, sync_svc):
        """A client timestamp behind the server must raise SyncConflictError."""
        sync_svc._server_timestamps["test"] = 1000
        with pytest.raises(SyncConflictError) as exc:
            await sync_svc.push(
                ["parcels"],
                "test",
                {"parcels": {"created": [], "updated": [], "deleted": []}},
                500,
            )
        assert exc.value.server_timestamp == 1000

    @pytest.mark.asyncio
    async def test_push_up_to_date_timestamp_succeeds(self, sync_svc):
        """A client timestamp at or after the server timestamp must succeed."""
        sync_svc._server_timestamps["test"] = 500
        result = await sync_svc.push(
            ["parcels"],
            "test",
            {"parcels": {"created": [], "updated": [], "deleted": []}},
            500,
        )
        assert "changes" in result
        assert result["timestamp"] >= 500

    @pytest.mark.asyncio
    async def test_push_creates_entities_in_orion(self, sync_svc):
        """push() with created records must call orion.create_entity."""
        result = await sync_svc.push(
            ["parcels"],
            "test",
            {
                "parcels": {
                    "created": [
                        {
                            "id": "loc1",
                            "name": "P1",
                            "geojson": "{}",
                            "area": 10,
                            "crop_type": "",
                            "status": "active",
                        }
                    ],
                    "updated": [],
                    "deleted": [],
                }
            },
            0,
        )
        assert sync_svc._orion.create_entity.called
        assert result["changes"]["parcels"]["deleted"] == ["loc1"]
        assert len(result["changes"]["parcels"]["created"]) == 1
        assert (
            result["changes"]["parcels"]["created"][0]["remote_id"]
            == "urn:ngsi-ld:Test:new-entity"
        )

    @pytest.mark.asyncio
    async def test_push_updates_entities_in_orion(self, sync_svc):
        """push() with updated records must call orion.patch_entity."""
        await sync_svc.push(
            ["parcels"],
            "test",
            {
                "parcels": {
                    "created": [],
                    "updated": [
                        {
                            "remote_id": "urn:ngsi-ld:AgriParcel:test:loc1",
                            "name": "P1-updated",
                            "status": "inactive",
                        }
                    ],
                    "deleted": [],
                }
            },
            0,
        )
        assert sync_svc._orion.patch_entity.called

    @pytest.mark.asyncio
    async def test_push_deletes_entities_in_orion(self, sync_svc):
        """push() with deleted records must call orion.delete_entity."""
        await sync_svc.push(
            ["parcels"],
            "test",
            {
                "parcels": {
                    "created": [],
                    "updated": [],
                    "deleted": ["urn:ngsi-ld:AgriParcel:test:loc1"],
                }
            },
            0,
        )
        assert sync_svc._orion.delete_entity.called

    @pytest.mark.asyncio
    async def test_push_creates_multiple_collections(self, sync_svc):
        """push() with multiple collections must handle each independently."""
        result = await sync_svc.push(
            ["parcels", "equipment"],
            "test",
            {
                "parcels": {
                    "created": [
                        {
                            "id": "p1",
                            "name": "Parcel-1",
                            "geojson": "{}",
                            "area": 10,
                            "crop_type": "wheat",
                            "status": "active",
                        }
                    ],
                    "updated": [],
                    "deleted": [],
                },
                "equipment": {
                    "created": [
                        {
                            "id": "t1",
                            "name": "Tractor-1",
                            "equipment_type": "tractor",
                            "implement_width": 3.0,
                            "status": "available",
                        }
                    ],
                    "updated": [],
                    "deleted": [],
                },
            },
            0,
        )
        assert sync_svc._orion.create_entity.call_count == 2
        assert "parcels" in result["changes"]
        assert "equipment" in result["changes"]

    @pytest.mark.asyncio
    async def test_push_invalid_collection_raises(self, sync_svc):
        """An unknown collection in push must raise ValueError."""
        with pytest.raises(ValueError, match="INVALID_COLLECTION"):
            await sync_svc.push(
                ["invalid"],
                "test",
                {"invalid": {"created": [], "updated": [], "deleted": []}},
                0,
            )

    @pytest.mark.asyncio
    async def test_push_updates_server_timestamp(self, sync_svc):
        """push() must record a new server timestamp after processing."""
        result = await sync_svc.push(
            ["parcels"],
            "test",
            {"parcels": {"created": [], "updated": [], "deleted": []}},
            0,
        )
        assert sync_svc._server_timestamps["test"] == result["timestamp"]
