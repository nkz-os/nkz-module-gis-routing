# backend/app/services/operation_store.py
"""Orion-LD AgriParcelOperation store: reads/writes + pure shape mappers.

Operations (route history) and templates are the same NGSI-LD entity type,
distinguished by the `isTemplate` Property. The desktop reads these directly
from Orion (the source of truth); the mobile sync mirror is unrelated.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Optional

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
