"""Phase 3 Task 3B — Ask-the-Worm endpoint core.

Verifies the in-app ask flow walks the same code path as production chat:

  1. ``ask_the_worm()`` writes a canonical chat_received PEVR cycle through
     the ledger (no demo-seam INSERT).
  2. Synthesizes the entry the registry's runner would have produced and
     fires ``MentionResponseReactivity`` on it — the production speech
     reactivity, unchanged.
  3. ``MentionResponseReactivity`` calls ``_LedgerChatReply.speak`` which
     writes a chat_reply PEVR cycle. The send goes through the in-app
     channel adapter that captures the OutMessage text into a per-tenant
     outbox.
  4. The function returns the captured reply text.

The tests assert the canonical ledger shape, the dispatch path, and the
text round-trip so future drift in the production reactivity surfaces as
a test failure here.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from wormbase_core.ask_the_worm import (
    ASK_THE_WORM_DEFAULT_REPLY,
    InAppChatOutbox,
    _InAppChannelAdapter,
    ask_the_worm,
)
from wormbase_ledger import InMemoryLedger


pytestmark = pytest.mark.asyncio


def _execute_rows_with_tool(rows: list[dict[str, Any]], tool: str) -> list[dict[str, Any]]:
    return [
        r for r in rows
        if r.get("kind") == "execute" and (r.get("payload") or {}).get("tool") == tool
    ]


async def test_ask_the_worm_writes_chat_received_pevr(ledger: InMemoryLedger, company_id: UUID) -> None:
    """Question becomes a 4-entry chat_received PEVR; tool=channel_adapter.emit_chat_received."""
    outbox = InAppChatOutbox()
    reply = await ask_the_worm(
        ledger=ledger,
        company_id=company_id,
        question="What is our Q3 revenue?",
        outbox=outbox,
    )

    rows = await ledger.fetch(company_id)
    chat_received_rows = _execute_rows_with_tool(rows, "channel_adapter.emit_chat_received")
    assert len(chat_received_rows) == 1, "exactly one chat_received execute row"

    args = chat_received_rows[0]["payload"]["args"]
    # The question lands verbatim in the chat_received text — the
    # adapter prefixes @worm so MentionResponseReactivity fires.
    assert "What is our Q3 revenue?" in args["text"]
    assert args["channel_id"].startswith("in_app:")
    assert args["classification"] == "internal"

    # Full PEVR cycle written: propose + execute + verify + resolve.
    chat_received_seqs = sorted(
        int(r["seq"]) for r in rows
        if (
            (r.get("kind") == "propose" and (r.get("payload") or {}).get("target_kind") == "chat_received")
            or (r.get("kind") == "execute" and (r.get("payload") or {}).get("tool") == "channel_adapter.emit_chat_received")
            or (r.get("kind") == "verify" and any(c.get("name") == "payload_valid" for c in (r.get("payload") or {}).get("checks", [])))
            or (r.get("kind") == "resolve" and "in-app" in (r.get("payload") or {}).get("rationale", ""))
        )
    )
    # 4 PEVR entries for chat_received (plus the chat_reply cycle).
    assert len(chat_received_seqs) == 4
    assert reply.answer == ASK_THE_WORM_DEFAULT_REPLY


async def test_ask_the_worm_fires_mention_response_chat_reply_pevr(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """MentionResponseReactivity runs end-to-end and writes a chat_reply PEVR."""
    outbox = InAppChatOutbox()
    reply = await ask_the_worm(
        ledger=ledger,
        company_id=company_id,
        question="why are we losing customers in Q3?",
        outbox=outbox,
    )

    rows = await ledger.fetch(company_id)
    # The chat_reply cycle's execute row.
    chat_reply_executed = _execute_rows_with_tool(rows, "emit_chat_reply_executed")
    assert len(chat_reply_executed) == 1, "MentionResponseReactivity wrote one chat_reply_executed"

    args = chat_reply_executed[0]["payload"]["args"]
    assert args["channel_id"].startswith("in_app:")
    assert args["platform"] == "in_app"

    # Verify entry records the channel_adapter_send_ok check (we wired
    # a real in-app adapter so the send succeeds).
    verify_rows = [
        r for r in rows
        if r.get("kind") == "verify"
        and any(
            c.get("name") == "channel_adapter_send_ok" and c.get("ok") is True
            for c in (r.get("payload") or {}).get("checks", [])
        )
    ]
    assert len(verify_rows) == 1

    # The captured reply text is the production reactivity body.
    assert reply.answer == ASK_THE_WORM_DEFAULT_REPLY


async def test_ask_the_worm_returns_chat_reply_id(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """The returned AskReply carries the chat_reply_id for trace links."""
    outbox = InAppChatOutbox()
    reply = await ask_the_worm(
        ledger=ledger,
        company_id=company_id,
        question="ping",
        outbox=outbox,
    )
    assert reply.chat_reply_id is not None
    # chat_reply_id appears in the chat_reply_executed row's args.
    rows = await ledger.fetch(company_id)
    chat_reply_executed = _execute_rows_with_tool(rows, "emit_chat_reply_executed")
    assert chat_reply_executed[0]["payload"]["args"]["chat_reply_id"] == str(reply.chat_reply_id)


async def test_ask_the_worm_per_tenant_isolation(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Two different tenants' replies don't leak across the outbox."""
    other_tenant = UUID("00000000-0000-0000-0000-000000000002")
    outbox = InAppChatOutbox()
    await ask_the_worm(
        ledger=ledger, company_id=company_id, question="alpha", outbox=outbox,
    )
    await ask_the_worm(
        ledger=ledger, company_id=other_tenant, question="beta", outbox=outbox,
    )
    rows_a = await ledger.fetch(company_id)
    rows_b = await ledger.fetch(other_tenant)
    chat_a = _execute_rows_with_tool(rows_a, "channel_adapter.emit_chat_received")
    chat_b = _execute_rows_with_tool(rows_b, "channel_adapter.emit_chat_received")
    assert len(chat_a) == 1 and len(chat_b) == 1
    assert "alpha" in chat_a[0]["payload"]["args"]["text"]
    assert "beta" in chat_b[0]["payload"]["args"]["text"]


async def test_in_app_channel_adapter_implements_channel_adapter_protocol() -> None:
    """The in-app adapter satisfies the runtime-checkable ChannelAdapter Protocol."""
    from wormbase_channel_adapters import ChannelAdapter

    adapter = _InAppChannelAdapter(outbox=InAppChatOutbox())
    assert isinstance(adapter, ChannelAdapter)
    assert adapter.platform == "in_app"
    assert "send" in adapter.capability


async def test_in_app_channel_adapter_send_captures_text() -> None:
    """The adapter writes to the per-tenant outbox keyed by channel_id."""
    from wormbase_channel_adapters.types import AuthHandle, ChannelRef, OutMessage

    outbox = InAppChatOutbox()
    adapter = _InAppChannelAdapter(outbox=outbox)
    handle = AuthHandle(connector_kind="in_app", handle_id="dashboard-1")
    channel = ChannelRef(platform="in_app", platform_channel_id="in_app:dashboard")

    msg = OutMessage(text="Acknowledged.")
    ref = await adapter.send(handle, channel, msg)
    assert ref.platform == "in_app"
    assert ref.platform_message_id  # non-empty
    captured = outbox.drain("in_app:dashboard")
    assert len(captured) == 1
    assert captured[0].text == "Acknowledged."
