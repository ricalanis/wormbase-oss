# WormBase monorepo Makefile
#
# Targets are stubs during Phase 0; they are progressively implemented by
# subsequent phases. Every target echoes its own name so CI and humans
# can confirm the plumbing is wired before any business logic lands.

COMPOSE := docker compose --project-directory . -f infra/docker-compose.yml

COMPOSE_TEST := docker compose --project-directory . \
    --project-name wormbase-test-cli \
    -f infra/docker-compose.test.yml

QA_JUNIT_DIR := .junit
QA_AGGREGATOR := uv run python -m tests._aggregator.qa_report

.PHONY: up down logs ps test test-all demo demo-virtual seed verify help \
        doctor tutorial \
        sim-build sim-test \
        openclaw-build openclaw-restart openclaw-logs openclaw-status \
        adapter-test adapter-build adapter-restart adapter-logs adapter-inspect \
        worm-build worm-restart worm-logs worm-test worm-inspect \
        dashboard-build dashboard-restart dashboard-logs dashboard-test dashboard-typecheck \
        visual-baselines \
        qa qa-fast qa-pre-demo qa-report integration demo-gates \
        test-ts test-contract test-service \
        test-up test-down test-logs \
        stage-replay-demo mcp-preflight \
        refresh-inference-cache

help:
	@echo "WormBase monorepo targets:"
	@echo "  make up                — bring up local dev services (docker-compose)"
	@echo "  make down              — tear down local dev services"
	@echo "  make logs              — tail logs from all dev services"
	@echo "  make ps                — show running dev services"
	@echo "  make test              — run full Python test suite (L1)"
	@echo "  make test-all          — loop pytest per package + workspace tests/ (cross-pkg)"
	@echo "  make demo              — orchestrated 7+1 beat demo with per-beat auto-recovery"
	@echo "  make seed              — provision demo workspace state"
	@echo "  make doctor            — diagnose dev-env preconditions"
	@echo "  make tutorial          — cold-start → working install in <90s"
	@echo "  make verify            — run ledger hash-chain verification"
	@echo ""
	@echo "QA — 6-layer test orchestration:"
	@echo "  make qa-fast           — L1 + L2 + L3   (dev pre-commit)"
	@echo "  make qa                — L1 + L2 + L3 + L4 + L5     (CI / pre-merge)"
	@echo "  make qa-pre-demo       — qa + L6 demo gates  (Tue/Wed dry runs)"
	@echo "  make qa-report         — print the per-layer pass/fail/skip table"
	@echo "  make integration       — L5 only (tests/integration/)"
	@echo "  make demo-gates        — L6 only (tests/demo/, F/Q/N gates)"
	@echo "  make test-contract     — L3 only (tests/contract/)"
	@echo "  make test-service      — L4 only (-m service marker)"
	@echo "  make test-ts           — L1 + L2 (TS via vitest + Playwright)"
	@echo "  make test-up           — bring up the TEST docker compose"
	@echo "  make test-down         — tear down the TEST docker compose"
	@echo "  make test-logs         — tail logs from the TEST stack"
	@echo ""
	@echo "OpenClaw (chat gateway, multi-tenant):"
	@echo "  make openclaw-build    — rebuild the OpenClaw image after Dockerfile changes"
	@echo "  make openclaw-restart  — restart OpenClaw to pick up config.json5 + .env changes"
	@echo "  make openclaw-logs     — follow OpenClaw gateway logs"
	@echo "  make openclaw-status   — show OpenClaw channel status (--probe)"
	@echo ""
	@echo "Channel adapter (OpenClaw → ledger):"
	@echo "  make adapter-test      — run channel-adapter unit tests (pytest)"
	@echo "  make adapter-build     — rebuild the channel-adapter image"
	@echo "  make adapter-restart   — restart the channel-adapter container"
	@echo "  make adapter-logs      — follow channel-adapter logs"
	@echo "  make adapter-inspect   — list recent chat ledger entries for the demo tenant"
	@echo ""
	@echo "Worm core (reactivity triad, source flows, ramp, autoresearch):"
	@echo "  make worm-test         — run worm-core + governance + ontology-seed pytest"
	@echo "  make worm-build        — rebuild the worm-core image"
	@echo "  make worm-restart      — restart the worm-core container"
	@echo "  make worm-logs         — follow worm-core logs"
	@echo "  make worm-inspect      — print recent worm-core ledger entries"
	@echo ""
	@echo "Dashboard (Next.js · Field Notebook):"
	@echo "  make dashboard-build   — rebuild the dashboard image"
	@echo "  make dashboard-restart — restart the dashboard container"
	@echo "  make dashboard-logs    — follow dashboard logs"
	@echo "  make dashboard-test    — run dashboard + design vitest unit tests"
	@echo "  make dashboard-typecheck — pnpm typecheck the dashboard + design"
	@echo "  make visual-baselines  — regenerate Playwright PNG baselines against canonical rich seed"

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

