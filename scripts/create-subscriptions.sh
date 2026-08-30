#!/bin/bash
# =============================================================================
# GIS Routing — NGSI-LD Subscription Setup
# =============================================================================
# Creates Orion-LD subscriptions to keep TimescaleDB materialized cache
# in sync with the Context Broker source of truth.
#
# Subscriptions are PER TENANT. A subscription created without NGSILD-Tenant
# lands in the tenant-less store, where it can never match an entity of any
# tenant — it looks healthy and never fires. Pass the tenants explicitly;
# this script refuses to run without them rather than defaulting.
#
# Subscription ids are deterministic, so re-running is idempotent: Orion
# answers 409 for one that already exists instead of creating a duplicate.
#
# The notify endpoint rejects any notification without the X-Orion-Secret
# header whenever MODULE_MANAGEMENT_KEY is configured on the backend (see
# app/api/routing.py:on_ngsild_notification). Orion only sends headers it was
# told to, via notification.endpoint.receiverInfo, so pass the same value in
# ORION_SECRET here or every notification is answered 403 and nothing is
# materialised. Never hardcode it: read it from the environment.
#
# The entity types below are exactly the ones the notify handler materializes
# (see app/api/routing.py:on_ngsild_notification). Adding a type here that the
# handler ignores creates a subscription that does nothing but deliver load.
#
# Usage:
#   TENANTS="tenant-a tenant-b" ./create-subscriptions.sh
#   ./create-subscriptions.sh tenant-a tenant-b
#
#   With port-forward:
#     kubectl port-forward -n nekazari svc/orion-service 1026:1026 &
#     ORION_URL=http://localhost:1026 \
#     NOTIFY_URL=http://localhost:8000/api/routing/notify \
#     TENANTS="tenant-a" ./create-subscriptions.sh
# =============================================================================
set -euo pipefail

ORION_URL="${ORION_URL:-http://orion-service:1026}"
ORION_SECRET="${ORION_SECRET:-}"
NOTIFY_URL="${NOTIFY_URL:-http://nkz-module-gis-routing-api-service:8000/api/routing/notify}"
CONTEXT_URL="${CONTEXT_URL:-http://api-gateway-service:5000/ngsi-ld-context.json}"

TENANTS="${TENANTS:-$*}"
if [ -z "$ORION_SECRET" ]; then
  echo "WARNING: ORION_SECRET is empty. If the backend has MODULE_MANAGEMENT_KEY" >&2
  echo "         set, every notification will be answered 403 and nothing will" >&2
  echo "         be materialised." >&2
fi

if [ -z "${TENANTS// /}" ]; then
  echo "ERROR: no tenants given. Pass them as arguments or in TENANTS." >&2
  echo "       A tenant-less subscription never matches any entity." >&2
  exit 1
fi

# Types the notify handler actually materializes. Keep this list in sync with it.
ENTITY_TYPES="AgriParcel ManufacturingMachine AgriParcelOperation"

create_sub() {
  local tenant="$1" entity_type="$2"
  local sub_id="urn:ngsi-ld:Subscription:gis-routing:${entity_type}"
  local status receiver_info=""

  if [ -n "$ORION_SECRET" ]; then
    receiver_info=",
          \"receiverInfo\": [{\"key\": \"X-Orion-Secret\", \"value\": \"$ORION_SECRET\"}]"
  fi

  status=$(curl -sS -o /dev/null -w "%{http_code}" -X POST "$ORION_URL/ngsi-ld/v1/subscriptions" \
    -H "Content-Type: application/json" \
    -H "NGSILD-Tenant: $tenant" \
    -H "Link: <$CONTEXT_URL>; rel=\"http://www.w3.org/ns/json-ld#context\"; type=\"application/ld+json\"" \
    -d "{
      \"id\": \"$sub_id\",
      \"description\": \"GIS Routing — $entity_type changes\",
      \"type\": \"Subscription\",
      \"entities\": [{\"type\": \"$entity_type\"}],
      \"notification\": {
        \"endpoint\": {
          \"uri\": \"$NOTIFY_URL\",
          \"accept\": \"application/json\"$receiver_info
        },
        \"format\": \"normalized\"
      },
      \"throttling\": 15,
      \"isActive\": true
    }")

  case "$status" in
    201) echo "  $tenant/$entity_type -> created" ;;
    409) echo "  $tenant/$entity_type -> already present" ;;
    *)   echo "  $tenant/$entity_type -> FAILED (HTTP $status)" >&2; return 1 ;;
  esac
}

failed=0
for tenant in $TENANTS; do
  echo "Tenant: $tenant"
  for entity_type in $ENTITY_TYPES; do
    create_sub "$tenant" "$entity_type" || failed=1
  done
done

if [ "$failed" -ne 0 ]; then
  echo "" >&2
  echo "One or more subscriptions failed." >&2
  exit 1
fi

echo ""
echo "Done. Verify one tenant with:"
echo "  curl -sS -H 'NGSILD-Tenant: <tenant>' $ORION_URL/ngsi-ld/v1/subscriptions?limit=100"
