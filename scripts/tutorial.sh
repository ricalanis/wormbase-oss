#!/usr/bin/env bash
# WormBase tutorial — orchestrate cold-start → working install in <90s.
#
# Owned by W1.A4. The tutorial is the production happy-path:
#   1. doctor (halt on red)
#   2. make up with retry-on-EOF (handles npm fetch flakes)
#   3. wait-for-health on worm-core / dashboard / MCP
#   4. seed BASEWORM tenant (with --install-from-env if a bot token is
#      available in env; otherwise warmup-only and direct the user at
#      /onboarding for the dashboard OAuth path)
#   5. seed DEMOCORP tenant (warmup-only, secondary multi-tenant)
#   6. open the user's default browser at /onboarding/welcome
#   7. print a clickable URL and next-step hints
#
# Idempotent — running twice should produce the same end-state. The
# seeds use --reset-first; the OAuth path is gated on env presence.
set -uo pipefail

REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &>/dev/null && pwd )"
cd "$REPO_ROOT"

RED='\033[31m'
YELLOW='\033[33m'
GREEN='\033[32m'
RESET='\033[0m'
if [ -n "${NO_COLOR:-}" ] || [ ! -t 1 ]; then
    RED=''; YELLOW=''; GREEN=''; RESET=''
fi

log()  { printf "${GREEN}[tutorial]${RESET} %s\n" "$*"; }
warn() { printf "${YELLOW}[tutorial]${RESET} %s\n" "$*"; }
err()  { printf "${RED}[tutorial]${RESET} %s\n" "$*"; }

# Compose invocation matches the Makefile so the project name + file
# are identical (avoids spawning a parallel "wormbase" project).
COMPOSE="docker compose --project-directory . -f infra/docker-compose.yml"

# ── Step 1: doctor ────────────────────────────────────────────────────
log "Step 1/6 — running doctor"
if ! bash "$REPO_ROOT/scripts/doctor.sh"; then
    err "doctor reported red issues; aborting tutorial"
    err "fix the items above (or 'cp .env.example .env' if .env is missing) and re-run"
    exit 1
fi

# ── Step 2: make up with retry ────────────────────────────────────────
log "Step 2/6 — bringing the stack up (with retry on transient errors)"
attempt=0
max_attempts=3
while true; do
    attempt=$((attempt+1))
    out_file="$(mktemp -t wormbase-up.XXXXXX)"
    # `up -d` returns immediately once containers start; transient
    # docker daemon errors / network flakes (especially fresh image
    # pulls) are the most common reason this fails on first run.
    if $COMPOSE up -d 2>&1 | tee "$out_file"; then
        rm -f "$out_file"
        log "stack up (attempt ${attempt})"
        break
    fi
    rc=$?
    if [ "$attempt" -ge "$max_attempts" ]; then
        err "make up failed after ${max_attempts} attempts; see output above"
        rm -f "$out_file"
        exit 1
    fi
    if grep -qiE 'EOF|i/o timeout|connection reset|tls handshake' "$out_file"; then
        warn "transient error on attempt ${attempt}; retrying in 3s"
    else
        warn "make up failed (rc=${rc}); retrying in 3s"
    fi
    rm -f "$out_file"
    sleep 3
done

# ── Step 3: wait for health ───────────────────────────────────────────
log "Step 3/6 — waiting for worm-core + dashboard + MCP to report healthy (≤60s)"

