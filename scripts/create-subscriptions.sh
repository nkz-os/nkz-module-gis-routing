#!/bin/bash
# =============================================================================
# GIS Routing — NGSI-LD Subscription Setup
# =============================================================================
# Creates Orion-LD subscriptions to keep TimescaleDB materialized cache
# in sync with the Context Broker source of truth.
#
# Runs once per environment (not per tenant).
# Orion-LD sends normalized notifications to our webhook on entity changes.
#
# Usage:
#   From within the cluster:
#     kubectl exec -n nekazari deployment/orion-ld -- \
#       curl ... (see below)
#
#   With port-forward:
#     kubectl port-forward -n nekazari svc/orion-service 1026:1026 &
#     ORION_URL=http://localhost:1026 NOTIFY_URL=http://localhost:8000/api/routing/notify ./create-subscriptions.sh
# =============================================================================
set -euo pipefail

ORION_URL="${ORION_URL:-http://orion-service:1026}"
NOTIFY_URL="${NOTIFY_URL:-http://nkz-module-gis-routing-api-service:8000/api/routing/notify}"
CONTEXT_URL="${CONTEXT_URL:-http://api-gateway-service:5000/ngsi-ld-context.json}"

HEADERS=(
  -H "Content-Type: application/json"
  -H "Link: <$CONTEXT_URL>; rel=\"http://www.w3.org/ns/json-ld#context\"; type=\"application/ld+json\""
)

create_sub() {
  local desc="$1" entity_type="$2"
  echo "Creating subscription: $desc ($entity_type)"

  curl -sS -X POST "$ORION_URL/ngsi-ld/v1/subscriptions" \
    "${HEADERS[@]}" \
    -d "{
      \"description\": \"GIS Routing — $desc\",
      \"type\": \"Subscription\",
      \"entities\": [{\"type\": \"$entity_type\"}],
      \"notification\": {
        \"endpoint\": {
          \"uri\": \"$NOTIFY_URL\",
          \"accept\": \"application/json\"
        },
        \"format\": \"normalized\"
      },
      \"throttling\": 15,
      \"isActive\": true
    }" && echo "  -> OK" || echo "  -> Already exists or failed (non-critical)"
}

create_sub "AgriParcel changes" "AgriParcel"
create_sub "AgriculturalTractor changes" "AgriculturalTractor"
create_sub "AgriculturalImplement changes" "AgriculturalImplement"
create_sub "AgriParcelOperation changes" "AgriParcelOperation"
create_sub "AgriManagementZone changes" "AgriManagementZone"

echo ""
echo "All subscriptions created."
echo "Verify: curl -s $ORION_URL/ngsi-ld/v1/subscriptions?type=Subscription | python -c \"import sys,json; print(f'{len(json.load(sys.stdin))} active')\""
