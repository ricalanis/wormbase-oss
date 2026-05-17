# WormBase channel-ledger adapter.
#
# Tails OpenClaw session JSONL files mounted from the openclaw-state
# docker volume and writes chat_received / chat_sent ledger entries to
# Postgres via wormbase_ledger.
#
# Build with the project root as the build context so the workspace
# packages/ledger and apps/channel-adapter are both visible:
#
#   docker compose build channel-adapter

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# uv is fast and matches the host toolchain.
RUN pip install --no-cache-dir uv==0.4.30

WORKDIR /workspace

# Copy only the manifests first so the dep layer can be cached.
# uv requires every workspace member listed in the root pyproject.toml's
# [tool.uv.workspace] block to have a discoverable pyproject.toml at
# build time, even if we only install one of them. Add new members here
# when the workspace grows.
COPY pyproject.toml uv.lock README.md /workspace/
COPY packages/ledger/pyproject.toml /workspace/packages/ledger/
COPY packages/governance/pyproject.toml /workspace/packages/governance/
COPY packages/ontology-seed/pyproject.toml /workspace/packages/ontology-seed/
COPY packages/inference-router/pyproject.toml /workspace/packages/inference-router/
COPY packages/connectors/pyproject.toml /workspace/packages/connectors/
COPY packages/channel-adapters/pyproject.toml /workspace/packages/channel-adapters/
COPY packages/reactivities/pyproject.toml /workspace/packages/reactivities/
COPY packages/lake-maintainer/pyproject.toml /workspace/packages/lake-maintainer/
COPY packages/wormbase-tools/pyproject.toml /workspace/packages/wormbase-tools/
COPY packages/wormbase-tools-test/pyproject.toml /workspace/packages/wormbase-tools-test/
COPY packages/wormbase-identity-tracker/pyproject.toml /workspace/packages/wormbase-identity-tracker/
COPY packages/wormbase-chat-presence/pyproject.toml /workspace/packages/wormbase-chat-presence/
COPY packages/wormbase-research-loop/pyproject.toml /workspace/packages/wormbase-research-loop/
COPY packages/wormbase-process-extractor/pyproject.toml /workspace/packages/wormbase-process-extractor/
COPY apps/channel-adapter/pyproject.toml /workspace/apps/channel-adapter/
COPY apps/worm-core/pyproject.toml /workspace/apps/worm-core/
COPY apps/sim-harness/pyproject.toml /workspace/apps/sim-harness/
COPY apps/voice-agent/pyproject.toml /workspace/apps/voice-agent/

# Source. The new packages (connectors + channel-adapters) need their src
# trees too because channel-adapter depends on wormbase-channel-adapters
# (Block B B6 refactor extracted SlackChannelAdapter into the new
# package).
COPY packages/ledger/src /workspace/packages/ledger/src
COPY packages/channel-adapters/src /workspace/packages/channel-adapters/src
COPY apps/channel-adapter/src /workspace/apps/channel-adapter/src

# Install only the channel-adapter package and its workspace deps.
RUN uv sync --package wormbase-channel-adapter --no-dev --frozen

# Persistent state lives here; mount as a tmpfs/volume in compose.
RUN mkdir -p /var/lib/wormbase-channel-adapter

ENV WORMBASE_ADAPTER_STATE_PATH=/var/lib/wormbase-channel-adapter/state.json \
    OPENCLAW_SESSIONS_PATH=/openclaw-state/agents/main/sessions \
    WORMBASE_TENANT_ID=baseworm

ENTRYPOINT ["uv", "run", "--package", "wormbase-channel-adapter", "wormbase-channel-adapter"]
CMD ["run"]