wait_for() {
    local url="$1"; local label="$2"; local accept_404="${3:-0}"
    local deadline=$(( $(date +%s) + 60 ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$url" 2>/dev/null || echo '000')"
        if [ "$code" = "200" ]; then
            log "  ${label} ready (200)"
            return 0
        fi
        if [ "$accept_404" = "1" ] && [ "$code" = "404" ]; then
            log "  ${label} responded 404 (acceptable — MCP disabled)"
            return 0
        fi
        sleep 2
    done
    warn "  ${label} did not become ready within 60s (continuing — seed may still succeed)"
    return 1
}

wait_for "http://localhost:8910/api/v1/health" "worm-core" || true
wait_for "http://localhost:3000/"               "dashboard" || true
wait_for "http://localhost:9911/mcp/catalog"   "MCP" 1 || true

# ── Step 4: seed BASEWORM ─────────────────────────────────────────────
# Token detection: load .env, then check whether the BASEWORM bot token
# is non-empty. We do NOT export the .env into our shell — the compose
# `run` command picks up the file via --env-file by default, and the
# sim-harness service block in compose.yml already wires the relevant
# env keys through.
slack_bot_token_baseworm=""
if [ -f "$REPO_ROOT/.env" ]; then
    slack_bot_token_baseworm="$(grep -E '^SLACK_BOT_TOKEN_BASEWORM=' "$REPO_ROOT/.env" 2>/dev/null \
        | tail -n 1 | sed -E 's/^SLACK_BOT_TOKEN_BASEWORM=//; s/^["'\'']//; s/["'\'']$//')"
fi

log "Step 4/6 — seeding tenant 'baseworm' (saas pack)"
if [ -n "$slack_bot_token_baseworm" ]; then
    log "  SLACK_BOT_TOKEN_BASEWORM detected — seed with --install-from-env"
    # xoxb tokens have no profile email; the override is required for
    # the install helper's email-match step. The override is set only
    # for THIS docker compose run; .env is never modified.
    if ! $COMPOSE run --rm \
        -e WORMBASE_INSTALLER_EMAIL_OVERRIDE="${WORMBASE_INSTALLER_EMAIL_OVERRIDE:-admin@example.com}" \
        sim-harness demo seed --reset-first --install-from-env \
            --tenant baseworm --domain-pack saas; then
        err "baseworm seed failed; check sim-harness output above"
        err "tip: ensure SLACK_BOT_TOKEN_BASEWORM is a valid xoxb token from your Slack app"
        exit 1
    fi
    seed_path="install"
else
    warn "SLACK_BOT_TOKEN_BASEWORM not set — running warmup-only seed (no install)"
    warn "OAuth via the dashboard's /onboarding 'Connect to Slack' is the install path"
    if ! $COMPOSE run --rm sim-harness demo seed --reset-first \
            --tenant baseworm --domain-pack saas; then
        err "baseworm warmup seed failed"
        exit 1
    fi
    seed_path="warmup"
fi

# ── Step 5: seed DEMOCORP ─────────────────────────────────────────────
log "Step 5/6 — seeding tenant 'democorp' (marketplace pack, warmup-only)"
if ! $COMPOSE run --rm sim-harness demo seed --reset-first \
        --tenant democorp --domain-pack marketplace; then
    warn "democorp seed failed; baseworm is still usable"
fi

# ── Step 6: open browser ──────────────────────────────────────────────
if [ "$seed_path" = "install" ]; then
    target="http://localhost:3000/onboarding/welcome"
else
    target="http://localhost:3000/onboarding"
fi

log "Step 6/6 — opening ${target}"
if command -v open >/dev/null 2>&1; then
    open "$target" 2>/dev/null || true
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$target" 2>/dev/null || true
else
    info_line="(no browser-open command found; copy the URL above)"
    warn "$info_line"
fi

# ── Done ──────────────────────────────────────────────────────────────
printf "\n${GREEN}== Tutorial complete ==${RESET}\n"
printf "  Dashboard:  %s\n" "$target"
printf "  Trace:      http://localhost:3000/trace\n"
printf "  Seed mode:  %s\n" "$seed_path"
if [ "$seed_path" = "warmup" ]; then
    printf "  ${YELLOW}Next step:${RESET} click 'Connect to Slack' on the dashboard to install\n"
    printf "             (requires SLACK_CLIENT_ID + SLACK_CLIENT_SECRET in .env)\n"
fi
printf "  Stop with:  make down\n"
exit 0
