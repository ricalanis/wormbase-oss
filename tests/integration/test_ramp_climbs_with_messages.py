"""L5 integration: conversational ramp axis climbs as messages arrive.

Starts from a fresh tenant (warmup just ran), injects N=3 channel
messages via the lurker, then computes the ramp and asserts:

  conversational > 0

This guards the connection between the lurker (chat_received emission)
and the ramp's conversational axis. If anyone changes the tool name
emitted by the lurker, this test catches it before integration.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_three_messages_lift_conversational_axis_from_zero(
    worm_core_integration, integration_ledger, integration_company_id,
) -> None:
    from wormbase_core.lurker import SlackLurker

    worm = worm_core_integration

    # Baseline: conversational starts at 0.0 (no messages yet).
    state0 = await worm.ramp.compute(
        integration_company_id, write_snapshot=False,
    )
    assert state0.conversational == 0.0

    # Drive 3 chat_received writes through the lurker.
    lurker = SlackLurker(
        ledger=integration_ledger,
        company_id=integration_company_id,
        pipeline=worm.pipeline,
        app_token="xapp-fake",
        bot_token="xoxb-fake",
    )
    for i in range(3):
        event = {
            "channel": "C0CONV",
            "user": f"U_user_{i}",
            "ts": f"1745619360.000{i:03d}",
            "event_ts": f"1745619360.000{i:03d}",
            "client_msg_id": f"msg-{i}",
            "text": f"hello message {i}",
            "type": "message",
        }
        await lurker._handle_event(  # noqa: SLF001
            event, body={"event": event}, kind="channel_message",
        )

    # Recompute the ramp; conversational axis must have moved off zero.
    state1 = await worm.ramp.compute(
        integration_company_id, write_snapshot=False,
    )
    assert state1.conversational > 0.0, (
        f"conversational axis stuck at 0 despite 3 messages; full ramp: "
        f"{state1.as_dict()}"
    )
