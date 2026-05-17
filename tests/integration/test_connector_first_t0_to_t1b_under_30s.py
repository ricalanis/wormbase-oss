"""L6 demo gate **o** of PRD §17.7 — connector-first T0→T1b under 30s.

From the operator landing on /onboarding to the medallion cascade
firing for an uploaded CSV, ≤ 30 seconds. The narrowest credentials
surface is csv_local — drop a file, the worm reads it.

Flow under test:
  1. POST /api/onboarding/upload with a small CSV (multipart) +
     IdentityForm payload.
  2. Assert 200 + redirect within 30s.
  3. Poll the ledger for the medallion cascade chain:
       emit_install_completed
         → emit_source_proposed
         → emit_source_bronzed
         → emit_source_silvered
         → emit_source_golded
  4. Assert all five lands within 30s of t0.

Requires the full docker-compose harness (`make up`) plus the
worm-core HTTP API. Skipped cleanly when the harness isn't running.
"""

from __future__ import annotations

import os

import pytest


def _harness_running() -> bool:
    return os.environ.get("WORMBASE_HARNESS_UP", "").strip() == "1"


@pytest.mark.skipif(
    not _harness_running(),
    reason=(
        "L6 demo gate o (connector-first T0→T1b ≤ 30s) needs the full "
        "docker-compose harness + worm-core HTTP API. Set "
        "WORMBASE_HARNESS_UP=1 after `make up` to enable."
    ),
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_connector_first_t0_to_t1b_under_30s() -> None:
    """Gate **o**: CSV upload → cascade-complete in ≤ 30s.

    The flow exercises the new G3 multipart upload path
    (POST /api/onboarding/upload) plus the medallion cascade running
    inside worm-core.
    """
    raise NotImplementedError(
        "Pending: harness wiring for the multipart upload path + the "
        "medallion cascade poll loop. Implementation lands once "
        "WORMBASE_HARNESS_UP=1 is wired into the make targets."
    )
