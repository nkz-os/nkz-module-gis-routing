"""
Tests for TimescaleDBClient -- asyncpg-based sync materialisation.

Covers pool lifecycle, UPSERT materialisation methods, and the
``get_changes`` delta query contract.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.timescale_client import TimescaleDBClient


@pytest.fixture
def ts_client():
    """TimescaleDBClient fixture with a throw-away DSN."""
    return TimescaleDBClient(dsn="postgresql://test:test@localhost:5432/testdb")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _connect(ts_client) -> AsyncMock:
    """Attach a mock pool with a mock connection to *ts_client* and
    return the mock connection.

    The pool is a ``MagicMock`` (not ``AsyncMock``) because
    ``pool.acquire()`` is used as ``async with pool.acquire() as conn:``
    — the ``acquire()`` call itself is synchronous and returns an async
    context manager.  ``AsyncMock`` methods return coroutines instead,
    which would break the ``async with`` protocol.
    """
    mock_conn = AsyncMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    ts_client._pool = mock_pool
    return mock_conn


def _row(**kwargs) -> dict:
    """Build a dict that can double as an asyncpg.Record (dict(row) works)."""
    return dict(kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTimescaleDBClient:
    """TimescaleDBClient unit tests."""

    @pytest.mark.asyncio
    async def test_materialize_parcel_calls_execute(self, ts_client):
        """materialize_parcel must call conn.execute with the UPSERT SQL."""
        mock_conn = _connect(ts_client)
        await ts_client.materialize_parcel(
            remote_id="urn:ngsi-ld:AgriParcel:test:1",
            tenant_id="test",
            name="P1",
            geojson="{}",
            area=10.0,
            crop_type="wheat",
            status="active",
            centroid_lat=42.0,
            centroid_lng=-1.0,
            updated_at=1000,
        )
        assert mock_conn.execute.called
        sql = mock_conn.execute.call_args[0][0]
        assert "INSERT INTO sync_parcels" in sql
        assert "ON CONFLICT" in sql

    @pytest.mark.asyncio
    async def test_materialize_equipment_calls_execute(self, ts_client):
        """materialize_equipment must call conn.execute with equipment UPSERT."""
        mock_conn = _connect(ts_client)
        await ts_client.materialize_equipment(
            remote_id="urn:ngsi-ld:AgriEquipment:test:1",
            tenant_id="test",
            name="Tractor-1",
            equipment_type="tractor",
            implement_width=3.0,
            status="available",
            steering_type="ackermann",
            steering_axles="front",
            track_width=1.8,
            wheelbase=2.7,
            gps_offset_x=0.0,
            gps_offset_y=0.0,
            gps_offset_z=0.0,
            hitch_type="three_point",
            hitch_offset_x=0.5,
            implement_length=2.0,
            implement_offset_x=0.0,
            updated_at=1000,
        )
        assert mock_conn.execute.called
        sql = mock_conn.execute.call_args[0][0]
        assert "INSERT INTO sync_equipment" in sql
        assert "ON CONFLICT" in sql

    @pytest.mark.asyncio
    async def test_materialize_operation_calls_execute(self, ts_client):
        """materialize_operation must call conn.execute with operation UPSERT."""
        mock_conn = _connect(ts_client)
        await ts_client.materialize_operation(
            remote_id="urn:ngsi-ld:AgriOperation:test:1",
            tenant_id="test",
            parcel_id="urn:ngsi-ld:AgriParcel:test:1",
            equipment_id="urn:ngsi-ld:AgriEquipment:test:1",
            tractor_id="urn:ngsi-ld:AgriEquipment:test:1",
            implement_id=None,
            operation_type="spraying",
            ab_line_geojson='{"type":"LineString","coordinates":[]}',
            implement_width=24.0,
            status="in_progress",
            vra_enabled=True,
            prescription_map="prescription_001",
            base_rate=150.0,
            rate_unit="l/ha",
            started_at=1000,
            completed_at=None,
            updated_at=1000,
        )
        assert mock_conn.execute.called
        sql = mock_conn.execute.call_args[0][0]
        assert "INSERT INTO sync_operations" in sql
        assert "ON CONFLICT" in sql

    @pytest.mark.asyncio
    async def test_get_changes_unknown_collection_raises(self, ts_client):
        """get_changes must raise ValueError for unknown table names."""
        ts_client._pool = AsyncMock()
        with pytest.raises(ValueError, match="Unknown collection"):
            await ts_client.get_changes("invalid", "test", 0)

    @pytest.mark.asyncio
    async def test_get_changes_returns_delta(self, ts_client):
        """get_changes must return {created, updated, deleted} delta."""
        mock_conn = _connect(ts_client)

        mock_row = _row(
            id="a1b2c3d4-e5f6-4789-abcd-ef1234567890",
            remote_id="urn:test",
            tenant_id="test",
            name="P1",
            geojson="{}",
            area=10.5,
            crop_type="wheat",
            status="active",
            centroid_lat=42.0,
            centroid_lng=-1.0,
            created_at=1000,
            updated_at=1000,
            _change_type="created",
        )
        mock_conn.fetch = AsyncMock(return_value=[mock_row])

        result = await ts_client.get_changes("parcels", "test", 0)

        assert "created" in result
        assert "updated" in result
        assert "deleted" in result
        assert len(result["created"]) >= 1
        created = result["created"][0]
        assert created["remote_id"] == "urn:test"
        assert created["area"] == 10.5
        assert created["id"] == "a1b2c3d4-e5f6-4789-abcd-ef1234567890"

    @pytest.mark.asyncio
    async def test_get_changes_distinguishes_created_from_updated(self, ts_client):
        """get_changes must separate 'created' and 'updated' records."""
        mock_conn = _connect(ts_client)

        rows = [
            _row(
                id="00000000-0000-0000-0000-000000000001",
                remote_id="urn:created",
                tenant_id="test",
                name="Created",
                geojson="{}", area=1.0, crop_type=None, status="active",
                centroid_lat=None, centroid_lng=None,
                created_at=2000, updated_at=2000,
                _change_type="created",
            ),
            _row(
                id="00000000-0000-0000-0000-000000000002",
                remote_id="urn:updated",
                tenant_id="test",
                name="Updated",
                geojson="{}", area=2.0, crop_type=None, status="active",
                centroid_lat=None, centroid_lng=None,
                created_at=1000, updated_at=2000,
                _change_type="updated",
            ),
        ]
        mock_conn.fetch = AsyncMock(return_value=rows)

        result = await ts_client.get_changes("parcels", "test", 0, limit=100)

        assert len(result["created"]) == 1
        assert len(result["updated"]) == 1
        assert result["created"][0]["remote_id"] == "urn:created"
        assert result["updated"][0]["remote_id"] == "urn:updated"

    @pytest.mark.asyncio
    async def test_connect_creates_pool_and_runs_ddl(self, ts_client):
        """connect() must create the pool and execute DDL."""
        with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_conn = AsyncMock()
            mock_pool_instance = MagicMock()
            mock_pool_instance.acquire.return_value.__aenter__.return_value = mock_conn
            mock_create.return_value = mock_pool_instance

            await ts_client.connect()
            mock_create.assert_awaited_once()
            mock_conn.execute.assert_awaited_once()
            sql = mock_conn.execute.call_args[0][0]
            assert "CREATE TABLE IF NOT EXISTS sync_parcels" in sql

    @pytest.mark.asyncio
    async def test_connect_is_idempotent(self, ts_client):
        """connect() must be a no-op when pool already exists."""
        ts_client._pool = MagicMock()
        with patch("asyncpg.create_pool") as mock_create:
            await ts_client.connect()
            mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_cleans_up_pool(self, ts_client):
        """close() must clean up the pool."""
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        ts_client._pool = mock_pool
        await ts_client.close()
        mock_pool.close.assert_awaited_once()
        assert ts_client._pool is None
