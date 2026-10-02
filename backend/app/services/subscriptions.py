"""
Orion-LD subscriptions feeding the notify materializer, registered by the module itself.

Registration used to be a manual script. When the notify auth header changed,
nobody re-ran it: the live subscriptions kept sending the old header, every
notification was rejected, and Orion paused them. The declaration now lives
here and the SDK registrar converges the broker onto it — at startup and on
every heal cycle — only for tenants that have the module installed and enabled.
"""

import asyncio
import logging
import os

import asyncpg
from nkz_platform_sdk.subscriptions import SubscriptionRegistrar

from app.config import get_settings

logger = logging.getLogger(__name__)

# Exactly the types on_ngsild_notification materializes. A type the handler
# ignores would only deliver load.
ENTITY_TYPES = ("AgriParcel", "ManufacturingMachine", "AgriParcelOperation")
THROTTLING_SECONDS = 15

# Part of the subscription id (urn:ngsi-ld:Subscription:gis-routing:<Type>).
# Changing it orphans every existing subscription instead of converging it.
MODULE_NAME = "gis-routing"


async def installed_tenants() -> list[str]:
    """Tenants with this module installed and enabled.

    Never registers anywhere else: a subscription in a tenant without the
    module is notification load for nobody.
    """
    settings = get_settings()
    if not settings.database_url:
        logger.error("DATABASE_URL not set — cannot resolve tenants for subscriptions")
        return []
    conn = await asyncpg.connect(settings.database_url)
    try:
        rows = await conn.fetch(
            "SELECT DISTINCT tenant_id FROM tenant_installed_modules "
            "WHERE module_id = $1 AND is_enabled "
            "AND tenant_id IS NOT NULL AND tenant_id <> ''",
            settings.module_id,
        )
    finally:
        await conn.close()
    return sorted(r["tenant_id"] for r in rows)


def build_registrar() -> SubscriptionRegistrar | None:
    """The declared subscriptions, or None when they could not authenticate.

    Without the secret Orion would deliver notifications the notify endpoint
    rejects, and pause the subscriptions after three of them.
    """
    secret = os.getenv("INTERNAL_SERVICE_SECRET", "")
    if not secret:
        logger.error(
            "INTERNAL_SERVICE_SECRET not set — Orion subscriptions NOT registered; "
            "the notify materializer receives nothing"
        )
        return None
    settings = get_settings()
    return SubscriptionRegistrar(
        orion_url=settings.context_broker_url,
        notification_url=settings.notify_url,
        subscriptions=[
            {"type": entity_type, "throttling": THROTTLING_SECONDS}
            for entity_type in ENTITY_TYPES
        ],
        module_name=MODULE_NAME,
        context_url=settings.ngsi_ld_context or None,
        notification_headers={"X-Internal-Service-Secret": secret},
    )


async def reconcile_once(registrar: SubscriptionRegistrar) -> dict | None:
    """One reconciliation pass. Never raises; None when tenants could not be read."""
    try:
        tenants = await installed_tenants()
    except Exception as exc:  # noqa: BLE001 — a DB outage must not kill the service
        logger.warning("Subscription reconcile skipped, tenant lookup failed: %s", exc)
        return None
    result = await registrar.ensure_all(tenants)
    logger.info(
        "Subscriptions reconciled for %s: created=%d converged=%d errors=%d",
        tenants, result["created"], result.get("converged", 0), len(result["errors"]),
    )
    for error in result["errors"]:
        logger.warning("Subscription reconcile error: %s", error)
    return result


async def run_subscription_reconciler(interval_minutes: int) -> None:
    """Reconcile now, then every `interval_minutes`. Never raises."""
    registrar = build_registrar()
    if registrar is None:
        return
    try:
        await reconcile_once(registrar)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Initial subscription reconcile failed: %s", exc)
    await registrar.periodic_heal(installed_tenants, interval_minutes=interval_minutes)
