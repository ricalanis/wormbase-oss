"""Tests for D.1 — system-map synthesis lifted from worm-core.

Covers the spec acceptance bullets (plan §D.1, lines 507-522):

* ``SystemMapAccumulator`` starts empty
* ``update_from_chat_entry`` adds the chat sender as a ``person`` node
* ``update_from_chat_entry`` adds the channel as a ``channel`` node
* ``update_from_chat_entry`` adds explicit @-mentions as ``person`` edges
* Edge weights accumulate across multiple chats with the same actor pair
* ``flush_one_node`` returns the highest-weight dirty node first
* ``flush_one_node`` returns ``None`` after all dirty nodes have been flushed
* Multiple tenants have independent accumulators
* ``flush_one_node``'s payload validates round-trip via
  ``wormbase_ledger.entries.SystemMapNodePayload``
* Determinism: a fixed sequence of updates produces a fixed flush order
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from wormbase_ledger.entries import SystemMapNodePayload
from wormbase_process_extractor.system_map import (
    SystemMapAccumulator,
    _reset_tenant_accumulator,
    flush_one_node,
    get_tenant_accumulator,
    update_from_chat_entry,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _ts() -> str:
    return datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC).isoformat()


def _args(
    *,
    text: str,
    sender: UUID | None = None,
    channel_id: str = "C-finance",
    message_id: str = "M-100",
) -> dict[str, Any]:
    return {
        "text": text,
        "sender_person": str(sender or uuid4()),
        "channel_id": channel_id,
        "message_id": message_id,
        "ts": _ts(),
    }


# ---------------------------------------------------------------------------
# Accumulator construction / emptiness
# ---------------------------------------------------------------------------


def test_accumulator_starts_empty() -> None:
    acc = SystemMapAccumulator()
    assert len(acc.person_to_person) == 0
    assert len(acc.person_to_channel) == 0
    assert len(acc.channel_to_topic) == 0
    assert acc.dirty_nodes == set()


def test_flush_returns_none_on_empty_accumulator() -> None:
    acc = SystemMapAccumulator()
    assert flush_one_node(acc) is None


# ---------------------------------------------------------------------------
# update_from_chat_entry — sender, channel, mentions
# ---------------------------------------------------------------------------


def test_update_records_sender_as_speaks_in_edge() -> None:
    acc = SystemMapAccumulator()
    sender = uuid4()
    update_from_chat_entry(
        _args(text="planning the close", sender=sender, channel_id="C-fin"),
        accumulator=acc,
    )
    assert acc.person_to_channel[(str(sender), "C-fin")] == 1
    # Sender node is dirty so flush_one_node will see it.
    assert str(sender) in acc.dirty_nodes


def test_update_records_channel_topic_edge() -> None:
    acc = SystemMapAccumulator()
    sender = uuid4()
    update_from_chat_entry(
        _args(
            text="rolling out the deploy now",
            sender=sender,
            channel_id="C-eng",
        ),
        accumulator=acc,
    )
    assert acc.channel_to_topic["C-eng"]["eng"] == 1
    assert "C-eng" in acc.dirty_nodes


def test_update_records_explicit_at_mentions() -> None:
    acc = SystemMapAccumulator()
    sender = uuid4()
    update_from_chat_entry(
        _args(
            text="@bob can you ack the @alice request",
            sender=sender,
            channel_id="C-ops",
        ),
        accumulator=acc,
    )
    assert acc.person_to_person[(str(sender), "bob")] == 1
    assert acc.person_to_person[(str(sender), "alice")] == 1


def test_update_skips_empty_text() -> None:
    acc = SystemMapAccumulator()
    update_from_chat_entry(_args(text=""), accumulator=acc)
    assert len(acc.person_to_channel) == 0
    assert len(acc.dirty_nodes) == 0


def test_update_skips_missing_text() -> None:
    acc = SystemMapAccumulator()
    args = _args(text="placeholder")
    args.pop("text")
    update_from_chat_entry(args, accumulator=acc)
    assert len(acc.person_to_channel) == 0
    assert len(acc.dirty_nodes) == 0


def test_edge_weights_accumulate_for_repeated_pair() -> None:
    acc = SystemMapAccumulator()
    sender = uuid4()
    for _ in range(3):
        update_from_chat_entry(
            _args(
                text="@bob hey",
                sender=sender,
                channel_id="C-ops",
            ),
            accumulator=acc,
        )
    assert acc.person_to_person[(str(sender), "bob")] == 3
    assert acc.person_to_channel[(str(sender), "C-ops")] == 3
    assert acc.channel_to_topic["C-ops"]["ops"] == 0  # "@bob hey" has no ops kw
    assert acc.channel_to_topic["C-ops"]["general"] == 3


# ---------------------------------------------------------------------------
# flush_one_node — picks highest-weight, then drains
# ---------------------------------------------------------------------------


def test_flush_one_node_picks_highest_weight_first() -> None:
    acc = SystemMapAccumulator()
    heavy_sender = uuid4()
    light_sender = uuid4()
    # Heavy: 3 messages with 1 mention each = weight 3 mentions + 3 speaks_in
    for _ in range(3):
        update_from_chat_entry(
            _args(
                text="@bob status",
                sender=heavy_sender,
                channel_id="C-ops",
            ),
            accumulator=acc,
        )
    # Light: 1 message with no mentions = weight 1 (just speaks_in)
    update_from_chat_entry(
        _args(text="hello", sender=light_sender, channel_id="C-fin"),
        accumulator=acc,
    )

    payload = flush_one_node(acc)
    assert payload is not None
    # The channel C-ops also has 3 messages → topic weight 3, total = 3.
    # heavy_sender's edges sum to 3 mentions + 3 speaks_in = 6, the max.
    assert payload.node_id == str(heavy_sender)
    assert payload.node_kind == "person"


def test_flush_drains_then_returns_none() -> None:
    acc = SystemMapAccumulator()
    sender = uuid4()
    update_from_chat_entry(
        _args(text="@bob hi", sender=sender, channel_id="C-ops"),
        accumulator=acc,
    )
    # Sender + channel = 2 dirty nodes
    seen: set[str] = set()
    while True:
        payload = flush_one_node(acc)
        if payload is None:
            break
        seen.add(payload.node_id)
    assert str(sender) in seen
    assert "C-ops" in seen
    assert flush_one_node(acc) is None


def test_flush_payload_round_trips_via_ledger_payload() -> None:
    acc = SystemMapAccumulator()
    sender = uuid4()
    update_from_chat_entry(
        _args(
            text="@bob deploy now",
            sender=sender,
            channel_id="C-eng",
        ),
        accumulator=acc,
    )
    payload = flush_one_node(acc)
    assert payload is not None
    # Round-trip via the canonical ledger payload class — same class, but
    # serialise + re-validate to assert structural compatibility.
    raw = payload.model_dump(mode="json")
    rehydrated = SystemMapNodePayload.model_validate(raw)
    assert rehydrated.node_id == payload.node_id
    assert rehydrated.node_kind == payload.node_kind
    assert rehydrated.edges == payload.edges


# ---------------------------------------------------------------------------
# Per-tenant registry
# ---------------------------------------------------------------------------


def test_tenants_have_independent_accumulators() -> None:
    t1 = uuid4()
    t2 = uuid4()
    _reset_tenant_accumulator(t1)
    _reset_tenant_accumulator(t2)

    acc1 = get_tenant_accumulator(t1)
    acc2 = get_tenant_accumulator(t2)
    assert acc1 is not acc2

    s1 = uuid4()
    update_from_chat_entry(
        _args(text="@bob ping", sender=s1, channel_id="C-t1"),
        accumulator=acc1,
    )
    # acc2 untouched
    assert len(acc2.person_to_person) == 0
    assert len(acc2.person_to_channel) == 0
    assert len(acc2.dirty_nodes) == 0

    # Re-fetch returns the same object (lazy cache, not re-construct).
    assert get_tenant_accumulator(t1) is acc1


def test_get_tenant_accumulator_lazy_constructs_once() -> None:
    t = uuid4()
    _reset_tenant_accumulator(t)
    a = get_tenant_accumulator(t)
    b = get_tenant_accumulator(t)
    assert a is b


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_flush_order_is_deterministic_under_equal_weight() -> None:
    """Equal-weight dirty nodes must flush in a stable order so test
    fixtures and replay traces match across runs."""

    def _replay() -> list[str]:
        acc = SystemMapAccumulator()
        # Three senders, each with one identical message → all equal weight.
        # We hard-code sender UUIDs so the tie-break by node-id sort is
        # observable (not random per run).
        senders = [
            UUID("00000000-0000-0000-0000-000000000aaa"),
            UUID("00000000-0000-0000-0000-000000000bbb"),
            UUID("00000000-0000-0000-0000-000000000ccc"),
        ]
        for s in senders:
            update_from_chat_entry(
                _args(text="hi", sender=s, channel_id="C-x"),
                accumulator=acc,
            )
        order: list[str] = []
        while True:
            p = flush_one_node(acc)
            if p is None:
                break
            order.append(p.node_id)
        return order

    a = _replay()
    b = _replay()
    assert a == b
    # And the tie-break-by-node-id sort means the channel (with weight 3,
    # the highest) flushes first, then senders in lexical UUID order.
    assert a[0] == "C-x"
    assert a[1:] == sorted(a[1:])


def test_flush_with_no_mentions_only_emits_channel_and_sender() -> None:
    acc = SystemMapAccumulator()
    sender = UUID("11111111-1111-1111-1111-111111111111")
    update_from_chat_entry(
        _args(text="just a normal message", sender=sender, channel_id="C-z"),
        accumulator=acc,
    )
    nodes: list[str] = []
    while True:
        p = flush_one_node(acc)
        if p is None:
            break
        nodes.append(p.node_id)
    # Sender has 1 speaks_in edge; channel has 1 topic edge. Both non-empty.
    assert set(nodes) == {str(sender), "C-z"}
