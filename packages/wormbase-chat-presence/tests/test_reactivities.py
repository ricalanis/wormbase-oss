"""Tests for chat-worm Reactivities (one test class per Reactivity)."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from wormbase_chat_presence.chat_store import _LedgerBackedChatStore
from wormbase_chat_presence.reactivities import ChatReceivedReactivity
from wormbase_core.reactivity import RelevanceDecision
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.protocol import (
    Reactivity,
    ReactivityContext,
    ReactivityResult,
)


@pytest.mark.asyncio
async def test_chat_received_reactivity_satisfies_protocol() -> None:
    r = ChatReceivedReactivity()
    assert isinstance(r, Reactivity)
    assert r.id == "chat_received"
    assert r.scope == "company"


@pytest.mark.asyncio
async def test_chat_received_reactivity_predicate_matches_chat_event() -> None:
    r = ChatReceivedReactivity()
    ctx = ReactivityContext(
        ledger=InMemoryLedger(),
        company_id=uuid4(),
        registry=None,
        now=datetime.now(UTC),
    )
    entry = {
        "kind": "execute",
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": {"channel_id": "C1", "text": "hello"},
        },
    }
    assert await r.predicate.match(entry, ctx) is True


@pytest.mark.asyncio
async def test_chat_received_reactivity_fires_routes_to_dispatcher() -> None:
    """Fire calls the dispatcher when relevance_gate.should_react=True."""
    company = uuid4()
    ledger = InMemoryLedger()
    chat_store = _LedgerBackedChatStore(ledger=ledger)

    routed: list[dict[str, Any]] = []

    class _StubGate:
        async def should_react(self, ctx: Any, msg: Any, interp: Any) -> RelevanceDecision:
            return RelevanceDecision(
                should_react=True, reason="test", suggested_flow="drop_and_profile",
            )

    async def _stub_dispatcher(event: dict[str, Any], decision: Any) -> None:
        routed.append({"event": event, "decision": decision})

    ctx = ReactivityContext(
        ledger=ledger,
        company_id=company,
        registry=None,
        now=datetime.now(UTC),
    )

    entry = {
        "kind": "execute",
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": {
                "channel_id": "C1",
                "message_id": "msg_1",
                "text": "we should pull from Stripe",
                "sender_person": str(uuid4()),
                "platform": "slack",
            },
        },
        "ts": datetime.now(UTC),
    }

    # Per O-B2: services are constructor-injected via factory kwargs;
    # the Reactivity reads them off self, not ctx.extras.
    r = ChatReceivedReactivity(
        _chat_store=chat_store,
        _relevance_gate=_StubGate(),
        _semantic_classifier=SimpleNamespace(handle=_stub_classifier_handle),
        _flow_dispatcher=_stub_dispatcher,
    )
    result = await r.fire(entry, ctx)

    assert isinstance(result, ReactivityResult)
    assert result.fired is True
    assert len(routed) == 1
    assert routed[0]["decision"].should_react is True


async def _stub_classifier_handle(infra: Any) -> Any:
    """Stub SemanticClassifier.handle returning a low-confidence interp."""
    from wormbase_core.reactivity import SemanticInterpretation
    return SemanticInterpretation(
        concepts=[], event_type="other", confidence=0.0, raw_text=getattr(infra, "text", ""),
    )


@pytest.mark.asyncio
async def test_mention_response_reactivity_fires_speak() -> None:
    """@-mention triggers ChatReply.speak."""
    from wormbase_chat_presence.reactivities import MentionResponseReactivity

    company = uuid4()
    ledger = InMemoryLedger()
    chat_store = _LedgerBackedChatStore(ledger=ledger)

    spoken: list[dict[str, Any]] = []

    class _StubReply:
        async def speak(
            self, ctx: Any, text: str, *, speech_act: str,
            in_reply_to: str | None = None,
        ) -> Any:
            spoken.append({
                "text": text,
                "speech_act": speech_act,
                "in_reply_to": in_reply_to,
            })
            return SimpleNamespace(message_id="msg_out")

    ctx = ReactivityContext(
        ledger=ledger,
        company_id=company,
        registry=None,
        now=datetime.now(UTC),
    )

    entry = {
        "kind": "execute",
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": {
                "channel_id": "C1",
                "message_id": "msg_in",
                "text": "@worm what is churn?",
            },
        },
        "ts": datetime.now(UTC),
    }

    # Per O-B2: chat_reply + chat_store threaded via factory kwargs.
    r = MentionResponseReactivity(
        _chat_reply=_StubReply(),
        _chat_store=chat_store,
    )
    assert await r.predicate.match(entry, ctx) is True
    result = await r.fire(entry, ctx)
    assert result.fired is True
    assert len(spoken) == 1
    assert spoken[0]["speech_act"] == "answer"
    assert spoken[0]["in_reply_to"] == "msg_in"


@pytest.mark.asyncio
async def test_interjection_budget_reactivity_fires_on_threshold_cross() -> None:
    """When clarify count reaches budget, the Reactivity emits a snapshot."""
    from wormbase_chat_presence.reactivities import InterjectionBudgetReactivity

    company = uuid4()
    ledger = InMemoryLedger()
    chat_store = _LedgerBackedChatStore(ledger=ledger)
    now = datetime.now(UTC)
    channel_id = "C_BUDGET"

    # Pre-populate: 2 clarify entries.
    for _ in range(2):
        await ledger.write(
            company_id=company,
            propose={
                "target_kind": "memory_written",
                "ref_id": str(uuid4()),
                "reason": "clarify",
                "proposed_by": "test",
            },
            execute_fn=lambda: {
                "tool": "emit_memory_written",
                "args": {
                    "memory_id": str(uuid4()),
                    "content": f"clarify_asked:{channel_id}",
                    "tags": ["clarify_asked", f"channel:{channel_id}"],
                },
                "result_ref": channel_id,
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
            timestamp=now,
            quadrant="active_deterministic",
        )

    ctx = ReactivityContext(
        ledger=ledger,
        company_id=company,
        registry=None,
        now=now,
    )

    # The 3rd clarify_asked entry — this fire should snapshot (default budget=3
    # → 3 entries crosses the threshold).
    entry = {
        "kind": "execute",
        "payload": {
            "tool": "emit_memory_written",
            "args": {
                "memory_id": str(uuid4()),
                "content": f"clarify_asked:{channel_id}",
                "tags": ["clarify_asked", f"channel:{channel_id}"],
            },
        },
        "ts": now,
    }
    # Pre-write the 3rd before fire so count_interjections sees count=3.
    await ledger.write(
        company_id=company,
        propose={"target_kind": "memory_written", "ref_id": str(uuid4()),
                 "reason": "clarify", "proposed_by": "test"},
        execute_fn=lambda: entry["payload"],
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
        timestamp=now,
        quadrant="active_deterministic",
    )

    # Per O-B2: chat_store threaded via factory kwarg.
    r = InterjectionBudgetReactivity(_chat_store=chat_store)
    result = await r.fire(entry, ctx)

    assert result.fired is True

    # Verify a policy_applied snapshot landed.
    rows = await ledger.fetch(company)
    snapshots = [
        row for row in rows
        if row["kind"] == "execute"
        and row["payload"].get("tool") == "emit_policy_applied"
        and row["payload"]["args"].get("policy_name") == "policy:channel_talkativeness"
        and "interjection_budget_consumed" in (row["payload"]["args"].get("rule") or "")
    ]
    assert len(snapshots) >= 1, "expected at least one budget-consumed snapshot"


@pytest.mark.asyncio
async def test_source_mentioned_reactivity_speaks_offer() -> None:
    """data-keyword hit → MentionedInConversationFlow → ChatReply.speak(speech_act='proposal')."""
    from wormbase_chat_presence.reactivities import SourceMentionedReactivity

    company = uuid4()
    ledger = InMemoryLedger()
    chat_store = _LedgerBackedChatStore(ledger=ledger)

    spoken: list[dict[str, Any]] = []

    class _StubReply:
        async def speak(self, ctx: Any, text: str, **kw: Any) -> Any:
            spoken.append({"text": text, **kw})
            return SimpleNamespace(message_id="msg_offer")

    class _StubFlow:
        async def on_proactive_mention(self, infra: Any) -> Any:
            return SimpleNamespace(
                channel_id=infra.channel_id,
                offer_text=f"I noticed you mentioned {infra.text}. Want to wire it up?",
            )

    ctx = ReactivityContext(
        ledger=ledger,
        company_id=company,
        registry=None,
        now=datetime.now(UTC),
    )

    entry = {
        "kind": "execute",
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": {
                "channel_id": "C1",
                "message_id": "msg_in",
                "text": "we should pull from Stripe",
                "sender_person": str(uuid4()),
            },
        },
        "ts": datetime.now(UTC),
    }

    # Per O-B2: chat_store / chat_reply / flow threaded via factory kwargs.
    r = SourceMentionedReactivity(
        _chat_store=chat_store,
        _chat_reply=_StubReply(),
        _mentioned_in_conversation_flow=_StubFlow(),
    )
    assert await r.predicate.match(entry, ctx) is True
    result = await r.fire(entry, ctx)

    assert result.fired is True
    assert len(spoken) == 1
    assert spoken[0]["speech_act"] == "proposal"
    assert "source_mention" in result.novelty_key
