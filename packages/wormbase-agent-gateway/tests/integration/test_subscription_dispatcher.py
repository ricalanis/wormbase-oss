"""Integration tests — SubscriptionDispatcher Reactivity (v2.A Task 3).

The dispatcher matches every new ledger entry against active subscriptions
and writes one ``agent_event_delivered`` PEVR cycle per match. These tests
exercise the full pipeline against an ``InMemoryLedger`` + recording
transports.

Test surface (per v2.A plan §Task 3 Step 1):

1. Subscription created → matching entry → fires; agent_event_delivered
   written with delivery_status=delivered.
2. Subscription revoked → matching entry → NO fire.
3. Filter mismatch → no fire (kinds-mismatch + domain-mismatch).
4. Idempotency: same (subscription, triggering_seq) twice → only one
   agent_event_delivered.
5. Meta-kind suppression: writing agent_subscription_created itself
   doesn't trigger dispatcher fire.
6. Webhook delivery success path → delivery_status=delivered.
7. Webhook delivery failure path → delivery_status=failed.
8. MCP stream delivery: event lands in StreamRegistry queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.protocol import ReactivityContext

from wormbase_agent_gateway.subscriptions.dispatcher import (
    SubscriptionDispatcher,
)
from wormbase_agent_gateway.subscriptions.filter import (
    AgentEventFilter,
    serialize_filter,
)
from wormbase_agent_gateway.subscriptions.stream_registry import StreamRegistry
from wormbase_agent_gateway.subscriptions.transports import (
    WebhookDeliveryResult,
)


pytestmark = pytest.mark.asyncio


COMPANY_ID = UUID("00000000-0000-0000-0000-000000000abc")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class RecordingWebhookTransport:
    """Test double for WebhookTransport — records calls, returns canned results.

    Mirrors WebhookTransport.deliver()'s async signature so the dispatcher
    consumes it uniformly. ``next_result`` controls the canned response;
    ``calls`` records every invocation.
    """

    next_result: WebhookDeliveryResult = field(
        default_factory=lambda: WebhookDeliveryResult(
            status="delivered", duration_ms=5,
        ),
    )
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def deliver(
        self, *, url: str, secret_ref: str, payload: dict[str, Any],
    ) -> WebhookDeliveryResult:
        self.calls.append({
            "url": url,
            "secret_ref": secret_ref,
            "payload": dict(payload),
        })
        return self.next_result


@dataclass
class StubSubscriptionReader:
    """In-memory active-subscriptions reader.

    The production reader walks the ledger. Tests can either seed the
    ledger directly (via _create_subscription helper) and use the
    LedgerSubscriptionReader, OR they can short-circuit by configuring
    this stub. We use the stub for clarity in unit-test surface.
    """

    rows: list[dict[str, Any]] = field(default_factory=list)

    async def active_subscriptions(
        self, _company_id: UUID,
    ) -> list[dict[str, Any]]:
        return list(self.rows)


def _make_subscription_row(
    *,
    subscription_id: str | None = None,
    agent_id: str = "agent-test",
    filter: AgentEventFilter | None = None,
    transport: str = "mcp_stream",
    webhook_url: str | None = None,
    webhook_secret_ref: str | None = None,
) -> dict[str, Any]:
    return {
        "subscription_id": subscription_id or str(uuid4()),
        "agent_id": agent_id,
        "filter": serialize_filter(filter or AgentEventFilter()),
        "transport": transport,
        "webhook_url": webhook_url,
        "webhook_secret_ref": webhook_secret_ref,
        "created_seq": 1,
    }


def _make_context(
    ledger: InMemoryLedger, *, replay_mode: bool = False,
) -> ReactivityContext:
    return ReactivityContext(
        ledger=ledger,
        company_id=COMPANY_ID,
        registry=None,
        now=lambda: datetime.now(UTC),
        replay_mode=replay_mode,
    )


def _make_entry(
    *,
    kind: str = "bad_pattern_proposed",
    seq: int = 100,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "seq": seq,
        "ts": datetime.now(UTC),
        "payload": {
            "tool": f"emit_{kind}",
            "args": args or {"agent_id": "agent-test", "domain": "finance"},
        },
        "args": args or {"agent_id": "agent-test", "domain": "finance"},
    }


async def _delivered_entries(ledger: InMemoryLedger) -> list[dict[str, Any]]:
    """Return all agent_event_delivered execute rows on the ledger."""
    rows = await ledger.fetch(COMPANY_ID)
    out = []
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") == "emit_agent_event_delivered":
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_subscription_created_matching_entry_fires() -> None:
    """Test 1: matching entry → fire; agent_event_delivered written."""
    ledger = InMemoryLedger()
    reader = StubSubscriptionReader(rows=[
        _make_subscription_row(
            filter=AgentEventFilter(kinds=("bad_pattern_proposed",)),
            transport="mcp_stream",
        ),
    ])
    transport = RecordingWebhookTransport()
    registry = StreamRegistry()
    dispatcher = SubscriptionDispatcher(
        subscription_reader=reader,
        webhook_transport=transport,
        stream_registry=registry,
        ledger=ledger,
    )
    entry = _make_entry(kind="bad_pattern_proposed", seq=42)
    result = await dispatcher.fire(entry, _make_context(ledger))

    assert result.fired is True
    assert len(result.actions) == 1
    assert result.actions[0].action_kind == "agent_event_delivered"
    delivered = await _delivered_entries(ledger)
    assert len(delivered) == 1
    args = delivered[0]["payload"]["args"]
    assert args["delivery_status"] == "delivered"
    assert args["triggering_entry_seq"] == 42
    assert args["triggering_entry_kind"] == "bad_pattern_proposed"
    assert args["transport_used"] == "mcp_stream"


async def test_subscription_revoked_no_fire() -> None:
    """Test 2: revoked subscription is excluded from active set → no fire."""
    ledger = InMemoryLedger()
    # The stub reader's job is to NOT return revoked subs; we simulate
    # that by returning an empty list (the LedgerSubscriptionReader
    # does the revoked-set subtraction in production; see its own tests).
    reader = StubSubscriptionReader(rows=[])
    dispatcher = SubscriptionDispatcher(
        subscription_reader=reader,
        webhook_transport=RecordingWebhookTransport(),
        stream_registry=StreamRegistry(),
        ledger=ledger,
    )
    entry = _make_entry(kind="bad_pattern_proposed", seq=42)
    result = await dispatcher.fire(entry, _make_context(ledger))

    assert result.fired is False
    assert await _delivered_entries(ledger) == []


async def test_filter_mismatch_no_fire_kinds() -> None:
    """Test 3a: kinds filter doesn't match → no fire."""
    ledger = InMemoryLedger()
    reader = StubSubscriptionReader(rows=[
        _make_subscription_row(
            filter=AgentEventFilter(kinds=("data_product_recommended",)),
            transport="mcp_stream",
        ),
    ])
    dispatcher = SubscriptionDispatcher(
        subscription_reader=reader,
        webhook_transport=RecordingWebhookTransport(),
        stream_registry=StreamRegistry(),
        ledger=ledger,
    )
    entry = _make_entry(kind="bad_pattern_proposed", seq=42)
    result = await dispatcher.fire(entry, _make_context(ledger))

    assert result.fired is False
    assert await _delivered_entries(ledger) == []


