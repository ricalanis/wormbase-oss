#!/usr/bin/env bash
# sync-tunnel-to-env.sh — extract the tunnel URL from the shared volume
# and write it into .env.tunnel as WORMBASE_DASHBOARD_URL.
#
# We use a sidecar .env.tunnel file rather than clobbering the main
# .env so:
#   1. The user's hand-edited .env stays pristine.
#   2. `make tunnel-down` can simply drop .env.tunnel without losing
#      anything.
#   3. The dashboard service can be configured to merge both files
#      (compose env_file directive on the dashboard service is A4's
#      scope; we only produce the file here).
#
# Usage:
#   bash infra/scripts/sync-tunnel-to-env.sh
#
# Idempotent: replaces existing WORMBASE_DASHBOARD_URL line if present.
set -euo pipefail

COMPOSE="${COMPOSE:-docker compose --project-directory . -f infra/docker-compose.yml}"
SERVICE="${TUNNEL_SERVICE_NAME:-tunnel}"
ENV_FILE="${ENV_TUNNEL_FILE:-.env.tunnel}"

# Read the URL out of the running tunnel container's /shared/tunnel.url
# (written by wait-for-tunnel.sh). The named volume backs both writers
# and readers, but pulling through `compose exec` keeps this script
# host-volume-mount-agnostic — works whether the volume is named or
# bind-mounted.
url=$($COMPOSE exec -T "$SERVICE" cat /shared/tunnel.url 2>/dev/null || true)

if [[ -z "$url" ]]; then
    echo "sync-tunnel-to-env: no URL found in /shared/tunnel.url — run wait-for-tunnel.sh first." >&2
    exit 1
fi

if ! [[ "$url" =~ ^https://[a-zA-Z0-9-]+\.trycloudflare\.com$ ]]; then
    echo "sync-tunnel-to-env: URL '$url' does not match trycloudflare.com pattern; refusing to write." >&2
    exit 1
fi

# Touch the file if missing so the upsert step is uniform.
touch "$ENV_FILE"

# Upsert WORMBASE_DASHBOARD_URL=... in $ENV_FILE.
# We use a tmp file + mv so partial writes can't corrupt the env file.
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

if grep -q '^WORMBASE_DASHBOARD_URL=' "$ENV_FILE" 2>/dev/null; then
    # Replace existing line. Using awk to avoid sed's platform quirks
    # (BSD vs GNU) around in-place edits.
    awk -v url="$url" 'BEGIN{set=0}
        /^WORMBASE_DASHBOARD_URL=/ { print "WORMBASE_DASHBOARD_URL=" url; set=1; next }
        { print }
        END { if (!set) print "WORMBASE_DASHBOARD_URL=" url }
    ' "$ENV_FILE" > "$tmp"
else
    cat "$ENV_FILE" > "$tmp"
    printf 'WORMBASE_DASHBOARD_URL=%s\n' "$url" >> "$tmp"
fi

mv "$tmp" "$ENV_FILE"
trap - EXIT

echo "sync-tunnel-to-env: wrote WORMBASE_DASHBOARD_URL=$url to $ENV_FILE"
