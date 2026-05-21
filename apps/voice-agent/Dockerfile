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

# Copy the entire workspace. uv sync --frozen requires every member
# listed in the root's [tool.uv.workspace] to be discoverable, so the
# safest path is a single sweep of packages/ + apps/ — that way the
# Dockerfile cannot drift from the workspace block when new members
# are added.
COPY pyproject.toml uv.lock README.md /workspace/
COPY packages /workspace/packages
COPY apps /workspace/apps

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
