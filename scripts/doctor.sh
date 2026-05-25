#!/usr/bin/env bash
# WormBase doctor — diagnose dev-env preconditions for `make tutorial`.
#
# Owned by W1.A4. Runs read-only checks across:
#   - host runtime (orb, docker, disk)
#   - .env keys (required + optional, never modified)
#   - stack health (worm-core /health, dashboard /, MCP /mcp/catalog,
#     postgres reachable)
#
# Exit codes:
#   0 — all green or only yellow (proceed with caution)
#   1 — at least one red (blocking issue; tutorial should halt)
#
# Color codes are constrained to the four required by spec:
#   red    \033[31m
#   yellow \033[33m
#   green  \033[32m
#   reset  \033[0m
set -uo pipefail

# Resolve repo root regardless of where the user invoked us.
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." &>/dev/null && pwd )"

RED='\033[31m'
YELLOW='\033[33m'
GREEN='\033[32m'
RESET='\033[0m'

# Honour NO_COLOR / non-tty stdout — the report should still be readable
# in CI logs. The eight-char escape just disappears.
if [ -n "${NO_COLOR:-}" ] || [ ! -t 1 ]; then
    RED=''; YELLOW=''; GREEN=''; RESET=''
fi

RED_COUNT=0
YELLOW_COUNT=0
GREEN_COUNT=0

ok()    { printf "  ${GREEN}[ok]${RESET}     %s\n" "$1";    GREEN_COUNT=$((GREEN_COUNT+1)); }
warn()  { printf "  ${YELLOW}[warn]${RESET}   %s\n" "$1";   YELLOW_COUNT=$((YELLOW_COUNT+1)); }
fail()  { printf "  ${RED}[fail]${RESET}   %s\n" "$1";      RED_COUNT=$((RED_COUNT+1)); }
info()  { printf "  [info]   %s\n" "$1"; }
header(){ printf "\n${RESET}== %s ==\n" "$1"; }

# ── Host runtime ──────────────────────────────────────────────────────
header "Host runtime"

# OrbStack is the user's Docker Desktop replacement on macOS.
if command -v orb >/dev/null 2>&1; then
    orb_status="$(orb status 2>/dev/null || true)"
    if printf '%s' "$orb_status" | grep -qiE '^Running'; then
        ok "orb status: Running"
    elif [ -z "$orb_status" ]; then
        warn "orb installed but 'orb status' returned no output"
    else
        first_line="$(printf '%s' "$orb_status" | head -n 1)"
        fail "orb status: ${first_line} (start with: orb start)"
    fi
else
    info "orb not installed (skipping; Docker Desktop or remote daemon may be in use)"
fi

if command -v docker >/dev/null 2>&1; then
    if docker info >/dev/null 2>&1; then
        ok "docker info reachable"
    else
        fail "docker info unreachable (daemon down or no permissions)"
    fi
else
    fail "docker CLI not installed"
fi

# Disk: yellow at 5-10 GB, red below 5 GB on /.
if avail_kb="$(df -Pk / | awk 'NR==2 {print $4}')" && [ -n "$avail_kb" ]; then
    avail_gb=$(( avail_kb / 1024 / 1024 ))
    if [ "$avail_gb" -gt 10 ]; then
        ok "disk: ${avail_gb} GB free on /"
    elif [ "$avail_gb" -ge 5 ]; then
        warn "disk: only ${avail_gb} GB free on / (recommend >10 GB for image builds)"
    else
        fail "disk: only ${avail_gb} GB free on / (image builds will fail; reclaim space)"
    fi
else
    warn "disk: could not determine free space on /"
fi

# ── .env keys ─────────────────────────────────────────────────────────
header ".env"

ENV_FILE="$REPO_ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
    fail ".env missing — copy .env.example to .env and fill required keys"
else
    ok ".env present"

    # Read a key WITHOUT sourcing the file (which would mutate our shell
    # and could be malicious). grep + cut on the literal "KEY=value" form.
    read_env_key() {
        local key="$1"
        # Match exact key=, ignore commented lines, take last occurrence.
        grep -E "^${key}=" "$ENV_FILE" 2>/dev/null \
            | tail -n 1 \
            | sed -E "s/^${key}=//; s/^['\"]//; s/['\"]$//"
    }

    # Required keys — each unset is a yellow; all unset is a red.
    REQUIRED_KEYS=(
        SLACK_BOT_TOKEN_BASEWORM
        SLACK_BOT_TOKEN_SIM_BASEWORM
        OPENCLAW_ADMIN_TOKEN
        OLLAMA_API_KEY
    )
    missing_required=0
    for key in "${REQUIRED_KEYS[@]}"; do
        val="$(read_env_key "$key")"
        if [ -z "$val" ]; then
            warn "${key} unset (required for full tutorial)"
            missing_required=$((missing_required+1))
        else
            ok "${key} set"
        fi
    done
    if [ "$missing_required" -eq "${#REQUIRED_KEYS[@]}" ]; then
        fail "all required .env keys are unset — cp .env.example .env and edit"
    fi

    # Optional keys — informational. Real OAuth (Tier-0 button) needs them.
    OPTIONAL_KEYS=(SLACK_CLIENT_ID SLACK_CLIENT_SECRET WORMBASE_DASHBOARD_URL)
    for key in "${OPTIONAL_KEYS[@]}"; do
        val="$(read_env_key "$key")"
        if [ -z "$val" ]; then
            info "${key} unset (real Slack OAuth via dashboard requires it)"
        else
            ok "${key} set"
        fi
    done