async def test_filter_mismatch_no_fire_domain() -> None:
    """Test 3b: domain filter doesn't match → no fire."""
    ledger = InMemoryLedger()
    reader = StubSubscriptionReader(rows=[
        _make_subscription_row(
            filter=AgentEventFilter(
                kinds=("bad_pattern_proposed",),
                domains=("sales",),
            ),
            transport="mcp_stream",
        ),
    ])
    dispatcher = SubscriptionDispatcher(
        subscription_reader=reader,
        webhook_transport=RecordingWebhookTransport(),
        stream_registry=StreamRegistry(),
        ledger=ledger,
    )
    entry = _make_entry(
        kind="bad_pattern_proposed",
        seq=42,
        args={"agent_id": "agent-test", "domain": "finance"},
    )
    result = await dispatcher.fire(entry, _make_context(ledger))

    assert result.fired is False
    assert await _delivered_entries(ledger) == []


async def test_idempotency_same_sub_seq_pair_once() -> None:
    """Test 4: re-firing on same (sub, seq) tuple writes only one delivery."""
    ledger = InMemoryLedger()
    sub_id = str(uuid4())
    reader = StubSubscriptionReader(rows=[
        _make_subscription_row(
            subscription_id=sub_id,
            filter=AgentEventFilter(kinds=("bad_pattern_proposed",)),
            transport="mcp_stream",
        ),
    ])
    dispatcher = SubscriptionDispatcher(
        subscription_reader=reader,
        webhook_transport=RecordingWebhookTransport(),
        stream_registry=StreamRegistry(),
        ledger=ledger,
    )
    entry = _make_entry(kind="bad_pattern_proposed", seq=42)

    # First fire — should deliver.
    r1 = await dispatcher.fire(entry, _make_context(ledger))
    assert r1.fired is True
    # Second fire on the same entry — should be idempotent (no new delivery).
    r2 = await dispatcher.fire(entry, _make_context(ledger))
    assert r2.fired is False

    delivered = await _delivered_entries(ledger)
    assert len(delivered) == 1, f"expected 1 delivery, got {len(delivered)}"


