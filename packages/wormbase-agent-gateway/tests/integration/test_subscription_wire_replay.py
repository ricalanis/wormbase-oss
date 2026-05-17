"""Wire-replay determinism tests — SubscriptionDispatcher (v2.A Task 6).

Per the v2.A plan §D5: a recorded subscription + recorded triggering
entry must reproduce the same match decision and the same
``agent_event_delivered`` ledger entry in replay mode, with the
network/queue side-effect no-op'd.

Three tests:

1. ``test_replay_mode_no_op_transport`` — replay with a transport that
   would raise; dispatcher records ``delivery_status="delivered"`` and
   does NOT raise.
2. ``test_replay_mode_deterministic`` — same input ledger replayed
   twice produces byte-identical ``agent_event_delivered`` entries
   (subscription_id, triggering_entry_seq, delivery_status,
   transport_used match).
3. ``test_replay_mode_preserves_idempotency`` — same (sub_id,
   triggering_seq) in replay produces exactly one delivery entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.protocol import ReactivityContext

from wormbase_agent_gateway.subscriptions.dispatcher import (
    SubscriptionDispatcher,
)
from wormbase_agent_gateway.subscriptions.filter import (
    AgentEventFilter,
)
from wormbase_agent_gateway.subscriptions.stream_registry import StreamRegistry
from wormbase_agent_gateway.subscriptions.transports import (
    WebhookDeliveryResult,
)

from .test_subscription_dispatcher import (
    COMPANY_ID,
    StubSubscriptionReader,
    _delivered_entries,
    _make_entry,
    _make_subscription_row,
)


pytestmark = pytest.mark.asyncio


@dataclass
class RaisingWebhookTransport:
    """Transport whose deliver() raises — used to prove replay no-ops side-effects.

    A real ``WebhookTransport`` would catch and record the error; this
    test double escalates so any test that *does* invoke deliver() in
    replay mode would fail loudly. The expected behaviour: replay mode
    skips the deliver() call entirely.
    """

    calls: list[dict[str, Any]] = field(default_factory=list)

    async def deliver(
        self, *, url: str, secret_ref: str, payload: dict[str, Any],
    ) -> WebhookDeliveryResult:
        self.calls.append({"url": url, "payload": payload})
        raise RuntimeError(
            "RaisingWebhookTransport: deliver() should never be called "
            "in replay mode",
        )


def _replay_context(ledger: InMemoryLedger) -> ReactivityContext:
    return ReactivityContext(
        ledger=ledger,
        company_id=COMPANY_ID,
        registry=None,
        now=lambda: datetime.now(UTC),
        replay_mode=True,
    )


async def test_replay_mode_no_op_transport() -> None:
    """Test 1: replay with a deliver()-that-would-raise produces a clean
    delivered entry.

    The dispatcher must skip the transport call entirely in replay mode
    so external systems do not receive duplicate events on replay.
    """
    ledger = InMemoryLedger()
    reader = StubSubscriptionReader(rows=[
        _make_subscription_row(
            filter=AgentEventFilter(kinds=("bad_pattern_proposed",)),
            transport="webhook",
            webhook_url="https://hook.example/test",
            webhook_secret_ref="env://test",
        ),
    ])
    raising_transport = RaisingWebhookTransport()
    dispatcher = SubscriptionDispatcher(
        subscription_reader=reader,
        webhook_transport=raising_transport,  # type: ignore[arg-type]
        stream_registry=StreamRegistry(),
        ledger=ledger,
    )
    entry = _make_entry(kind="bad_pattern_proposed", seq=99)

    # Replay mode: deliver() must NOT be called.
    result = await dispatcher.fire(entry, _replay_context(ledger))

    assert result.fired is True
    assert raising_transport.calls == [], (
        "RaisingWebhookTransport.deliver() was called in replay mode; "
        "wire-replay determinism violated"
    )
    delivered = await _delivered_entries(ledger)
    assert len(delivered) == 1
    args = delivered[0]["payload"]["args"]
    # Replay records delivery_status=delivered deterministically (D5).
    assert args["delivery_status"] == "delivered"
    assert args["transport_used"] == "webhook"


async def test_replay_mode_deterministic() -> None:
    """Test 2: replay the same input twice → byte-identical delivered entries.

    "Byte-identical" here means the audit-relevant fields
    (subscription_id, triggering_entry_seq, delivery_status,
    transport_used). Entry hashes themselves will differ across two
    fresh InMemoryLedger instances because hash chains depend on
    timestamps; the v2.A determinism contract is on the entry payload,
    not the chain hash.
    """
    sub_id = str(uuid4())

    async def _run_once() -> dict[str, Any]:
        ledger = InMemoryLedger()
        reader = StubSubscriptionReader(rows=[
            _make_subscription_row(
                subscription_id=sub_id,
                filter=AgentEventFilter(kinds=("bad_pattern_proposed",)),
                transport="webhook",
                webhook_url="https://hook.example/test",
                webhook_secret_ref="env://test",
            ),
        ])
        dispatcher = SubscriptionDispatcher(
            subscription_reader=reader,
            webhook_transport=RaisingWebhookTransport(),  # type: ignore[arg-type]
            stream_registry=StreamRegistry(),
            ledger=ledger,
        )
        entry = _make_entry(kind="bad_pattern_proposed", seq=77)
        await dispatcher.fire(entry, _replay_context(ledger))
        delivered = await _delivered_entries(ledger)
        assert len(delivered) == 1
        args = delivered[0]["payload"]["args"]
        return {
            "subscription_id": args["subscription_id"],
            "triggering_entry_seq": args["triggering_entry_seq"],
            "delivery_status": args["delivery_status"],
            "transport_used": args["transport_used"],
            "triggering_entry_kind": args["triggering_entry_kind"],
        }

    run_a = await _run_once()
    run_b = await _run_once()
    assert run_a == run_b, (
        f"replay produced non-deterministic delivery entries: "
        f"{run_a!r} != {run_b!r}"
    )


async def test_replay_mode_preserves_idempotency() -> None:
    """Test 3: same (sub_id, triggering_seq) replayed twice → exactly one delivery."""
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
        webhook_transport=RaisingWebhookTransport(),  # type: ignore[arg-type]
        stream_registry=StreamRegistry(),
        ledger=ledger,
    )
    entry = _make_entry(kind="bad_pattern_proposed", seq=42)

    # Fire twice in replay mode.
    await dispatcher.fire(entry, _replay_context(ledger))
    await dispatcher.fire(entry, _replay_context(ledger))

    delivered = await _delivered_entries(ledger)
    assert len(delivered) == 1, (
        f"replay-mode idempotency broken: expected 1 delivery, got "
        f"{len(delivered)}"
    )