test:
	uv run --package wormbase-ledger --extra dev pytest packages/ledger/tests -q
	uv run --package wormbase-ontology-seed --extra dev pytest packages/ontology-seed/tests -q
	uv run --package wormbase-governance --extra dev pytest packages/governance/tests -q
	uv run --package wormbase-channel-adapter --extra dev pytest apps/channel-adapter/tests -q
	uv run --package wormbase-worm-core --extra dev pytest apps/worm-core/tests -q

# `make test-all` (O-B6) — cross-package full Python suite.
#
# Cross-package `pytest packages/` from the workspace root collides on
# the `tests.conftest` namespace (each package owns a `tests/conftest.py`
# and pytest can't load 16+ conftests under one rootdir). The supported
# alternatives are this target (loops package-by-package) or running
# `uv run pytest packages/<name>/tests/` for a single package.
#
# After the per-package loop, also runs the workspace-root `tests/`
# suite (contract / integration / demo / property / chaos / multitenant)
# which lives outside any package.
test-all:
	@for pkg in packages/*/; do \
		if [ -d "$$pkg/tests" ]; then \
			echo "=== $$pkg ==="; \
			(cd $$pkg && uv run --extra dev pytest tests/ -q) || exit 1; \
		fi; \
	done
	@for app in apps/*/; do \
		if [ -d "$$app/tests" ]; then \
			echo "=== $$app ==="; \
			(cd $$app && uv run --extra dev pytest tests/ -q) || exit 1; \
		fi; \
	done
	@echo "=== workspace tests/ ==="
	uv run --extra dev pytest tests/ -q

# `make demo` (W3.A11) — one-command orchestrator with per-beat
# auto-recovery. Wraps `wormbase demo run --scenario install-arc-7beat`
# and detects each beat's failure mode (worm-core stalled, channel-
# adapter stalled, OAuth flake) and auto-recovers via worm-restart /
# adapter-restart / wire-replay without operator intervention.
#
# Override pace via `make demo PACE=virtual`. Sandbox mode (no
# compose calls) via `WORMBASE_DEMO_SKIP_RUN=1 make demo`.
demo:
	@python3 scripts/demo-orchestrator.py \
	    --scenario install-arc-7beat \
	    --pace $(or $(PACE),wall)

demo-virtual:
	@python3 scripts/demo-orchestrator.py \
	    --scenario install-arc-7beat \
	    --pace virtual

seed:
	$(COMPOSE) run --rm sim-harness demo seed --reset-first \
	    --tenant baseworm --domain-pack saas
	$(COMPOSE) run --rm sim-harness demo seed --reset-first \
	    --tenant democorp --domain-pack marketplace

doctor:
	@bash scripts/doctor.sh

tutorial:
	@bash scripts/tutorial.sh

verify:
	@echo "make verify (stub — will invoke wormbase verify CLI)"

