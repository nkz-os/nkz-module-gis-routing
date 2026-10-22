"""
Orion-LD subscriptions feeding the notify materializer, registered by the module itself.

Registration used to be a manual script. When the notify auth header changed,
nobody re-ran it: the live subscriptions kept sending the old header, every
notification was rejected, and Orion paused them. The declaration now lives
here and the SDK registrar converges the broker onto it — at startup, on every
heal cycle and on the install hint (/internal/lifecycle). Where the module is
installed comes from the platform (SDK reconcile_installations), not from a
query of our own: create where enabled, remove ours where not, and touch
nothing when the platform cannot answer.
"""

import asyncio
import logging
import os

from nkz_platform_sdk.notify_auth import derived_tokens_from_env
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
        # The registrar owns the receiver auth header: the master secret (legacy) or,
        # with NKZ_NOTIFY_DERIVED_TOKENS on, a token bound to the tenant and this
        # receiver so the broker never stores the master.
        internal_secret=secret,
        derived_tokens=derived_tokens_from_env(),
    )


_registrar: SubscriptionRegistrar | None = None


def get_registrar() -> SubscriptionRegistrar | None:
    """One registrar per process: its lock serializes heal and lifecycle hints."""
    global _registrar
    if _registrar is None:
        _registrar = build_registrar()
    return _registrar


async def reconcile_once(registrar: SubscriptionRegistrar | None = None) -> dict | None:
    """One reconciliation pass. Never raises; None without a registrar."""
    registrar = registrar or get_registrar()
    if registrar is None:
        return None
    result = await registrar.reconcile_installations(get_settings().module_id)
    if "skipped" in result:
        logger.warning("Subscription reconcile skipped: %s", result.get("reason"))
        return result
    ensured, removed = result["ensured"], result["removed"]
    logger.info(
        "Subscriptions reconciled: created=%d converged=%d removed=%d errors=%d",
        ensured["created"], ensured.get("converged", 0), removed["removed"],
        len(ensured["errors"]) + len(removed["errors"]),
    )
    for error in ensured["errors"] + removed["errors"]:
        logger.warning("Subscription reconcile error: %s", error)
    return result


async def run_subscription_reconciler(interval_minutes: int) -> None:
    """Reconcile now, then every `interval_minutes`. Never raises."""
    registrar = get_registrar()
    if registrar is None:
        return
    try:
        await reconcile_once(registrar)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Initial subscription reconcile failed: %s", exc)
    await registrar.periodic_reconcile(get_settings().module_id, interval_minutes)
