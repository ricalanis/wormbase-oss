#!/usr/bin/env bash
# scripts/stage_replay_demo.sh — P14 stage demo entrypoint.
#
# Wraps `scripts/stage_replay_demo.py` so a presenter can run a single
# command on stage:
#
#     make stage-replay-demo
#
# behind the curtain this invokes:
#
#     bash scripts/stage_replay_demo.sh [--fixture PATH] [--docker]
#
# The default path is in-process: two `InMemoryLedger` tenants driven
# in parallel through the production `WireReplayer`. Same primitive
# the live channel-adapter uses — no flow-bypass — and ~2s wall-clock
# on stock laptops so the stage moment lands cleanly.
#
# `--docker` opt-in path: spin two `docker compose --project-name`
# stacks (tenant_a / tenant_b) with isolated postgres volumes, replay
# through the channel-adapter container, diff hashes via
# `wormbase verify`. Heavier (~60s warm-up); kept as a switch for the
# operator who wants to prove this on the real wire on the day.
#
# Exit codes
# ----------
# 0  hashes match — determinism confirmed.
# 1  hashes diverged — stop the show, dispatch a debug.
# 2  pre-flight failure (missing fixture, missing python, etc.).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_FIXTURE="${REPO_ROOT}/tests/fixtures/install_arc.jsonl"

FIXTURE="${DEFAULT_FIXTURE}"
USE_DOCKER=0

usage() {
    cat <<EOF
usage: scripts/stage_replay_demo.sh [--fixture PATH] [--docker]

  --fixture PATH   Wire-event JSONL to replay into both tenants.
                   Defaults to tests/fixtures/install_arc.jsonl.
  --docker         Use the heavier two-compose-stack path (one
                   docker compose --project-name per tenant). Default
                   is in-process (fast, same primitive).
  -h, --help       Show this message.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --fixture)
            FIXTURE="$2"
            shift 2
            ;;
        --docker)
            USE_DOCKER=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "[stage-replay-demo] unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ ! -f "${FIXTURE}" ]]; then
    echo "[stage-replay-demo] fixture not found: ${FIXTURE}" >&2
    exit 2
fi

cd "${REPO_ROOT}"

if [[ "${USE_DOCKER}" -eq 1 ]]; then
    # The docker variant is left as a guarded path: it requires the
    # base compose file to support `--project-name` namespacing
    # (i.e. removing fixed `container_name:` entries on the day).
    # Surface that explicitly rather than silently degrading.
    cat <<'EOF' >&2
[stage-replay-demo] --docker path requires --project-name-safe compose.
[stage-replay-demo] The repo's infra/docker-compose.yml currently uses
[stage-replay-demo] fixed container_name: entries which collide across
[stage-replay-demo] project-names. Use the in-process path for the
[stage-replay-demo] stage demo (default), or rebuild compose with the
[stage-replay-demo] container_name lines removed before opting in here.
EOF
    exit 2
fi

# Pick a runner: prefer `uv run` if available (matches make/qa
# conventions); fall back to plain python so the script also works
# in a stripped-down clean-clone environment (e.g. the demo machine
# minutes before showtime).
if command -v uv >/dev/null 2>&1; then
    RUNNER=(uv run python)
else
    RUNNER=(python3)
fi

exec "${RUNNER[@]}" "${SCRIPT_DIR}/stage_replay_demo.py" --fixture "${FIXTURE}"