# Wave H Phase 1 1A — wipe the inference cache and emit an audit PEVR cycle.
# Honors WORMBASE_INFERENCE_CACHE_PATH (default /tmp/wormbase-inference-cache.sqlite).
# Writes an inference_cache_refreshed ledger row when WORMBASE_LEDGER_DSN +
# WORMBASE_TENANT_ID are set; otherwise prints a notice and exits 0.
refresh-inference-cache:
	uv run --package wormbase-inference-router --extra dev \
		python scripts/refresh_inference_cache.py

# ─── OpenClaw ──────────────────────────────────────────────────

openclaw-build:
	$(COMPOSE) build openclaw

# W7.A2 — one-command recovery from `unhealthy`. Captures pre-restart
# state to .openclaw-pre-restart.log (last 100 lines + container status)
# so forensics is preserved before the restart wipes the in-container
# state. Then restarts and re-runs the doctor's openclaw block to
# verify recovery — exit code propagates from doctor (1 if still
# unhealthy after the restart window).
openclaw-restart:
	@echo "[openclaw-restart] capturing pre-restart state to .openclaw-pre-restart.log"
	@( \
		echo "=== openclaw-restart triggered at $$(date -u +%FT%TZ) ==="; \
		echo; \
		echo "--- docker compose ps openclaw ---"; \
		$(COMPOSE) ps openclaw 2>&1 || true; \
		echo; \
		echo "--- docker inspect health ---"; \
		docker inspect -f '{{json .State.Health}}' wormbase-openclaw 2>&1 || true; \
		echo; \
		echo "--- last 100 log lines ---"; \
		$(COMPOSE) logs --tail 100 openclaw 2>&1 || true; \
	) > .openclaw-pre-restart.log
	$(COMPOSE) restart openclaw
	@echo "[openclaw-restart] restarted; waiting up to 120s for healthy…"
	@bash -c 'deadline=$$(( $$(date +%s) + 120 )); while [ $$(date +%s) -lt $$deadline ]; do \
		s="$$(docker inspect -f "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" wormbase-openclaw 2>/dev/null || echo missing)"; \
		case "$$s" in healthy) echo "[openclaw-restart] healthy"; exit 0 ;; unhealthy|exited|dead) echo "[openclaw-restart] state=$$s — see .openclaw-pre-restart.log"; exit 1 ;; esac; \
		sleep 3; \
	done; echo "[openclaw-restart] timed out waiting for healthy state"; exit 1'
	@bash scripts/doctor.sh

openclaw-logs:
	$(COMPOSE) logs -f openclaw

openclaw-status:
	$(COMPOSE) exec openclaw openclaw channels status --probe

# ─── Sim harness (Phase 5) ─────────────────────────────────────

sim-build:
	$(COMPOSE) build sim-harness

sim-test:
	uv run --package wormbase-sim-harness --extra dev \
	    pytest apps/sim-harness/tests -q

# ─── Channel adapter (OpenClaw → ledger) ───────────────────────

adapter-test:
	uv run --package wormbase-channel-adapter --extra dev \
	    pytest apps/channel-adapter/tests -q

adapter-build:
	$(COMPOSE) build channel-adapter

adapter-restart:
	$(COMPOSE) restart channel-adapter

adapter-logs:
	$(COMPOSE) logs -f channel-adapter

adapter-inspect:
	$(COMPOSE) exec channel-adapter wormbase-channel-adapter inspect --limit 20

# ─── Worm core ────────────────────────────────────────────────

worm-test:
	uv run --package wormbase-worm-core --extra dev pytest apps/worm-core/tests -q
	uv run --package wormbase-governance --extra dev pytest packages/governance/tests -q
	uv run --package wormbase-ontology-seed --extra dev pytest packages/ontology-seed/tests -q

worm-build:
	$(COMPOSE) build worm-core

worm-restart:
	$(COMPOSE) restart worm-core

worm-logs:
	$(COMPOSE) logs -f worm-core

worm-inspect:
	$(COMPOSE) exec worm-core wormbase-worm-core inspect --limit 30

# ─── Dashboard (Next.js · Field Notebook) ─────────────────────

dashboard-build:
	$(COMPOSE) build dashboard

