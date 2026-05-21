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

# Copy the entire workspace. uv sync --frozen requires every member of
# [tool.uv.workspace] to be discoverable, so sweeping packages/ + apps/
# in one shot keeps the Dockerfile from drifting when members are
# added (the per-package enumeration here was missing wormbase-agent-
# gateway and wormbase-catalog-mirror as of 2026-05-20).
COPY pyproject.toml uv.lock README.md /workspace/
COPY packages /workspace/packages
COPY apps /workspace/apps

# Install only the channel-adapter package and its workspace deps.
RUN uv sync --package wormbase-channel-adapter --no-dev --frozen

# Persistent state lives here; mount as a tmpfs/volume in compose.
RUN mkdir -p /var/lib/wormbase-channel-adapter

ENV WORMBASE_ADAPTER_STATE_PATH=/var/lib/wormbase-channel-adapter/state.json \
    OPENCLAW_SESSIONS_PATH=/openclaw-state/agents/main/sessions \
    WORMBASE_TENANT_ID=baseworm

ENTRYPOINT ["uv", "run", "--package", "wormbase-channel-adapter", "wormbase-channel-adapter"]
CMD ["run"]
