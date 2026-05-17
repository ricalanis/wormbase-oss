#!/usr/bin/env bash
# wait-for-tunnel.sh — poll the cloudflared tunnel sidecar's log for an
# assigned https://*.trycloudflare.com URL and stash it on the shared
# volume so the host can pick it up.
#
# Usage:
#   bash infra/scripts/wait-for-tunnel.sh [timeout_seconds]
#
# Exits 0 on success (URL written to /shared/tunnel.url inside the
# container, mirrored to the named volume on the host). Exits 1 on
# timeout (default 30s). Idempotent: re-running after success short-
# circuits if /shared/tunnel.url already holds a valid URL.
#
# Why poll the log rather than parse cloudflared's metrics endpoint?
# The free-tier quick-tunnel URL only appears in stdout. The metrics
# endpoint exposes runtime stats, not the assigned hostname.
set -euo pipefail

TIMEOUT="${1:-30}"
COMPOSE="${COMPOSE:-docker compose --project-directory . -f infra/docker-compose.yml}"
SERVICE="${TUNNEL_SERVICE_NAME:-tunnel}"
URL_PATTERN='https://[a-zA-Z0-9-]+\.trycloudflare\.com'

# Helper: run a command inside the tunnel container. Falls back to
# `docker exec` directly if `compose exec` isn't available (e.g.
# legacy compose v1 syntax).
exec_in_tunnel() {
    $COMPOSE exec -T "$SERVICE" "$@"
}

# Idempotency: if a URL already exists in the container's /shared and
# resolves a fresh trycloudflare hostname, return it.
existing_url=$(exec_in_tunnel cat /shared/tunnel.url 2>/dev/null || true)
if [[ -n "$existing_url" ]] && [[ "$existing_url" =~ ^https://[a-zA-Z0-9-]+\.trycloudflare\.com$ ]]; then
    # Verify the tunnel container is actually still serving this URL —
    # if the container was restarted, the URL rotated and the cached
    # value is stale. Compare against the live log.
    live_url=$(exec_in_tunnel sh -c "grep -oE '$URL_PATTERN' /shared/tunnel.log 2>/dev/null | tail -1" || true)
    if [[ "$existing_url" == "$live_url" ]]; then
        echo "tunnel: already up at $existing_url (idempotent re-run)"
        exit 0
    fi
fi

echo "tunnel: waiting up to ${TIMEOUT}s for cloudflared to assign a URL..."
deadline=$(( $(date +%s) + TIMEOUT ))

while [[ $(date +%s) -lt $deadline ]]; do
    # Find the latest URL in the tunnel's log. We grab the last match
    # in case the log has rotated through multiple URLs (shouldn't
    # happen on a fresh boot, but defensively `tail -1`).
    url=$(exec_in_tunnel sh -c "grep -oE '$URL_PATTERN' /shared/tunnel.log 2>/dev/null | tail -1" || true)
    if [[ -n "$url" ]]; then
        # Persist the URL inside the shared volume. sync-tunnel-to-env.sh
        # reads this back on the host side via the same named volume.
        exec_in_tunnel sh -c "printf '%s' '$url' > /shared/tunnel.url"
        echo "tunnel: ready at $url"
        exit 0
    fi
    sleep 1
done

echo "tunnel: timed out after ${TIMEOUT}s — cloudflared did not produce a URL." >&2
echo "tunnel: check '$COMPOSE logs $SERVICE' for cloudflared errors." >&2
exit 1
