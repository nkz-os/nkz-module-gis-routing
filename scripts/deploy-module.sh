#!/usr/bin/env bash
# =============================================================================
# deploy-module.sh — Frontend (MF2 remote) deploy for nkz-module-gis-routing
# =============================================================================
# Builds the Module Federation remote and publishes it to MinIO as a FLAT
# overwrite of the live module path (NOT a versioned <sha>/ path — that model
# is unused for this module). Backs up the current contents first and verifies
# the served remoteEntry afterwards.
#
# This is the real, canonical deploy mechanism (the CI MinIO/activate steps are
# non-functional). Run it from a host that has BOTH `pnpm` (to build) and a
# working `mc` alias pointing at the cluster MinIO (default: `internal-minio`).
#
# Idempotent: re-running rebuilds and re-overwrites; each run snapshots the
# pre-deploy state under a unique, sha-stamped backup prefix.
#
# Required tools: git, pnpm, mc, curl
#
# Configurable via env (defaults match the production layout):
#   MC_ALIAS         mc alias for cluster MinIO            (internal-minio)
#   BUCKET           frontend bucket                       (nekazari-frontend)
#   MODULE_ID        module folder under modules/          (nkz-module-gis-routing)
#   PUBLIC_BASE_URL  base URL that serves /modules/...     (https://nekazari.robotika.cloud)
#   SKIP_BUILD       set to 1 to deploy an existing dist/  (unset)
# =============================================================================
set -euo pipefail

MC_ALIAS="${MC_ALIAS:-internal-minio}"
BUCKET="${BUCKET:-nekazari-frontend}"
MODULE_ID="${MODULE_ID:-nkz-module-gis-routing}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://nekazari.robotika.cloud}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

GIT_SHA="$(git rev-parse --short=8 HEAD)"
LIVE_PATH="${MC_ALIAS}/${BUCKET}/modules/${MODULE_ID}/"
BACKUP_PATH="${MC_ALIAS}/${BUCKET}/_backup/${MODULE_ID}-pre-${GIT_SHA}-$(date -u +%Y%m%d%H%M%S)/"
ENTRY_URL="${PUBLIC_BASE_URL}/modules/${MODULE_ID}/remoteEntry.js"

log() { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[deploy:ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

for bin in git pnpm mc curl; do
  command -v "$bin" >/dev/null 2>&1 || die "required tool not found: $bin"
done
mc alias list "$MC_ALIAS" >/dev/null 2>&1 || die "mc alias '$MC_ALIAS' not configured"

# 1. Build the MF2 remote (sha-stamped for cache-busting in the host).
if [ "${SKIP_BUILD:-}" = "1" ]; then
  log "SKIP_BUILD=1 — using existing dist/"
else
  log "Building module bundle (NKZ_VERSION_HASH=${GIT_SHA}) ..."
  NKZ_VERSION_HASH="$GIT_SHA" pnpm run build:module
fi
[ -f dist/remoteEntry.js ] || die "dist/remoteEntry.js not found — build did not produce a remote entry"

# 2. Back up the current live contents (best-effort: empty on first deploy).
log "Backing up current live module → ${BACKUP_PATH}"
if mc ls "$LIVE_PATH" >/dev/null 2>&1; then
  mc cp --recursive "$LIVE_PATH" "$BACKUP_PATH" || die "backup failed — aborting before overwrite"
else
  log "No existing live contents to back up (first deploy?)"
fi

# 3. Flat overwrite of the live path.
log "Uploading dist/ → ${LIVE_PATH}"
mc cp --recursive ./dist/ "$LIVE_PATH" || die "upload failed"
mc anonymous set download "$LIVE_PATH" >/dev/null 2>&1 || true

# 4. Verify the served remote entry: HTTP 200 + non-empty body.
log "Verifying ${ENTRY_URL}"
http_code="$(curl -fsS -o /tmp/deploy_remoteEntry.js -w '%{http_code}' "$ENTRY_URL" || true)"
bytes="$(wc -c < /tmp/deploy_remoteEntry.js 2>/dev/null || echo 0)"
rm -f /tmp/deploy_remoteEntry.js
[ "$http_code" = "200" ] || die "remoteEntry verification failed: HTTP ${http_code} (rollback: mc cp --recursive ${BACKUP_PATH} ${LIVE_PATH})"
[ "$bytes" -gt 0 ] || die "remoteEntry served 0 bytes (rollback: mc cp --recursive ${BACKUP_PATH} ${LIVE_PATH})"

log "OK — deployed ${MODULE_ID} @ ${GIT_SHA}; remoteEntry 200, ${bytes} bytes."
log "Rollback if needed: mc cp --recursive ${BACKUP_PATH} ${LIVE_PATH}"
