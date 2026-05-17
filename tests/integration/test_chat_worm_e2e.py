"""e2e: chat_received -> ChatReceivedReactivity -> relevance -> ChatReply ->
4-entry chat_reply_* PEVR cycle lands.

Task I1 of the chat-worm extraction plan
(docs/superpowers/plans/2026-05-03-chat-worm-extraction.md, lines 5010-5227).

Smoke test for the full Wave B composition: an inbound `chat_received`
ledger entry flows through the W5a ReactivityRegistry -> the chat-worm
Reactivities constructed by `wire_chat_for_install` fire ->
`MentionResponseReactivity` calls `_LedgerChatReply.speak` -> the
four-entry chat_reply_* PEVR cycle lands on the ledger. Channel-adapter
is stubbed (records the send call, returns a MessageRef); the four
chat-driven flows are stubbed (we're testing the wiring, not the flow
internals).

Per O-B2 (deferred-backlog Block C, 2026-05-04): chat-worm Reactivities
take their service dependencies (chat_reply, chat_store, relevance_gate,
flow_dispatcher, semantic_classifier, mentioned_in_conversation_flow) as
constructor kwargs threaded through `make_chat_reactivities` —
`wire_chat_for_install` does the threading, so the registry's stock
dispatch (which only injects `extras={"reactivity_id": rid}`) is
sufficient. The previous `_patch_registry_extras` bridge is removed; the
production cli.py path and the test path now share the same construction
seam.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from wormbase_chat_presence import Install, wire_chat_for_install
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.registry import ReactivityRegistry


@pytest.mark.asyncio
async def test_e2e_chat_mention_lands_chat_reply_pevr_cycle() -> None:
    company = uuid4()
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=company)
    install = Install(id=company, platform="slack")

    # Stub the channel-adapter's send (records the call, returns a MessageRef).
    sent: list[dict[str, Any]] = []

    class _StubAdapter:
        platform = "slack"

        async def send(self, handle: Any, channel: str, msg: Any) -> Any:
            sent.append({"channel": channel, "msg": msg})
            return SimpleNamespace(message_id=f"slack_{len(sent)}")

    # Stub flows; we're testing chat-worm wiring, not flow internals.
    class _StubFlow:
        async def on_file_drop(self, infra: Any) -> Any:
            return None

        async def on_dm(self, infra: Any) -> Any:
            return None

        async def on_proactive_mention(self, infra: Any) -> Any:
            return SimpleNamespace(
                channel_id=infra.channel_id, offer_text="offer!",
            )

    # wire_chat_for_install threads chat_reply / chat_store / relevance_gate
    # / flow_dispatcher / mentioned_in_conversation_flow into each
    # Reactivity via factory kwargs (O-B2). The
    # MentionResponseReactivity that fires below reads chat_reply +
    # chat_store from its own instance attrs, NOT from
    # ReactivityContext.extras.
    await wire_chat_for_install(
        install=install,
        ledger=ledger,
        reactivity_registry=registry,
        drop_and_profile=_StubFlow(),
        credential_in_dm=_StubFlow(),
        mentioned_in_conversation=_StubFlow(),
        channel_adapter=_StubAdapter(),
        channel_adapter_handle="handle",
        mention_handle="@worm",
    )

    # Drive a chat_received entry that mentions @worm.
    await ledger.write(
        company_id=company,
        propose={
            "target_kind": "chat_received",
            "ref_id": str(uuid4()),
            "reason": "test",
            "proposed_by": "channel_adapter",
        },
        execute_fn=lambda: {
            "tool": "channel_adapter.emit_chat_received",
            "args": {
                "platform": "slack",
                "channel_id": "C1",
                "message_id": "msg_in_1",
                "text": "@worm please help",
                "sender_person": str(uuid4()),
            },
            "result_ref": "msg_in_1",
        },
        verify_fn=lambda _e: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        timestamp=datetime.now(UTC),
        quadrant="active_probabilistic",
    )

    # Dispatch the new entry through the registry — this fires
    # MentionResponseReactivity, which calls chat_reply.speak.
    rows = await ledger.fetch(company)
    chat_received_row = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "channel_adapter.emit_chat_received"
    ][-1]
    await registry.dispatch(chat_received_row)

    # Assert: the channel adapter was called once.
    assert len(sent) >= 1, f"adapter.send was never invoked; sent={sent}"

    # Assert: a chat_reply_proposed propose envelope landed.
    rows = await ledger.fetch(company)
    proposes = [
        r for r in rows
        if r["kind"] == "propose"
        and r["payload"].get("target_kind") == "chat_reply_proposed"
    ]
    assert len(proposes) >= 1

    # Assert: a chat_reply_executed execute envelope landed.
    executes = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_chat_reply_executed"
    ]
    assert len(executes) >= 1

    # Assert: the verify entry recorded passed=True.
    verifies = [
        r for r in rows
        if r["kind"] == "verify"
        and any(
            "channel_adapter_send" in str(c.get("name", ""))
            for c in r["payload"].get("checks", [])
        )
    ]
    assert len(verifies) >= 1
    assert verifies[-1]["payload"]["passed"] is True

    # Assert: the resolve entry recorded outcome=keep with chat_reply rationale.
    resolves = [
        r for r in rows
        if r["kind"] == "resolve"
        and r["payload"].get("outcome") == "keep"
        and "chat_reply" in str(r["payload"].get("rationale", ""))
    ]
    assert len(resolves) >= 1