fi

# ── Stack health ──────────────────────────────────────────────────────
header "Stack health (best effort — only meaningful after 'make up')"

http_check() {
    local label="$1"; local url="$2"; local accept_404="${3:-0}"
    if ! command -v curl >/dev/null 2>&1; then
        warn "${label}: curl not available, skipping"
        return
    fi
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$url" 2>/dev/null || echo '000')"
    if [ "$code" = "200" ]; then
        ok "${label} reachable (200) — ${url}"
    elif [ "$accept_404" = "1" ] && [ "$code" = "404" ]; then
        # MCP catalog returns 404 when WORMBASE_MCP_ENABLED=0; honest
        # empty per spec. Not a doctor failure.
        info "${label} returned 404 — expected when MCP is disabled (${url})"
    elif [ "$code" = "000" ]; then
        warn "${label} unreachable — ${url} (stack may not be up; run 'make up')"
    else
        warn "${label} returned HTTP ${code} — ${url}"
    fi
}

http_check "worm-core /api/v1/health" "http://localhost:8910/api/v1/health"
http_check "dashboard /"               "http://localhost:3000/"
http_check "MCP /mcp/catalog"          "http://localhost:9911/mcp/catalog" 1

# OpenClaw container health — W7.A2. Inspect compose state directly
# (not an HTTP probe) because the canonical liveness signal is the
# Docker healthcheck wired into the openclaw service in docker-compose.yml.
# Three-state report: healthy = ok, unhealthy/exited = fail with
# remediation hint, starting/missing = warn.
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    # `timeout` is from GNU coreutils — present on Linux, optional on
    # macOS (brew install coreutils → `gtimeout`). Use whichever is
    # available so doctor stays fast, fall back to bare `docker inspect`
    # otherwise. Docker daemon hangs are rare; the typical path is fast.
    if command -v timeout >/dev/null 2>&1; then
        _oc_inspect_prefix="timeout 2"
    elif command -v gtimeout >/dev/null 2>&1; then
        _oc_inspect_prefix="gtimeout 2"
    else
        _oc_inspect_prefix=""
    fi
    oc_status="$($_oc_inspect_prefix docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' wormbase-openclaw 2>/dev/null || echo 'missing')"
    case "$oc_status" in
        healthy)
            ok "openclaw: healthy"
            ;;
        unhealthy)
            fail "openclaw: unhealthy (recover with: make openclaw-restart)"
            ;;
        starting)
            warn "openclaw: still starting (start_period not yet elapsed)"
            ;;
        running)
            # Container is up but no healthcheck configured (older image
            # build). Treat as warn — we can't confirm, but it's not red.
            warn "openclaw: running, healthcheck not reporting (rebuild image?)"
            ;;
        exited|dead|paused|created|restarting)
            fail "openclaw: container ${oc_status} (recover with: make openclaw-restart)"
            ;;
        missing|"")
            warn "openclaw: container not found (run 'make up')"
            ;;
        *)
            warn "openclaw: unknown state '${oc_status}'"
            ;;
    esac
else
    info "openclaw: skipping container inspect (docker unavailable)"
fi

# Postgres: try `pg_isready` if installed, else a TCP probe.
if command -v pg_isready >/dev/null 2>&1; then
    if pg_isready -h localhost -p 5432 -U wormbase -d wormbase -t 2 >/dev/null 2>&1; then
        ok "postgres reachable on localhost:5432"
    else
        warn "postgres not reachable on localhost:5432 (run 'make up')"
    fi
elif command -v nc >/dev/null 2>&1; then
    if nc -z -G 2 localhost 5432 >/dev/null 2>&1 || nc -z -w 2 localhost 5432 >/dev/null 2>&1; then
        ok "postgres TCP open on localhost:5432"
    else
        warn "postgres TCP closed on localhost:5432 (run 'make up')"
    fi
else
    info "no pg_isready/nc; skipping postgres probe"
fi

# ── Summary ───────────────────────────────────────────────────────────
header "Summary"
printf "  ${GREEN}%d ok${RESET}   ${YELLOW}%d warn${RESET}   ${RED}%d fail${RESET}\n" \
    "$GREEN_COUNT" "$YELLOW_COUNT" "$RED_COUNT"

if [ "$RED_COUNT" -gt 0 ]; then
    printf "${RED}doctor: blocking issues found (exit 1)${RESET}\n"
    exit 1
fi
if [ "$YELLOW_COUNT" -gt 0 ]; then
    printf "${YELLOW}doctor: warnings present, but no blockers (exit 0)${RESET}\n"
else
    printf "${GREEN}doctor: all checks passed${RESET}\n"
fi
exit 0
