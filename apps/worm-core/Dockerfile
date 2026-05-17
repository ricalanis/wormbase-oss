# wormbase-worm-core — runs the reactivity pipeline + Slack lurker.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# uv for fast, reproducible installs.
RUN pip install --no-cache-dir uv==0.5.13

WORKDIR /workspace

# Copy workspace skeleton: root pyproject + lock + the packages we
# depend on. Build context is the repo root (set via compose context: .).
COPY pyproject.toml uv.lock ./
COPY packages/ledger ./packages/ledger
COPY packages/inference-router ./packages/inference-router
COPY packages/governance ./packages/governance
COPY packages/ontology-seed ./packages/ontology-seed
COPY packages/connectors ./packages/connectors
COPY packages/channel-adapters ./packages/channel-adapters
COPY packages/reactivities ./packages/reactivities
COPY apps/worm-core ./apps/worm-core
COPY apps/sim-harness ./apps/sim-harness
COPY apps/channel-adapter ./apps/channel-adapter
COPY apps/voice-agent ./apps/voice-agent

# Install with the worm-core extras; --no-dev to keep image small.
RUN uv sync --package wormbase-worm-core --no-dev

ENV PATH="/workspace/.venv/bin:${PATH}"

# Default runs the lurker + heartbeat loop.
CMD ["wormbase-worm-core", "run"]
