"""
Tests for sync_parcels carrying accessPoint + exclusionZones offline.

Verifies that materialize_parcels extracts the GeoProperty/Property values
from AgriParcel entities and passes them as JSON strings to
timescale_client.materialize_parcel so they are persisted for offline use.
"""

import json
import pytest
from app.services import entity_sync


class _FakeTS:
    def __init__(self): self.calls = []
    async def materialize_parcel(self, **kw): self.calls.append(kw)


class _FakeOrion:
    async def query_entities(self, etype, tenant_id):
        return [{
            "id": "urn:ngsi-ld:AgriParcel:t1:p1", "type": "AgriParcel",
            "name": {"value": "P1"}, "area": {"value": 1.0},
            "location": {"value": {"type": "Polygon",
                                   "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}},
            "accessPoint": {"type": "GeoProperty",
                            "value": {"type": "Point", "coordinates": [0.5, 0.5]}},
            "exclusionZones": {"type": "Property",
                               "value": {"type": "FeatureCollection", "features": [1]}},
        }]


@pytest.mark.asyncio
async def test_materialize_carries_constraints():
    ts = _FakeTS()
    await entity_sync.materialize_parcels(_FakeOrion(), ts, "t1")
    kw = ts.calls[0]
    assert json.loads(kw["access_point"]) == {"type": "Point", "coordinates": [0.5, 0.5]}
    assert json.loads(kw["exclusion_zones"])["type"] == "FeatureCollection"


class _FakeOrionNoConstraints:
    async def query_entities(self, etype, tenant_id):
        return [{
            "id": "urn:ngsi-ld:AgriParcel:t1:p2", "type": "AgriParcel",
            "name": {"value": "P2"}, "area": {"value": 2.0},
            "location": {"value": {"type": "Polygon",
                                   "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}},
        }]


@pytest.mark.asyncio
async def test_materialize_without_constraints_passes_none():
    """Entities without accessPoint/exclusionZones must pass None for both."""
    ts = _FakeTS()
    await entity_sync.materialize_parcels(_FakeOrionNoConstraints(), ts, "t1")
    kw = ts.calls[0]
    assert kw["access_point"] is None
    assert kw["exclusion_zones"] is None
