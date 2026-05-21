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

# Copy the entire workspace. uv sync --frozen requires every member of
# [tool.uv.workspace] to be discoverable; sweeping packages/ + apps/ in
# one shot keeps the Dockerfile from drifting when members are added.
# (personas.yml + scenarios/ + fixtures/ under apps/sim-harness/ are
# also bind-mounted at runtime; this baked copy is the cold-start
# fallback.)
COPY pyproject.toml uv.lock README.md /workspace/
COPY packages /workspace/packages
COPY apps /workspace/apps

RUN uv sync --package wormbase-sim-harness --no-dev --frozen

ENV WORMBASE_SIM_HARNESS_ROOT=/workspace/apps/sim-harness \
    WORMBASE_TENANT_ID=baseworm

ENTRYPOINT ["uv", "run", "--package", "wormbase-sim-harness", "wormbase"]
CMD ["--help"]
