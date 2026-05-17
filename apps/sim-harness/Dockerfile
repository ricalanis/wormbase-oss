# WormBase sim harness.
#
# Drives a real Slack workspace with scripted persona posts. Talks to
# the ledger only for post-run acceptance checks.
#
# Build with the project root as the build context so the workspace
# packages/ledger and apps/sim-harness are both visible:
#
#   docker compose build sim-harness

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir uv==0.4.30

WORKDIR /workspace

# Manifest layer for cache.
COPY pyproject.toml uv.lock README.md /workspace/
COPY packages/ledger/pyproject.toml /workspace/packages/ledger/
COPY packages/governance/pyproject.toml /workspace/packages/governance/
COPY packages/ontology-seed/pyproject.toml /workspace/packages/ontology-seed/
COPY packages/inference-router/pyproject.toml /workspace/packages/inference-router/
COPY packages/connectors/pyproject.toml /workspace/packages/connectors/
COPY packages/channel-adapters/pyproject.toml /workspace/packages/channel-adapters/
COPY packages/reactivities/pyproject.toml /workspace/packages/reactivities/
COPY apps/channel-adapter/pyproject.toml /workspace/apps/channel-adapter/
COPY apps/worm-core/pyproject.toml /workspace/apps/worm-core/
COPY apps/sim-harness/pyproject.toml /workspace/apps/sim-harness/
COPY apps/voice-agent/pyproject.toml /workspace/apps/voice-agent/

# Source for every transitive workspace dep. sim-harness depends on
# worm-core (for tenant_to_uuid + flow types), which depends on
# governance + ontology-seed. ontology-seed has a hatchling
# forced-include for its data/ directory, so that must be copied too.
# Block B added wormbase-channel-adapters as a worm-core dep, so its
# src tree must be visible too.
COPY packages/ledger/src /workspace/packages/ledger/src
COPY packages/governance/src /workspace/packages/governance/src
COPY packages/ontology-seed/src /workspace/packages/ontology-seed/src
COPY packages/ontology-seed/data /workspace/packages/ontology-seed/data
COPY packages/channel-adapters/src /workspace/packages/channel-adapters/src
# inference-router is a stub package (pyproject only, no src yet) so no
# source copy is needed for the workspace solver to resolve it.
COPY apps/worm-core/src /workspace/apps/worm-core/src
COPY apps/channel-adapter/src /workspace/apps/channel-adapter/src
COPY apps/sim-harness/src /workspace/apps/sim-harness/src

# Personas / scenarios / fixtures (also bind-mounted at runtime so updates
# don't require a rebuild — this baked copy is the cold-start fallback).
COPY apps/sim-harness/personas.yml /workspace/apps/sim-harness/personas.yml
COPY apps/sim-harness/scenarios /workspace/apps/sim-harness/scenarios
COPY apps/sim-harness/fixtures /workspace/apps/sim-harness/fixtures

RUN uv sync --package wormbase-sim-harness --no-dev --frozen

ENV WORMBASE_SIM_HARNESS_ROOT=/workspace/apps/sim-harness \
    WORMBASE_TENANT_ID=baseworm

ENTRYPOINT ["uv", "run", "--package", "wormbase-sim-harness", "wormbase"]
CMD ["--help"]
