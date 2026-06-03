"""Sync Orion-LD entities into TimescaleDB materialized cache."""
import json
import logging
from datetime import datetime, timezone
from app.services.orion_client import OrionLDClient
from app.services.timescale_client import TimescaleDBClient

logger = logging.getLogger(__name__)


async def materialize_parcels(orion: OrionLDClient, ts: TimescaleDBClient, tenant_id: str):
    """Fetch AgriParcel entities from Orion-LD and upsert into sync_parcels."""
    entities = await orion.query_entities("AgriParcel", tenant_id)
    for e in entities:
        location = e.get("location", {}).get("value", {})
        geojson_str = json.dumps(location) if location else "{}"
        coords = location.get("coordinates", [[[0, 0]]]) if location else [[[0, 0]]]
        # Handle Polygon (ring of rings) vs MultiPolygon (array of rings)
        if coords and isinstance(coords[0], list) and isinstance(coords[0][0], list):
            centroid = coords[0][0] if coords[0] else [0, 0]
        else:
            centroid = [0, 0]
        name = str(e.get("name", {}).get("value", e["id"]))
        area = float(e.get("area", {}).get("value", 0))
        crop_type = str(e.get("category", {}).get("value", ""))
        status_val = str(e.get("cropStatus", {}).get("value", "active"))
        status = "active" if status_val in ("growing", "active") else "fallow"
        updated_at = _parse_datetime_attr(e, "modifiedAt") or _parse_datetime_attr(e, "dateModified") or 0
        access_point = e.get("accessPoint", {}).get("value")
        exclusion_zones = e.get("exclusionZones", {}).get("value")
        access_point_str = json.dumps(access_point) if access_point else None
        exclusion_zones_str = json.dumps(exclusion_zones) if exclusion_zones else None
        await ts.materialize_parcel(
            remote_id=e["id"], tenant_id=tenant_id, name=name, geojson=geojson_str,
            area=area, crop_type=crop_type, status=status,
            centroid_lat=float(centroid[1]) if len(centroid) > 1 else 0,
            centroid_lng=float(centroid[0]), updated_at=updated_at,
            access_point=access_point_str, exclusion_zones=exclusion_zones_str)


async def materialize_equipment_entities(orion: OrionLDClient, ts: TimescaleDBClient, tenant_id: str):
    """Fetch ManufacturingMachine entities from Orion-LD (category differentiates tractor vs implement)."""
    entities = await orion.query_entities("ManufacturingMachine", tenant_id)
    for e in entities:
        name = str(e.get("name", {}).get("value", e["id"]))
        category = str(e.get("category", {}).get("value", "tractor"))
        eq_type = "tractor" if category == "tractor" else "implement"
        width = float(e.get("implementWidth", {}).get("value", 0)
                      or e.get("workingWidth", {}).get("value", 0)
                      or e.get("width", {}).get("value", 3.0))
        steering = str(e.get("steeringType", {}).get("value", "ackermann"))
        axles = str(e.get("steeringAxles", {}).get("value", "front"))
        gps_x = float(e.get("gpsOffsetX", {}).get("value", 0))
        gps_y = float(e.get("gpsOffsetY", {}).get("value", 0))
        gps_z = float(e.get("gpsOffsetZ", {}).get("value", 0))
        hitch = str(e.get("hitchType", {}).get("value", "none"))
        hitch_ox = float(e.get("hitchOffsetX", {}).get("value", 0))
        impl_len = float(e.get("implementLength", {}).get("value", 0))
        impl_ox = float(e.get("implementOffsetX", {}).get("value", 0))
        track_w = float(e.get("trackWidth", {}).get("value", 0))
        wb = float(e.get("wheelbase", {}).get("value", 0))
        status = str(e.get("status", {}).get("value", "available"))
        updated_at = _parse_datetime_attr(e, "modifiedAt") or _parse_datetime_attr(e, "dateModified") or 0
        await ts.materialize_equipment(
            remote_id=e["id"], tenant_id=tenant_id, name=name, equipment_type=eq_type,
            implement_width=max(width, 1.0), status=status, steering_type=steering,
            steering_axles=axles, track_width=track_w, wheelbase=wb,
            gps_offset_x=gps_x, gps_offset_y=gps_y, gps_offset_z=gps_z,
            hitch_type=hitch, hitch_offset_x=hitch_ox, implement_length=impl_len,
            implement_offset_x=impl_ox, updated_at=updated_at)


def _parse_datetime_attr(entity: dict, attr_name: str) -> int:
    """Parse NGSI-LD DateTime attribute into epoch millis."""
    attr = entity.get(attr_name, {})
    if not attr: return 0
    value = attr.get("value", "")
    if isinstance(value, dict): value = value.get("@value", "")
    if not value: return 0
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0
