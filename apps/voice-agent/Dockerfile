# wormbase-voice-agent — ElevenLabs ↔ Kimi bridge service.
#
# FastAPI service exposing /webhook/elevenlabs (per-turn LLM hook),
# /webhook/elevenlabs/session-start, /webhook/elevenlabs/session-end,
# and /healthz. Build context is the project root so workspace deps
# (packages/ledger and friends) resolve correctly:
#
#   docker compose build voice-agent
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# uv: fast, reproducible installs (matches the channel-adapter / worm-core image).
RUN pip install --no-cache-dir uv==0.5.13

WORKDIR /workspace

# Copy workspace skeleton: root pyproject + lock + EVERY workspace member
# pyproject.toml. uv requires every member listed in the root's
# [tool.uv.workspace] block to be discoverable at build time, even if
# we only install one of them. Add new members here when the workspace
# grows (parallel to apps/channel-adapter/Dockerfile).
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

# Source. We bring in everything voice-agent transitively needs at runtime;
# uv only resolves what's declared but copying source lets the workspace
# resolution find the wheels it builds.
COPY packages/ledger/src /workspace/packages/ledger/src
COPY packages/governance/src /workspace/packages/governance/src
COPY packages/ontology-seed/src /workspace/packages/ontology-seed/src
COPY apps/voice-agent/src /workspace/apps/voice-agent/src

# Install only the voice-agent package and its workspace deps (--no-dev
# keeps the image small).
RUN uv sync --package wormbase-voice-agent --no-dev --frozen

ENV PATH="/workspace/.venv/bin:${PATH}"

# Demo audio storage root. Production swaps this for S3/MinIO; see
# apps/voice-agent/README.md "Demo-day prerequisites".
ENV WORMBASE_VOICE_AUDIO_DIR=/tmp/voice-audio
RUN mkdir -p /tmp/voice-audio

EXPOSE 8090

ENTRYPOINT ["wormbase-voice-agent"]
CMD ["serve", "--port", "8090"]
