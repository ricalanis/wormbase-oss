# wormbase-worm-core — runs the reactivity pipeline + Slack lurker.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# uv for fast, reproducible installs.
RUN pip install --no-cache-dir uv==0.5.13

WORKDIR /workspace

# Copy workspace skeleton. Build context is the repo root (compose
# context: .). We copy the entire packages/ and apps/ trees so the
# Dockerfile cannot drift from `[tool.uv.workspace].members` in the
# root pyproject — uv sync --frozen requires every member to be
# discoverable at build time.
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps ./apps

# Install with the worm-core extras; --no-dev to keep image small.
RUN uv sync --package wormbase-worm-core --no-dev

ENV PATH="/workspace/.venv/bin:${PATH}"

# Default runs the lurker + heartbeat loop.
CMD ["wormbase-worm-core", "run"]
