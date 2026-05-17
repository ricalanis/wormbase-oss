# Hermes Agent — H1 spike image.
#
# Per docs/superpowers/specs/2026-04-27-openclaw-to-hermes-migration.md §5
# Phase 0 (the GO/NO-GO gate). Stands up alongside the existing OpenClaw
# service so we can verify Hermes's hook system fires reliably on every
# inbound Slack message.
#
# Hermes upstream: https://github.com/NousResearch/hermes-agent (MIT).
# The package is NOT on PyPI; install is via `uv pip install -e .[all]`
# from the upstream git checkout. We mirror that pattern here, pinning
# to a calendar-versioned release tag.
#
# Note: the migration spec referenced "v0.11.0" (the codename in
# RELEASE_v0.11.0.md), but the actual git tags use calendar versioning
# (v<YEAR>.<MONTH>.<DAY>). The H1 spike pins v2026.4.23 — that's the
# tag the spec was anchored to.
#
# Multi-tenancy: Hermes uses ONE app token + per-workspace bot tokens.
# Comma-separated SLACK_BOT_TOKEN list, or ~/.hermes/slack_tokens.json
# mapping team-id → bundle. The spike is single-tenant (`baseworm`); we
# pass the same SLACK_BOT_TOKEN_BASEWORM env var through.
#
# Hooks: ~/.hermes/hooks/<name>/HOOK.yaml + handler.py. The wire-tap hook
# (mounted at runtime, see docker-compose) registers handlers for the
# `agent:start` event — that fires on every inbound message that reaches
# the agent loop. See gateway/hooks.py + gateway/run.py:4894 in upstream.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# uv matches the rest of the workspace toolchain. Pinned for build
# reproducibility; bump in lockstep with apps/channel-adapter/Dockerfile.
RUN pip install --no-cache-dir uv==0.4.30

# System deps Hermes needs at runtime: git for the upstream clone, curl
# for healthchecks, ca-certs for TLS to Slack/Ollama.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      git curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/hermes

# Clone Hermes at v0.11.0 — the spec-pinned version. The repo carries
# its own pyproject.toml; we install it as an editable package so the
# `hermes` CLI lands on PATH.
#
# Network resilience: same retry posture as the OpenClaw image — first
# OrbStack boot can hit slow git/pip routing.
ARG HERMES_REF=v2026.4.23
RUN git clone --depth 1 --branch "${HERMES_REF}" \
      https://github.com/NousResearch/hermes-agent.git . \
 && uv venv \
 && uv pip install --no-cache-dir -e ".[all]" \
 || (echo "hermes install failed — see logs above" >&2 && exit 1)

# Make the venv binaries discoverable.
ENV PATH="/opt/hermes/.venv/bin:${PATH}"

# Hermes home — mounted as a named volume in docker-compose so config,
# slack_tokens.json, and hooks/ survive restarts.
ENV HERMES_HOME=/opt/data
RUN mkdir -p /opt/data/hooks /opt/data/logs

# Spike entrypoint. Renders a minimal config from env, copies the
# wire-tap hook into ~/.hermes/hooks/, and execs `hermes gateway run`.
COPY entrypoint.sh /usr/local/bin/wormbase-hermes-entrypoint.sh
RUN chmod +x /usr/local/bin/wormbase-hermes-entrypoint.sh

# Hermes gateway port — distinct from OpenClaw's 18789 so the two run
# alongside each other during the spike. Hermes's default control surface
# is the dashboard (9119); the gateway itself doesn't bind a TCP port
# unless API_SERVER_HOST is set, but we expose 9120 for /healthz parity.
EXPOSE 9120

ENTRYPOINT ["/usr/local/bin/wormbase-hermes-entrypoint.sh"]
