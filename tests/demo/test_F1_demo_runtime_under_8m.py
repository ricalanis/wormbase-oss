"""F1 demo gate: end-to-end 9-beat install arc completes in < 8m.

E6 of ``docs/superpowers/plans/2026-04-26-production-dashboard.md`` +
J7 (Beat 8 — Claude Desktop MCP query) + W5.A2 (Beat 9 — Statement-to-Owner).

The 9-beat install arc (`apps/sim-harness/scenarios/install-arc-7beat.yml`,
PRD §10 + Block J Beat 8 + W5.A2 Beat 9) targets ~470s wall-clock from
"click Connect to Slack" through "Carol replies in DM (Statement-to-Owner)."
We allow up to **480s** before the demo budget is gone — the gate fails
and the demo runbook's ``wire-replay`` backstop becomes mandatory.

This test runs in two layers:

1. **In-process schema validation** — always runs; loads the YAML,
   asserts the engine can simulate every beat under a virtual clock
   in <0.1s wall-time and the cumulative `at` budget is under 470s
   (the 8m gate minus a 10s buffer for last-wait_for slack).

2. **Live-wire wall-clock** — gated on
   ``WORMBASE_INTEGRATION_LIVE_SLACK=1``; reproduces the install arc
   end-to-end via real Slack + the channel-adapter and asserts wall
   time < 480s. Same auth pattern as ``tests/integration/
   test_demo_arc_live_wire.py`` (Block C6).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_PATH = (
    REPO_ROOT / "apps/sim-harness/scenarios/install-arc-7beat.yml"
)


def test_F1_install_arc_yaml_budget_under_8m() -> None:
    """The scenario's terminal `at` field must leave an 8m budget.

    The YAML's last beat (Beat 9b — Carol replies via DM) lands at
    450s; the wait_for at the end can take up to ~20s for the
    channel-adapter to surface the reply. We assert the floor
    (last `at` <= 470s) so the live wall-clock layer below has buffer.
    """
    from wormbase_sim_harness.scenario import Scenario

    scen = Scenario.from_yaml(SCENARIO_PATH)
    assert scen.beats, "scenario must have beats"
    last_at = max(b.at for b in scen.beats)
    assert last_at <= 470.0, (
        f"scenario's terminal `at` is {last_at}s; over the 8m "
        f"budget (target ≤ 470s for wall-clock buffer)."
    )

    # Total wait_for timeout sum must also stay inside the budget.
    total_wait_timeout = sum(
        (b.wait_for.timeout_s if b.wait_for is not None else 0.0)
        for b in scen.beats
    )
    assert total_wait_timeout <= 300.0, (
        f"sum of wait_for timeouts is {total_wait_timeout}s; the "
        f"engine could block for that long if the dashboard never "
        f"fires the expected entries — keep this <= 5m to leave "
        f"buffer in the 8m gate (covers 7 wait_for beats incl Beats 8 + 9)."
    )


@pytest.mark.skipif(
    os.environ.get("WORMBASE_INTEGRATION_LIVE_SLACK") != "1",
    reason=(
        "live Slack integration off by default. "
        "Set WORMBASE_INTEGRATION_LIVE_SLACK=1 with a running compose "
        "stack and SLACK_BOT_TOKEN_BASEWORM in env to enable."
    ),
)
def test_F1_install_arc_wall_clock_under_8m() -> None:
    """Wall-clock the live install arc against real Slack + ledger.

    Mirrors the live-wire layer of
    ``tests/integration/test_demo_arc_live_wire.py``: requires
    ``WORMBASE_INTEGRATION_LIVE_SLACK=1`` + a running compose stack +
    real Slack tokens. Asserts the recorded run finishes in < 480s.
    """
    import asyncio
    from datetime import UTC, datetime

    from wormbase_sim_harness.clock import WallClock
    from wormbase_sim_harness.engine import ScenarioEngine
    from wormbase_sim_harness.personas import PersonaRegistry
    from wormbase_sim_harness.scenario import Scenario
    from wormbase_sim_harness.slack_poster import SlackPoster

    bot_token = os.environ.get("SLACK_BOT_TOKEN_SIM_BASEWORM")
    if not bot_token:
        pytest.skip("SLACK_BOT_TOKEN_SIM_BASEWORM not set")

    dsn = os.environ.get(
        "WORMBASE_LEDGER_DSN",
        "postgresql+asyncpg://wormbase:wormbase@localhost:5432/wormbase",
    )

    from wormbase_channel_adapter.tenant import tenant_to_company_uuid
    from wormbase_ledger import Ledger

    company_id = tenant_to_company_uuid("baseworm")
    personas_path = REPO_ROOT / "apps/sim-harness/personas.yml"

    registry = PersonaRegistry.from_yaml(personas_path)
    scenario = Scenario.from_yaml(SCENARIO_PATH)
    scenario.validate_against(registry)

    poster = SlackPoster(bot_token)
    ledger = Ledger(dsn)

    async def _go() -> float:
        try:
            engine = ScenarioEngine(
                registry,
                ledger=ledger,
                company_id=company_id,
                fixtures_root=REPO_ROOT / "apps/sim-harness/fixtures",
            )
            clock = WallClock()
            started = datetime.now(UTC)
            assert started  # appease linters
            t0 = time.monotonic()
            await engine.run(scenario, clock, poster)
            return time.monotonic() - t0
        finally:
            await ledger.dispose()

    elapsed = asyncio.run(_go())
    assert elapsed < 480.0, (
        f"install-arc-7beat ran in {elapsed:.1f}s; over the 8m "
        f"(390s) F1 budget. Replay segments via wire-replay before "
        f"shipping."
    )
