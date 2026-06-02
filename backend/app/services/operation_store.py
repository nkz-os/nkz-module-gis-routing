# backend/app/services/operation_store.py
"""Orion-LD AgriParcelOperation store: reads/writes + pure shape mappers.

Operations (route history) and templates are the same NGSI-LD entity type,
distinguished by the `isTemplate` Property. The desktop reads these directly
from Orion (the source of truth); the mobile sync mirror is unrelated.
"""
from __future__ import annotations

import calendar
import json
import time
import uuid
from typing import Optional

from shapely.geometry import mapping

from app.services.orion_client import OrionLDClient


# ----- pure helpers ---------------------------------------------------------

def _prop(entity: dict, name: str, default=None):
    node = entity.get(name)
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return default


def _rel(entity: dict, name: str) -> Optional[str]:
    node = entity.get(name)
    if isinstance(node, dict):
        return node.get("object")
    return None


def _iso_to_epoch_s(node) -> Optional[int]:
    """Convert a NGSI-LD DateTime value ({"@value": "YYYY-MM-DDTHH:MM:SSZ"}) to epoch seconds."""
    if isinstance(node, dict):
        node = node.get("@value")
    if not isinstance(node, str):
        return None
    try:
        return calendar.timegm(time.strptime(node, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, TypeError):
        return None


def is_template_entity(entity: dict) -> bool:
    return _prop(entity, "isTemplate", False) is True


def operation_to_row(entity: dict) -> dict:
    """Lightweight history row: metadata + honest metrics, NO geometry."""
    return {
        "id": entity.get("id"),
        "parcel_id": _rel(entity, "refAgriParcel"),
        "operation_type": _prop(entity, "operationType"),
        "status": _prop(entity, "status"),
        "swath_count": _prop(entity, "swathCount"),
        "field_efficiency": _prop(entity, "fieldEfficiency"),
        "worked_distance_m": _prop(entity, "workedDistance"),
        "non_working_distance_m": _prop(entity, "nonWorkingDistance"),
        "covered_area_ha": _prop(entity, "coveredAreaHa"),
        "total_distance_m": _prop(entity, "totalDistanceM"),
        "date_created": _prop(entity, "dateCreated"),
    }


def operation_to_detail(entity: dict) -> dict:
    """Full detail incl. geometry + the inputs needed to re-run."""
    row = operation_to_row(entity)
    row["route"] = _prop(entity, "location")
    row["generation_config"] = _prop(entity, "generationConfig")
    row["vra_config"] = _prop(entity, "vraConfig")
    row["prescription_map"] = _prop(entity, "prescriptionMap")
    row["tractor_id"] = _rel(entity, "refTractor")
    row["implement_id"] = _rel(entity, "refImplement")
    row["source_operation_id"] = _rel(entity, "refSourceOperation")
    return row


# ----- entity builders -------------------------------------------------------

def _now_iso() -> dict:
    return {"@type": "DateTime", "@value": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def new_operation_id(tenant_id: str) -> str:
    return f"urn:ngsi-ld:AgriParcelOperation:{tenant_id}:{uuid.uuid4().hex[:8]}"


def build_operation_entity(*, op_id, body, result, prescription_map, is_template=False) -> dict:
    """Build an AgriParcelOperation NGSI-LD entity from a generation result."""
    pc = body.pattern_config
    metrics = getattr(result, "metrics", {}) or {}
    entity = {
        "id": op_id,
        "type": "AgriParcelOperation",
        "name": {"type": "Property",
                 "value": f"{body.operation_type} - {(body.parcel_id or 'op')[:8]}"},
        "operationType": {"type": "Property", "value": body.operation_type},
        "couplingModel": {"type": "Property", "value": body.coupling_model},
        "status": {"type": "Property", "value": "planned"},
        "location": {"type": "GeoProperty", "value": mapping(result.geometry)},
        "swathCount": {"type": "Property", "value": result.swath_count},
        "totalDistanceM": {"type": "Property", "value": result.total_distance_m},
        "fieldEfficiency": {"type": "Property", "value": metrics.get("field_efficiency")},
        "workedDistance": {"type": "Property", "value": metrics.get("worked_distance_m")},
        "nonWorkingDistance": {"type": "Property", "value": metrics.get("non_working_distance_m")},
        "coveredAreaHa": {"type": "Property", "value": metrics.get("covered_area_ha")},
        "isTemplate": {"type": "Property", "value": is_template},
        "dateCreated": {"type": "Property", "value": _now_iso()},
        "generationConfig": {"type": "Property", "value": {
            "pattern": body.pattern,
            "heading_deg": pc.heading_deg,
            "width_m": pc.width_m,
            "overlap_pct": pc.overlap_pct,
            "headland_passes": pc.headland_passes,
            "direction": pc.direction,
            "heading_objective": pc.heading_objective,
            "turning_radius_m": pc.turning_radius_m,
        }},
        "refAgriParcel": {"type": "Relationship", "object": body.parcel_id},
    }
    if body.tractor_id:
        entity["refTractor"] = {"type": "Relationship", "object": body.tractor_id}
    if body.implement_id:
        entity["refImplement"] = {"type": "Relationship", "object": body.implement_id}
    if body.vra is not None:
        entity["vraConfig"] = {"type": "Property", "value": {
            "enabled": body.vra.enabled,
            "source": body.vra.source,
            "base_rate": body.vra.base_rate,
            "rate_unit": body.vra.rate_unit,
            "zone_ids": body.vra.zone_ids,
        }}
    if prescription_map:
        entity["prescriptionMap"] = {"type": "Property", "value": prescription_map}
    return entity


def build_template_entity(*, op_id, parcel_id, name, pattern_type, pattern_config,
                          route_geojson, vra_prescription_map,
                          equipment_tractor_id, equipment_implement_id,
                          source_operation_id) -> dict:
    """Build an isTemplate=true AgriParcelOperation from the frontend save body."""
    entity = {
        "id": op_id,
        "type": "AgriParcelOperation",
        "name": {"type": "Property", "value": name},
        "patternType": {"type": "Property", "value": pattern_type},
        "status": {"type": "Property", "value": "planned"},
        "isTemplate": {"type": "Property", "value": True},
        "dateCreated": {"type": "Property", "value": _now_iso()},
        "generationConfig": {"type": "Property", "value": pattern_config},
        "location": {"type": "GeoProperty", "value": json.loads(route_geojson)},
        "refAgriParcel": {"type": "Relationship", "object": parcel_id},
    }
    if vra_prescription_map:
        entity["prescriptionMap"] = {"type": "Property", "value": vra_prescription_map}
    if equipment_tractor_id:
        entity["refTractor"] = {"type": "Relationship", "object": equipment_tractor_id}
    if equipment_implement_id:
        entity["refImplement"] = {"type": "Relationship", "object": equipment_implement_id}
    if source_operation_id:
        entity["refSourceOperation"] = {"type": "Relationship", "object": source_operation_id}
    return entity


def template_to_dict(entity: dict) -> dict:
    """Map an isTemplate entity back to the legacy field_patterns dict shape."""
    loc = _prop(entity, "location")
    return {
        "id": entity.get("id"),
        "parcel_id": _rel(entity, "refAgriParcel"),
        "name": _prop(entity, "name"),
        "pattern_type": _prop(entity, "patternType"),
        "pattern_config": _prop(entity, "generationConfig"),
        "route_geojson": json.dumps(loc) if loc is not None else None,
        "vra_prescription_map": _prop(entity, "prescriptionMap"),
        "equipment_tractor_id": _rel(entity, "refTractor"),
        "equipment_implement_id": _rel(entity, "refImplement"),
        "source_operation_id": _rel(entity, "refSourceOperation"),
        "created_at": _iso_to_epoch_s(_prop(entity, "dateCreated")),
    }


# ----- async store readers ---------------------------------------------------

def _matches_parcel(entity: dict, parcel_id: Optional[str]) -> bool:
    if not parcel_id:
        return True
    return _rel(entity, "refAgriParcel") == parcel_id


async def list_operations(orion: OrionLDClient, tenant_id: str,
                          parcel_id: Optional[str] = None, limit: int = 20) -> list[dict]:
    entities = await orion.query_entities("AgriParcelOperation", tenant_id)
    rows = [operation_to_row(e) for e in entities
            if not is_template_entity(e) and _matches_parcel(e, parcel_id)]
    return rows[:limit]


async def list_templates(orion: OrionLDClient, tenant_id: str, parcel_id: str) -> list[dict]:
    entities = await orion.query_entities("AgriParcelOperation", tenant_id)
    return [template_to_dict(e) for e in entities
            if is_template_entity(e) and _matches_parcel(e, parcel_id)]


async def get_operation(orion: OrionLDClient, operation_id: str, tenant_id: str) -> Optional[dict]:
    entity = await orion.get_entity(operation_id, tenant_id)
    return operation_to_detail(entity) if entity else None