async def test_meta_kind_suppression_predicate() -> None:
    """Test 5: dispatcher's predicate excludes the 3 meta kinds.

    The dispatcher's predicate is composed in __post_init__; firing on
    a meta-kind entry should be a no-op because the W5a runner won't
    invoke fire(). We verify the predicate directly here — the runner
    itself is exercised in the wire-up tests below.
    """
    ledger = InMemoryLedger()
    reader = StubSubscriptionReader(rows=[])
    dispatcher = SubscriptionDispatcher(
        subscription_reader=reader,
        webhook_transport=RecordingWebhookTransport(),
        stream_registry=StreamRegistry(),
        ledger=ledger,
    )
    ctx = _make_context(ledger)

    # Each of the 3 meta kinds must NOT match the dispatcher's predicate.
    for meta_kind in (
        "agent_subscription_created",
        "agent_subscription_revoked",
        "agent_event_delivered",
    ):
        entry = _make_entry(kind=meta_kind, seq=1, args={})
        matches = await dispatcher.predicate.match(entry, ctx)
        assert matches is False, (
            f"meta-kind {meta_kind!r} unexpectedly matched dispatcher predicate"
        )

    # Sanity: a non-meta kind DOES match.
    non_meta = _make_entry(kind="bad_pattern_proposed", seq=2)
    assert await dispatcher.predicate.match(non_meta, ctx) is True


async def test_webhook_delivery_success() -> None:
    """Test 6: webhook transport returns delivered → delivery_status=delivered."""
    ledger = InMemoryLedger()
    reader = StubSubscriptionReader(rows=[
        _make_subscription_row(
            filter=AgentEventFilter(kinds=("bad_pattern_proposed",)),
            transport="webhook",
            webhook_url="https://hook.example/test",
            webhook_secret_ref="env://test_secret",
        ),
    ])
    transport = RecordingWebhookTransport(
        next_result=WebhookDeliveryResult(
            status="delivered", duration_ms=12, http_status=200,
        ),
    )
    dispatcher = SubscriptionDispatcher(
        subscription_reader=reader,
        webhook_transport=transport,
        stream_registry=StreamRegistry(),
        ledger=ledger,
    )
    entry = _make_entry(kind="bad_pattern_proposed", seq=99)
    result = await dispatcher.fire(entry, _make_context(ledger))

    assert result.fired is True
    assert len(transport.calls) == 1
    assert transport.calls[0]["url"] == "https://hook.example/test"
    delivered = await _delivered_entries(ledger)
    args = delivered[0]["payload"]["args"]
    assert args["delivery_status"] == "delivered"
    assert args["transport_used"] == "webhook"
    assert args["duration_ms"] == 12


async def test_webhook_delivery_failure() -> None:
    """Test 7: webhook transport returns failed → delivery_status=failed."""
    ledger = InMemoryLedger()
    reader = StubSubscriptionReader(rows=[
        _make_subscription_row(
            filter=AgentEventFilter(kinds=("bad_pattern_proposed",)),
            transport="webhook",
            webhook_url="https://hook.example/down",
            webhook_secret_ref="env://test_secret",
        ),
    ])
    transport = RecordingWebhookTransport(
        next_result=WebhookDeliveryResult(
            status="failed", duration_ms=3000, error="HTTP 500",
        ),
    )
    dispatcher = SubscriptionDispatcher(
        subscription_reader=reader,
        webhook_transport=transport,
        stream_registry=StreamRegistry(),
        ledger=ledger,
    )
    entry = _make_entry(kind="bad_pattern_proposed", seq=99)
    result = await dispatcher.fire(entry, _make_context(ledger))

    # We still record the delivery row (with failed status) so admins
    # can see what happened — the action fired even if the side-effect
    # didn't succeed.
    assert result.fired is True
    delivered = await _delivered_entries(ledger)
    assert len(delivered) == 1
    args = delivered[0]["payload"]["args"]
    assert args["delivery_status"] == "failed"
    assert args["error"] == "HTTP 500"


async def test_mcp_stream_event_lands_in_queue() -> None:
    """Test 8: mcp_stream transport pushes event into the per-sub queue."""
    ledger = InMemoryLedger()
    sub_id = str(uuid4())
    reader = StubSubscriptionReader(rows=[
        _make_subscription_row(
            subscription_id=sub_id,
            filter=AgentEventFilter(kinds=("bad_pattern_proposed",)),
            transport="mcp_stream",
        ),
    ])
    stream = StreamRegistry()
    dispatcher = SubscriptionDispatcher(
        subscription_reader=reader,
        webhook_transport=RecordingWebhookTransport(),
        stream_registry=stream,
        ledger=ledger,
    )
    entry = _make_entry(kind="bad_pattern_proposed", seq=77)
    result = await dispatcher.fire(entry, _make_context(ledger))

    assert result.fired is True
    assert stream.size(sub_id) == 1
    queued = stream.queue_for(sub_id).get_nowait()
    assert queued["triggering_entry_seq"] == 77
    assert queued["kind"] == "bad_pattern_proposed"