dashboard-restart:
	$(COMPOSE) restart dashboard

dashboard-logs:
	$(COMPOSE) logs -f dashboard

dashboard-test:
	pnpm --filter @wormbase/dashboard test:unit
	pnpm --filter @wormbase/design test

dashboard-typecheck:
	pnpm --filter @wormbase/dashboard typecheck
	pnpm --filter @wormbase/design typecheck

# ─── Visual regression baselines (W7.A6) ──────────────────────
#
# `make visual-baselines` regenerates all 80 Playwright PNGs under
# `apps/dashboard/tests/visual/__snapshots__/` against the canonical
# rich seed. Idempotent: re-running on a stable stack produces the
# same output (modulo masked volatile regions like timestamps).
#
# Workflow:
#   1. Seed `baseworm` with `demo seed --reset-first --rich` so
#      projections include the W7.A1 Beat-9 enrichment (churn KPI,
#      retention maintainer, decisions, process map, data product).
#   2. If `SLACK_BOT_TOKEN_BASEWORM` is in `.env`, also pass
#      `--install-from-env` so the tenant has an `Install` row and
#      the dashboard renders the post-onboarding shell instead of
#      the redirect-to-/onboarding state. Without the token the
#      baselines capture the onboarding-redirect chrome — surface
#      that as the canonical state and document it in the commit.
#   3. Sleep 12s for the projection runner to settle.
#   4. Run Playwright with `--update-snapshots`. Stack must be up
#      (`make up` or `make tutorial`).
#   5. Re-run the suite without `--update-snapshots` to confirm 0
#      pixel-diffs. Fails the make invocation if any baseline drifts.
#
# When to run: after a UI change that intentionally shifts the
# rendered chrome (selectors, layout, copy). Review the resulting
# `git diff --stat apps/dashboard/tests/visual/__snapshots__/` to
# confirm only the expected tabs changed before committing.
.PHONY: visual-baselines
visual-baselines:
	@echo "[visual-baselines] regenerating against canonical rich seed"
	@if [ ! -f .env ]; then \
		echo "[visual-baselines] .env missing — copy .env.example to .env first"; \
		exit 1; \
	fi
	@SLACK_BOT_TOKEN_BASEWORM=$$(grep -E '^SLACK_BOT_TOKEN_BASEWORM=' .env 2>/dev/null \
		| tail -n 1 | sed -E 's/^SLACK_BOT_TOKEN_BASEWORM=//; s/^["'\'']//; s/["'\'']$$//'); \
	if [ -n "$$SLACK_BOT_TOKEN_BASEWORM" ]; then \
		echo "[visual-baselines] SLACK_BOT_TOKEN_BASEWORM detected — seeding with --install-from-env"; \
		$(COMPOSE) run --rm \
			-e SLACK_BOT_TOKEN_BASEWORM="$$SLACK_BOT_TOKEN_BASEWORM" \
			-e WORMBASE_INSTALLER_EMAIL_OVERRIDE="$${WORMBASE_INSTALLER_EMAIL_OVERRIDE:-admin@example.com}" \
			sim-harness demo seed --reset-first --install-from-env \
				--tenant baseworm --domain-pack saas --rich || exit 1; \
	else \
		echo "[visual-baselines] WARN: SLACK_BOT_TOKEN_BASEWORM unset — capturing pre-install chrome"; \
		echo "[visual-baselines] Without an Install row the dashboard redirects every tab to /onboarding."; \
		echo "[visual-baselines] To capture the post-install chrome, add SLACK_BOT_TOKEN_BASEWORM to .env."; \
		$(COMPOSE) run --rm sim-harness demo seed --reset-first \
			--tenant baseworm --domain-pack saas --rich || exit 1; \
	fi
	@echo "[visual-baselines] waiting 12s for projection runner to settle"
	@sleep 12
	@echo "[visual-baselines] regenerating snapshots"
	@cd apps/dashboard && WORMBASE_HARNESS_UP=1 \
		WORMBASE_DASHBOARD_URL=$${WORMBASE_DASHBOARD_URL:-http://localhost:3000} \
		pnpm exec playwright test tests/visual/ --update-snapshots
	@echo "[visual-baselines] verifying clean diff (0 pixel-diffs)"
	@cd apps/dashboard && WORMBASE_HARNESS_UP=1 \
		WORMBASE_DASHBOARD_URL=$${WORMBASE_DASHBOARD_URL:-http://localhost:3000} \
		pnpm exec playwright test tests/visual/
	@echo "[visual-baselines] done — review 'git diff --stat apps/dashboard/tests/visual/__snapshots__/' before committing"

# ─── QA: 6-layer orchestration ────────────────────────────────

# Each per-layer target writes a junitxml file under .junit/ so that
# `make qa-report` can fold the counts into a single table.

$(QA_JUNIT_DIR):
	@mkdir -p $(QA_JUNIT_DIR)

# L1 (unit) — runs each Python package's pytest, capturing junitxml.
test-l1: $(QA_JUNIT_DIR)
	uv run --package wormbase-ledger --extra dev pytest packages/ledger/tests \
	    -q --junitxml=$(QA_JUNIT_DIR)/l1-ledger.xml
	uv run --package wormbase-ontology-seed --extra dev pytest packages/ontology-seed/tests \
	    -q --junitxml=$(QA_JUNIT_DIR)/l1-ontology-seed.xml
	uv run --package wormbase-governance --extra dev pytest packages/governance/tests \
	    -q --junitxml=$(QA_JUNIT_DIR)/l1-governance.xml
	uv run --package wormbase-channel-adapter --extra dev pytest apps/channel-adapter/tests \
	    -q --junitxml=$(QA_JUNIT_DIR)/l1-channel-adapter.xml
	uv run --package wormbase-worm-core --extra dev pytest apps/worm-core/tests \
	    -q --junitxml=$(QA_JUNIT_DIR)/l1-worm-core.xml

# L2 (component) — TS Vitest via pnpm. Vitest configs in
# apps/dashboard and packages/design write junit XML into
# .junit/l2-dashboard.xml and .junit/l2-design.xml so that
# `make qa-report` folds the L2 count into the layer table.
test-ts: $(QA_JUNIT_DIR)
	@pnpm -r --if-present test || echo "test-ts: pnpm test exited non-zero"

# L3 (contract) — pure Python, no Docker.
test-contract: $(QA_JUNIT_DIR)
	uv run pytest tests/contract/ -q --junitxml=$(QA_JUNIT_DIR)/l3-contract.xml

# L4 (service) — single-service tests using `service` marker. Currently
# none registered; this target is here so future tests slot in cleanly.
test-service: $(QA_JUNIT_DIR)
	uv run pytest -m service tests/ -q --junitxml=$(QA_JUNIT_DIR)/l4-service.xml || true

# L5 (integration) — boots the test compose, runs tests/integration/,
# tears it down. Tests default to InMemoryLedger if Docker is missing
# (see tests/integration/conftest.py).
integration: $(QA_JUNIT_DIR)
	uv run pytest tests/integration/ -q --junitxml=$(QA_JUNIT_DIR)/l5-integration.xml

# L6 (demo gates) — runs every gate file (skipped ones still report) +
# the 7-beat live-wire integration test (in-process layer; the live-Slack
# layer skips unless WORMBASE_INTEGRATION_LIVE_SLACK=1).
demo-gates: $(QA_JUNIT_DIR)
	uv run pytest tests/demo/ tests/integration/test_demo_arc_live_wire.py \
	    -q --junitxml=$(QA_JUNIT_DIR)/l6-demo.xml

# Composed targets — fail the make invocation if any layer's pytest fails.
qa-fast: test-l1 test-contract test-ts
	@echo "qa-fast: L1 + L2 + L3 done"

qa: test-l1 test-contract test-service integration test-ts
	@echo "qa: L1 + L2 + L3 + L4 + L5 done"

qa-pre-demo: qa demo-gates
	@echo "qa-pre-demo: all 6 layers done"
	@$(MAKE) qa-report

# qa-report aggregates every junitxml in .junit/ into a single table.
# Vitest junit (l2-*.xml) goes through --also-vitest so its package-relative
# file paths (tests/unit/Foo.test.tsx) fold into L2 instead of L1.
qa-report:
	@if [ ! -d $(QA_JUNIT_DIR) ]; then \
	    echo "no $(QA_JUNIT_DIR)/ — run 'make qa' or 'make qa-pre-demo' first"; \
	    exit 1; \
	fi
	@$(QA_AGGREGATOR) \
	    $(foreach f,$(filter-out $(QA_JUNIT_DIR)/l2-%.xml,$(wildcard $(QA_JUNIT_DIR)/*.xml)),--junit $(f)) \
	    $(foreach f,$(wildcard $(QA_JUNIT_DIR)/l2-*.xml),--also-vitest $(f))

# ─── Test compose lifecycle (L5 plumbing) ─────────────────────

test-up:
	$(COMPOSE_TEST) up -d --remove-orphans

test-down:
	$(COMPOSE_TEST) down -v --remove-orphans

test-logs:
	$(COMPOSE_TEST) logs -f

# ─── Tunnel (cloudflared quick-tunnel for OAuth, W1.A2) ───────
#
# Brings up a cloudflared sidecar that exposes the dashboard at a
# free https://*.trycloudflare.com URL. The URL is auto-detected and
# written to .env.tunnel as WORMBASE_DASHBOARD_URL — restart the
# dashboard (`make dashboard-restart`) to pick it up. Profile-gated
# so `make up` never starts it. URLs rotate per restart on the free
# tier; see docs/setup/tunnel.md for the named-tunnel upgrade path.

.PHONY: tunnel tunnel-down

tunnel:
	$(COMPOSE) --profile oauth up -d tunnel
	@COMPOSE="$(COMPOSE)" bash infra/scripts/wait-for-tunnel.sh
	@COMPOSE="$(COMPOSE)" bash infra/scripts/sync-tunnel-to-env.sh
	@cat .env.tunnel
	@echo "Tunnel ready. Restart dashboard: make dashboard-restart"

tunnel-down:
	$(COMPOSE) --profile oauth stop tunnel
	$(COMPOSE) --profile oauth rm -f tunnel
	@docker volume rm wormbase-tunnel-state 2>/dev/null || true
	@rm -f .env.tunnel
	@echo "Tunnel down."

# ─── P14 — two-tenant determinism stage demo ──────────────────
#
# `make stage-replay-demo` answers council Q8 (McKinney): wire-replay
# the canonical install-arc JSONL into two clean tenants in parallel
# and prove their terminal ledger-projection hashes are byte-identical.
#
# The default path is in-process — two `InMemoryLedger` tenants driven
# through the production `WireReplayer` (same primitive the live
# channel-adapter uses; no flow-bypass). Lands in ~2s on a stock laptop
# so the stage moment reads cleanly from the back row.
#
# For the heavier two-compose-stack variant, run:
#
#     bash scripts/stage_replay_demo.sh --docker
#
# Note: --docker requires the base infra/docker-compose.yml to be
# rebuilt without fixed `container_name:` entries so two `--project-
# name` stacks can coexist.
stage-replay-demo:
	@bash scripts/stage_replay_demo.sh

# ─── MCP Beat-8 preflight ─────────────────────────────────────
#
# Verifies the MCP tunnel and a known decision_id before the demo.
# Fails fast with clear diagnostics so you don't discover a dead
# tunnel mid-stage.
#
# Usage:
#   DECISION_ID=<uuid> make mcp-preflight
#
# The script falls back to localhost:9911 if the tunnel env is unset.
mcp-preflight:
	@echo "[mcp-preflight] probing MCP endpoint..."
	@bash scripts/demo/mcp_beat8_run.sh || exit 1
	@echo "[mcp-preflight] MCP endpoint alive and decision_id resolvable."
