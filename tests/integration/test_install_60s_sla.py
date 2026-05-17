"""60-second install SLA — D7 of the production-dashboard plan.

From OAuth callback to first ramp-gauge movement should be ≤ 60 seconds.

This L5 integration test requires the full docker-compose harness
(`make up`) plus the worm-core HTTP API. Until the install endpoint is
deployed and the Tier 0 OAuth route is wired through the harness, the
test is marked skip — the unit-level OAuth handler test in
``apps/dashboard/tests/api/install.test.ts`` covers the route shape.
"""
from __future__ import annotations

import pytest


@pytest.mark.skip(
    reason=(
        "D7 SLA test pending — needs docker-compose harness + worm-core "
        "/api/v1/installs endpoint (not deployed yet). The unit-level "
        "OAuth handler test in apps/dashboard/tests/api/install.test.ts "
        "covers the route shape."
    ),
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_installer_to_aha_in_60s() -> None:
    """From OAuth callback to first ramp-gauge movement, ≤ 60 seconds.

    Flow under test:
      1. POST /onboarding/oauth/slack with simulated installer credentials
      2. Assert 200 within 30s (Tier 1 SLA)
      3. Poll the ledger for an emit_memory_written entry whose
         payload.args.content == "ramp_snapshot"
      4. Assert ramp-snapshot lands within 60s of t0
    """
    raise NotImplementedError
