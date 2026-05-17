# > AUTHORED 2026-05-03: Block H2 of the chat-worm extraction plan.
# > _LedgerChatReply.speak writes the canonical 4-entry PEVR cycle, with each
# > envelope's payload tagged with the appropriate chat_reply_* domain kind.
"""ChatReply.speak writes the canonical 4-entry PEVR cycle, with each
entry's payload tagged with the appropriate chat_reply_* kind."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from wormbase_chat_presence.chat_reply import _LedgerChatReply
from wormbase_chat_presence.protocols import ChatReply
from wormbase_chat_presence.types import ChatPolicy, ConversationContext
from wormbase_ledger import InMemoryLedger


def _ctx(company_id: Any = None, channel_id: str = "C1") -> ConversationContext:
    return ConversationContext(
        company_id=company_id or uuid4(),
        channel_id=channel_id,
        domain_id=None,
        is_dm=False,
        classification="internal",
        policy=ChatPolicy(talkativeness="responsive", daily_interjection_budget=3),
    )


@pytest.mark.asyncio
async def test_chat_reply_satisfies_protocol() -> None:
    ledger = InMemoryLedger()
    cr = _LedgerChatReply(
        ledger=ledger, company_id=uuid4(),
        channel_adapter=None, channel_adapter_handle=None,
    )
    assert isinstance(cr, ChatReply)


@pytest.mark.asyncio
async def test_chat_reply_speak_writes_pevr_cycle_when_adapter_succeeds() -> None:
    ledger = InMemoryLedger()
    company = uuid4()

    sent: list[Any] = []

    class _StubAdapter:
        platform = "slack"

        async def send(self, handle: Any, channel: str, msg: Any) -> Any:
            sent.append({"channel": channel, "msg": msg})
            return SimpleNamespace(message_id="slack_msg_123")

    cr = _LedgerChatReply(
        ledger=ledger, company_id=company,
        channel_adapter=_StubAdapter(), channel_adapter_handle="handle",
    )

    ctx = _ctx(company_id=company)

    ref = await cr.speak(ctx, "want to wire up Stripe?", speech_act="proposal")

    assert ref is not None
    assert len(sent) == 1, f"adapter.send was called {len(sent)}x; expected 1"

    # 4 entries land — canonical PEVR.
    rows = await ledger.fetch(company)
    # Filter to entries from this cycle (propose entry's payload's reason).
    cycle_rows = [
        r for r in rows
        if (
            (r["kind"] == "propose"
             and r["payload"].get("target_kind") == "chat_reply_proposed")
            or (r["kind"] == "execute"
                and r["payload"].get("tool") == "emit_chat_reply_executed")
            or (r["kind"] == "verify"
                # Verify envelope's payload includes a check whose name says chat_reply_*.
                and any(
                    str(c.get("name", "")).startswith("channel_adapter_send")
                    for c in r["payload"].get("checks", [])
                ))
            or (r["kind"] == "resolve"
                and "chat_reply" in str(r["payload"].get("rationale", "")))
        )
    ]
    assert len(cycle_rows) == 4, f"expected 4 cycle rows, got {len(cycle_rows)}"

    # The propose entry's target_kind is chat_reply_proposed.
    propose_row = [r for r in cycle_rows if r["kind"] == "propose"][0]
    assert propose_row["payload"]["target_kind"] == "chat_reply_proposed"
    assert propose_row["payload"]["proposed_by"] == "chat-worm"

    # The execute envelope carries the chat_reply_executed tool name.
    execute_row = [r for r in cycle_rows if r["kind"] == "execute"][0]
    assert execute_row["payload"]["tool"] == "emit_chat_reply_executed"
    args = execute_row["payload"]["args"]
    assert args["channel_id"] == "C1"
    assert args["platform"] == "slack"
    assert "adapter_call_started_at" in args
    assert "adapter_call_ended_at" in args
    assert "chat_reply_id" in args

    # Verify envelope: one passing channel_adapter_send_ok check.
    verify_row = [r for r in cycle_rows if r["kind"] == "verify"][0]
    assert verify_row["payload"]["passed"] is True
    checks = verify_row["payload"]["checks"]
    assert len(checks) == 1
    assert checks[0]["name"] == "channel_adapter_send_ok"
    assert checks[0]["ok"] is True

    # Resolve envelope: keep, with rationale that names chat_reply.
    resolve_row = [r for r in cycle_rows if r["kind"] == "resolve"][0]
    assert resolve_row["payload"]["outcome"] == "keep"
    assert "chat_reply" in resolve_row["payload"]["rationale"]


@pytest.mark.asyncio
async def test_chat_reply_speak_returns_none_on_adapter_failure() -> None:
    ledger = InMemoryLedger()
    company = uuid4()

    class _FailAdapter:
        platform = "slack"

        async def send(self, handle: Any, channel: str, msg: Any) -> Any:
            raise RuntimeError("rate_limited")

    cr = _LedgerChatReply(
        ledger=ledger, company_id=company,
        channel_adapter=_FailAdapter(), channel_adapter_handle="handle",
    )

    ctx = _ctx(company_id=company)

    ref = await cr.speak(ctx, "hi", speech_act="answer")
    assert ref is None

    # PEVR cycle still lands — the failure is recorded as verify.passed=False
    # and resolve.outcome="discard".
    rows = await ledger.fetch(company)
    resolve_rows = [
        r for r in rows
        if r["kind"] == "resolve"
        and r["payload"].get("outcome") == "discard"
        and "chat_reply" in str(r["payload"].get("rationale", ""))
    ]
    assert len(resolve_rows) >= 1

    # The verify entry should record the failure check.
    verify_rows = [
        r for r in rows
        if r["kind"] == "verify"
        and any(
            str(c.get("name", "")).startswith("channel_adapter_send")
            for c in r["payload"].get("checks", [])
        )
    ]
    assert len(verify_rows) == 1
    failed_check = verify_rows[0]["payload"]["checks"][0]
    assert failed_check["ok"] is False
    assert "rate_limited" in failed_check["name"]


@pytest.mark.asyncio
async def test_chat_reply_speak_when_adapter_unavailable() -> None:
    """ChatReply degrades gracefully when channel_adapter=None."""
    ledger = InMemoryLedger()
    company = uuid4()
    cr = _LedgerChatReply(
        ledger=ledger, company_id=company,
        channel_adapter=None, channel_adapter_handle=None,
    )
    ctx = _ctx(company_id=company)

    ref = await cr.speak(ctx, "hi", speech_act="answer")

    # Adapter unavailable → ref is None; PEVR cycle still lands with
    # verify.passed=False and resolve.outcome="discard".
    assert ref is None
    rows = await ledger.fetch(company)
    proposes = [
        r for r in rows
        if r["kind"] == "propose"
        and r["payload"].get("target_kind") == "chat_reply_proposed"
    ]
    assert len(proposes) == 1

    # The verify envelope should record the unavailable adapter.
    verify_rows = [
        r for r in rows
        if r["kind"] == "verify"
        and any(
            str(c.get("name", "")).startswith("channel_adapter_")
            for c in r["payload"].get("checks", [])
        )
    ]
    assert len(verify_rows) == 1
    failed_check = verify_rows[0]["payload"]["checks"][0]
    assert failed_check["ok"] is False
    assert "unavailable" in failed_check["name"]


@pytest.mark.asyncio
async def test_chat_reply_passes_in_reply_to_to_adapter() -> None:
    """When in_reply_to is provided, the OutMessage carries it as thread_ref."""
    ledger = InMemoryLedger()
    company = uuid4()

    captured: dict[str, Any] = {}

    class _CaptureAdapter:
        platform = "slack"

        async def send(self, handle: Any, channel: str, msg: Any) -> Any:
            captured["msg"] = msg
            captured["channel"] = channel
            return SimpleNamespace(message_id="m1")

    cr = _LedgerChatReply(
        ledger=ledger, company_id=company,
        channel_adapter=_CaptureAdapter(), channel_adapter_handle="handle",
    )
    ctx = _ctx(company_id=company)

    ref = await cr.speak(
        ctx, "thread reply", speech_act="answer", in_reply_to="parent_msg_id"
    )
    assert ref is not None
    # OutMessage instances expose .thread_ref; dict fallback would have key.
    msg = captured["msg"]
    thread_ref = getattr(msg, "thread_ref", None) or msg.get("thread_ref") if isinstance(msg, dict) else getattr(msg, "thread_ref", None)
    assert thread_ref == "parent_msg_id"
