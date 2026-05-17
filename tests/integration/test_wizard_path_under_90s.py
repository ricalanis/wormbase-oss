"""L6 demo gate **r** of PRD §17.7 — wizard path under 90 seconds.

After the user picks "Dashboard wizard" in /onboarding/setup-mode/choose,
the dashboard's Tier 2 + Tier 3 forms must complete in ≤ 90 seconds
of normal click-through.

Flow under test:
  1. Seed install + wizard mode.
  2. POST to /api/onboarding/setup-mode with mode=wizard.
  3. Drive Tier 2 (domain pack pick + admin invites + classification
     defaults) via dashboard API.
  4. Drive Tier 3 (KPI tree).
  5. Assert emit_setup_completed lands ≤ 90s after t0.

Requires the docker-compose harness; no Slack dependency (wizard is
fully GUI-driven).
"""

from __future__ import annotations

import os

import pytest


def _harness_running() -> bool:
    return os.environ.get("WORMBASE_HARNESS_UP", "").strip() == "1"


@pytest.mark.skipif(
    not _harness_running(),
    reason=(
        "L6 gate r (wizard path ≤ 90s) needs the full docker-compose "
        "harness. Set WORMBASE_HARNESS_UP=1 after `make up` to enable."
    ),
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_wizard_path_under_90s() -> None:
    """Gate **r**: Wizard T2 + T3 in ≤ 90s normal click-through."""
    raise NotImplementedError(
        "Pending: harness wiring for the wizard click-through driver. "
        "Implementation lands once WORMBASE_HARNESS_UP=1 is wired into "
        "the make targets."
    )
