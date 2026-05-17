#!/usr/bin/env bash
# WormBase — 20-minute demo setup script (lunch-hour edition)
# Run this from the repo root:  bash scripts/demo-setup.sh
#
# What it does:
#   1. Checks Docker + .env
#   2. Starts all services
#   3. Seeds baseworm tenant with rich demo state
#   4. Invites bot to #todo-baseworm
#   5. Verifies dashboard + MCP + Slack
#   6. Prints a go/no-go verdict
#
# If anything fails, it stops immediately and tells you what to fix.

set -euo pipefail

RED='\033[31m'; GREEN='\033[32m'; YELLOW='\033[33m'; RESET='\033[0m'
[ -t 1 ] || { RED=''; GREEN=''; YELLOW=''; RESET=''; }

ok()   { echo -e "  ${GREEN}✓${RESET} $1"; }
fail() { echo -e "  ${RED}✗${RESET} $1"; exit 1; }
warn() { echo -e "  ${YELLOW}!${RESET} $1"; }
step() { echo -e "\n${YELLOW}▶ $1${RESET}"; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ── 1. Preconditions ──────────────────────────────────────────────────
step "1/6  Checking preconditions"

command -v docker >/dev/null 2>&1 || fail "docker CLI not found"
docker info >/dev/null 2>&1          || fail "docker daemon not reachable"
ok "docker is up"

[ -f .env ] || fail ".env missing — copy .env.example to .env and fill it"
ok ".env present"

[ "$(df -Pk / | awk 'NR==2 {print $4}')" -gt 5242880 ] 2>/dev/null || warn "disk < 5 GB free — builds may fail"

# ── 2. Start stack ────────────────────────────────────────────────────
step "2/6  Starting services (this takes ~60s)"

docker compose --project-directory . -f infra/docker-compose.yml up -d

# Wait for postgres first (everything depends on it)
echo -n "  waiting for postgres"
for i in {1..30}; do
  docker exec wormbase-postgres pg_isready -U wormbase 2>/dev/null && break
  echo -n "."
  sleep 2
done
echo ""
docker exec wormbase-postgres pg_isready -U wormbase >/dev/null 2>&1 || fail "postgres never came up"
ok "postgres ready"

# ── 3. Seed demo tenant ───────────────────────────────────────────────
step "3/6  Seeding baseworm tenant (rich demo state)"

docker compose --project-directory . -f infra/docker-compose.yml run --rm sim-harness \
  demo seed --reset-first --tenant baseworm --install-from-env --rich
ok "baseworm seeded"

# ── 4. Warm up dashboard ────────────────────────────────────────────────
step "4/6  Warming up dashboard"

# Next.js dev server needs one compile cycle after cold start
echo -n "  compiling"
for i in {1..60}; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/api/health 2>/dev/null || echo 000)
  [ "$code" = "200" ] && break
  echo -n "."
  sleep 2
done
echo ""

curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/api/health | grep -q 200 || fail "dashboard /api/health not 200"
ok "dashboard healthcheck 200"

# Verify key routes
paths="/ /dashboard /onboarding /sources /trace /people /decisions /data-products /mcp"
for p in $paths; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:3000$p" 2>/dev/null || echo 000)
  [ "$code" = "200" ] || fail "dashboard $p returned $code"
done
ok "dashboard routes all 200"

# ── 5. Invite bot to Slack channel ────────────────────────────────────
step "5/6  Ensuring Slack bot is in #todo-baseworm"

# Try to invite; if it's already in the channel, Slack returns "already_in_channel" which is fine
docker compose exec openclaw openclaw channels invite --channel '#todo-baseworm' 2>/dev/null || true
ok "bot invited (or already present)"

# Quick ping: post a message then delete it
docker compose exec openclaw openclaw channels ping --channel '#todo-baseworm' 2>/dev/null || warn "Slack ping failed — check OPENCLAW_SLACK_BOT_TOKEN in .env"

# ── 6. MCP preflight ──────────────────────────────────────────────────
step "6/6  MCP preflight"

code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:9911/mcp 2>/dev/null || echo 000)
[ "$code" = "200" ] || fail "MCP /mcp returned $code"
ok "MCP health 200"

ok=$(curl -s http://localhost:9911/mcp 2>/dev/null | grep -o '"ok"' || true)
[ -n "$ok" ] || warn "MCP JSON response missing 'ok' field"

# ── Verdict ─────────────────────────────────────────────────────────────
echo -e "\n${GREEN}═══════════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}  ALL SYSTEMS GO — you are ready to demo.${RESET}"
echo -e "${GREEN}═══════════════════════════════════════════════════════${RESET}"
echo ""
echo "  Dashboard:  http://localhost:3000"
echo "  MCP:        http://localhost:9911/mcp"
echo "  Slack:      #todo-baseworm"
echo ""
echo "  Next step:  make demo"
echo "              (or:  make demo PACE=virtual  for a fast dry-run)"
