"""L5 integration gate **q** of PRD §17.7 — bot-path 5-step ≤ 3 minutes.

Drive a scripted 5-answer conversation through the
SetupConversationLoop and assert it emits emit_setup_completed within
3 minutes of the first DM. Each step's answer is replied via the live
Slack workspace (a sim persona DMs the worm); the loop parses, writes
the corresponding ledger entry, advances the cursor, posts the next
question, and so on.

Flow under test:
  1. Seed install + bot mode (same as gate p).
  2. SetupConversationLoop posts the first question.
  3. Sim-harness Slack persona DMs the answer "saas".
  4. Loop advances; posts the classification_default question.
  5. Persona DMs "internal".
  6. Loop posts invite_admins question.
  7. Persona DMs "@bob @carol".
  8. Loop posts first_kpi question.
  9. Persona DMs "Q3 net revenue".
  10. Loop posts the done step + emit_setup_completed.
  11. Assert emit_setup_completed lands ≤ 180s after t0.

Requires the same preconditions as gate p plus a sim Slack persona.
"""

from __future__ import annotations

import os

import pytest


def _live_slack_available() -> bool:
    return bool(
        os.environ.get("SLACK_BOT_TOKEN_BASEWORM", "").strip()
        and os.environ.get("WORMBASE_HARNESS_UP", "").strip() == "1",
    )


@pytest.mark.skipif(
    not _live_slack_available(),
    reason=(
        "L5 gate q (bot path 5-step ≤ 3min) needs live Slack + harness "
        "+ sim-harness persona writer. Set SLACK_BOT_TOKEN_BASEWORM + "
        "WORMBASE_HARNESS_UP=1 to enable."
    ),
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_bot_path_completes_under_3_minutes() -> None:
    """Gate **q**: 5-step scripted bot conversation completes ≤ 3min."""
    raise NotImplementedError(
        "Pending: sim-harness persona scripted-DM driver. The unit-level "
        "5-step end-to-end coverage in apps/worm-core/tests/"
        "test_setup_conversation.py::test_loop_completes_full_5_step_"
        "conversation already proves the loop's logic; this gate covers "
        "the live-Slack timing budget."
    )
