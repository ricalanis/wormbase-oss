"""L5 integration: lurker captures every channel message, even non-mentions.

The lurker invariant (worm-core/lurker.py): every Slack message in any
channel the worm is subscribed to becomes a `chat_received` ledger
entry, regardless of whether the worm chose to reply.

We avoid spinning up real Socket Mode by calling
``SlackLurker._handle_event`` directly with a synthetic Slack event
dict. The handler invokes the same ``_write_chat_received`` path that
production uses, so this exercises the full Pydantic + ledger write
chain.
"""

from __future__ import annotations

import asyncio
import time

import pytest


@pytest.mark.asyncio
async def test_lurker_writes_chat_received_for_non_mention_within_2s(
    worm_core_integration, integration_ledger, integration_company_id,
) -> None:
    from wormbase_core.lurker import SlackLurker
    from wormbase_core.reactivity import ReactivityPipeline

    pipeline: ReactivityPipeline = worm_core_integration.pipeline

    lurker = SlackLurker(
        ledger=integration_ledger,
        company_id=integration_company_id,
        pipeline=pipeline,
        app_token="xapp-fake-test-token",
        bot_token="xoxb-fake-test-token",
    )

    fake_event = {
        # Important: this is a non-mention plain-message event.
        "channel": "C0DATA",
        "user": "U_observer",
        "ts": "1745619360.000100",
        "event_ts": "1745619360.000100",
        "client_msg_id": "msg-non-mention-1",
        "text": "lunch order arrived",  # no @worm
        "type": "message",
    }

    started = time.monotonic()
    await lurker._handle_event(  # noqa: SLF001 — exercising the contract
        fake_event, body={"event": fake_event}, kind="channel_message",
    )
    elapsed = time.monotonic() - started
    assert elapsed < 2.0, f"lurker handler too slow: {elapsed:.2f}s"

    # Assert the chat_received entry landed in the ledger.
    rows = await integration_ledger.fetch(integration_company_id)
    chat_rows = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] in {"emit_chat_received", "channel_adapter.emit_chat_received"}
    ]
    assert chat_rows, "lurker did not write any chat_received entry"

    # The message content + channel id round-trip into the ledger payload.
    args = chat_rows[-1]["payload"]["args"]
    assert args["channel_id"] == "C0DATA"
    assert args["text"] == "lunch order arrived"

    # And the PEVR sequence is intact: each chat_received write is a 4-row
    # propose/execute/verify/resolve chain.
    propose_rows = [r for r in rows if r["kind"] == "propose"]
    execute_rows = [r for r in rows if r["kind"] == "execute"]
    verify_rows = [r for r in rows if r["kind"] == "verify"]
    resolve_rows = [r for r in rows if r["kind"] == "resolve"]
    # At minimum: one PEVR for the chat_received itself (warmup also
    # writes some, so >=).
    assert len(propose_rows) >= 1
    assert len(execute_rows) >= 1
    assert len(verify_rows) >= 1
    assert len(resolve_rows) >= 1
