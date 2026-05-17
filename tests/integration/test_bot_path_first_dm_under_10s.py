"""L5 integration gate **p** of PRD §17.7 — bot-path first DM ≤ 10s.

After the user picks "Worm in chat" in /onboarding/setup-mode/choose,
the SetupConversationLoop must DM the installer the first setup
question within 10 seconds.

Flow under test:
  1. Seed the ledger with an active Slack install + bot installer Person.
  2. POST to /api/onboarding/setup-mode with mode=bot.
  3. Wait for the SetupConversationLoop to post the first DM
     (the loop posts via SlackChannelAdapter; the channel-adapter
     captures the outbound message as emit_chat_sent).
  4. Assert emit_chat_sent appears in the ledger within 10s of t0
     and its text matches the saas-default.yml first step
     (domain_pack question).

Requires:
  * docker-compose harness running (`make up`)
  * Live SLACK_BOT_TOKEN_BASEWORM env var (real Slack workspace)
  * SetupConversationLoop wired in cli.py (G5 — landed)

Skipped cleanly when any of those preconditions are unmet.
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
        "L5 gate p (bot-path first DM ≤ 10s) needs live Slack + harness. "
        "Set SLACK_BOT_TOKEN_BASEWORM + WORMBASE_HARNESS_UP=1 to enable."
    ),
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_bot_path_first_dm_under_10s() -> None:
    """Gate **p**: User picks bot → worm DMs first question ≤ 10s."""
    raise NotImplementedError(
        "Pending: live Slack workspace fixture + SetupConversationLoop "
        "polling cycle assertion. Implementation lands once the demo "
        "Slack workspace credentials are persisted in CI secrets."
    )
