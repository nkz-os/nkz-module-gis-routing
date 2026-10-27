"""Shared: read ManufacturingMachine kinematics from Orion."""
from app.config import get_settings
from nkz_platform_sdk.orion import OrionClient

_KEYS = ("implementWidth", "trackWidth", "minTurningRadius", "steeringType")


async def fetch_machine_kinematics(machine_id: str, tenant_id: str) -> dict:
    """Return the kinematic attributes present on the machine; {} if it does not exist."""
    settings = get_settings()
    orion = OrionClient(
        tenant_id,
        base_url=settings.context_broker_url,
        context_url=settings.ngsi_ld_context,
    )
    try:
        entity = await orion.get_entity(machine_id)
    finally:
        await orion.close()
    if not entity:
        return {}
    return {k: (entity.get(k, {}) or {}).get("value") for k in _KEYS
            if entity.get(k) is not None}
