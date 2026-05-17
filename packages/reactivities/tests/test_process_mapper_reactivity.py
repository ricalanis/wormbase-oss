"""P10 — RecurringQuestionProcessMapperReactivity unit tests.

Verifies the predicate / condition / fire path with stubbed inputs. The
true end-to-end test (drives chat_received entries through the full
pipeline and asserts /system-map renders the proposed process_map) lives
in tests/integration/test_process_map_e2e.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from wormbase_reactivities import (
    ReactivityContext,
    ReactivityRegistry,
)
from wormbase_reactivities.process_mapper import (
    InThread,
    RecurringQuestionProcessMapperReactivity,
    _reset_history,
)


pytestmark = pytest.mark.asyncio


BOB = UUID("aaaaaaaa-0000-0000-0000-0000000000b0")
CAROL = UUID("bbbbbbbb-0000-0000-0000-0000000000c0")
DANA = UUID("cccccccc-0000-0000-0000-0000000000d0")
TOPIC_CHURN = "churn_rate"
TOPIC_QBR = "qbr_deck"

# A "now" near our default test now() — observations stamped here will
# fall inside any reasonable 14-day window when context.now() is
# 2026-04-28. Using a real 2026 epoch value keeps the prune logic
# observable without time-mocking gymnastics.
_FRESH_TS = "1777334000.000001"  # ≈ 2026-04-28 00:00 UTC
_FRESH_THREAD_TS = "1777334000.000000"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chat_entry(
    seq: int,
    *,
    asker: UUID,
    askee: UUID,
    topic: str,
    ts: str = _FRESH_TS,
    thread_ts: str = _FRESH_THREAD_TS,
    message_id: str | None = None,
    channel_id: str = "C-rev",
) -> dict[str, Any]:
    """Synthesize a chat_received execute envelope.

    The reactivity's predicate is ``EntryKind('chat_received') &
    HasTopic() & InThread()``; we set ``topic`` and ``thread_ts != ts``
    so all three predicates pass.
    """
    args: dict[str, Any] = {
        "channel_id": channel_id,
        "message_id": message_id or f"M-{seq}",
        "ts": ts,
        "thread_ts": thread_ts,
        "sender_person": str(asker),
        "thread_parent_person": str(askee),
        "topic": topic,
        "text": f"hey {askee}, what's the {topic}?",
    }
    return {
        "kind": "execute",
        "seq": seq,
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": args,
        },
    }


def _make_reactivity(**kwargs: Any) -> RecurringQuestionProcessMapperReactivity:
    return RecurringQuestionProcessMapperReactivity(**kwargs)


@pytest.fixture(autouse=True)
def _isolate_history(company_id):
    """Each test gets a fresh per-tenant history store.

    The reactivity stores its rolling-window observation table in a
    module-level dict keyed by ``company_id``. Tests share the same
    fixture company_id, so we reset before AND after to ensure isolation
    even when a test crashes mid-run.
    """
    _reset_history(company_id)
    yield
    _reset_history(company_id)


# ---------------------------------------------------------------------------
# InThread predicate
# ---------------------------------------------------------------------------


async def test_in_thread_matches_when_thread_ts_differs_from_ts(
    ledger, company_id,
):
    pred = InThread()
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id, registry=None,
        now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": "x"},
    )
    entry = _chat_entry(1, asker=BOB, askee=CAROL, topic=TOPIC_CHURN,
                        ts="100.001", thread_ts="100.000")
    assert await pred.match(entry, ctx) is True


async def test_in_thread_skips_top_level_messages(ledger, company_id):
    pred = InThread()
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id, registry=None,
        now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": "x"},
    )
    entry = _chat_entry(1, asker=BOB, askee=CAROL, topic=TOPIC_CHURN)
    # Force thread_ts == ts → top-level
    entry["payload"]["args"]["thread_ts"] = entry["payload"]["args"]["ts"]
    assert await pred.match(entry, ctx) is False


async def test_in_thread_accepts_explicit_thread_id(ledger, company_id):
    """Discord/Teams adapters set thread_id rather than thread_ts."""
    pred = InThread()
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id, registry=None,
        now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": "x"},
    )
    entry = _chat_entry(1, asker=BOB, askee=CAROL, topic=TOPIC_CHURN)
    entry["payload"]["args"].pop("thread_ts", None)
    entry["payload"]["args"]["thread_id"] = "T-9001"
    assert await pred.match(entry, ctx) is True


# ---------------------------------------------------------------------------
# Predicate composition (all three pieces)
# ---------------------------------------------------------------------------


async def test_predicate_matches_chat_received_with_topic_in_thread(
    ledger, company_id,
):
    rx = _make_reactivity()
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id, registry=None,
        now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )
    assert await rx.predicate.match(
        _chat_entry(1, asker=BOB, askee=CAROL, topic=TOPIC_CHURN),
        ctx,
    ) is True


async def test_predicate_skips_when_no_topic(ledger, company_id):
    rx = _make_reactivity()
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id, registry=None,
        now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )
    entry = _chat_entry(1, asker=BOB, askee=CAROL, topic=TOPIC_CHURN)
    entry["payload"]["args"].pop("topic", None)
    assert await rx.predicate.match(entry, ctx) is False


# ---------------------------------------------------------------------------
# Fire path — counts and threshold cross
# ---------------------------------------------------------------------------


async def test_fire_below_threshold_does_not_emit(ledger, company_id):
    rx = _make_reactivity(threshold=3)
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id, registry=None,
        now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )
    # Only 2 observations — below the threshold of 3.
    r1 = await rx.fire(
        _chat_entry(1, asker=BOB, askee=CAROL, topic=TOPIC_CHURN), ctx,
    )
    r2 = await rx.fire(
        _chat_entry(2, asker=BOB, askee=CAROL, topic=TOPIC_CHURN), ctx,
    )
    assert r1.fired is False
    assert r2.fired is False
    rows = await ledger.fetch(company_id)
    tools = [r["payload"].get("tool") for r in rows
             if r["kind"] == "execute"]
    assert "emit_data_product_proposed" not in tools


async def test_fire_at_threshold_emits_data_product_proposed(
    ledger, company_id,
):
    """Third observation tips the triplet over threshold → fire."""
    rx = _make_reactivity(threshold=3)
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id, registry=None,
        now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )
    for i in range(1, 3):
        await rx.fire(
            _chat_entry(i, asker=BOB, askee=CAROL, topic=TOPIC_CHURN),
            ctx,
        )
    result = await rx.fire(
        _chat_entry(3, asker=BOB, askee=CAROL, topic=TOPIC_CHURN), ctx,
    )
    assert result.fired is True
    assert len(result.actions) == 1
    assert result.actions[0].action_kind == "data_product_proposed"
    rows = await ledger.fetch(company_id)
    proposed = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_data_product_proposed"
    ]
    assert len(proposed) == 1
    args = proposed[0]["payload"]["args"]
    assert args["kind"] == "process_map"
    # Process-map payload lives in parameters.
    pm = args["parameters"]
    assert "nodes" in pm and "edges" in pm
    assert pm["window_end"] >= pm["window_start"]
    assert isinstance(pm["confidence"], float)
    # The triplet (BOB, CAROL, churn_rate) should appear as an edge.
    edges = pm["edges"]
    assert any(
        e["from"] == str(BOB) and e["to"] == str(CAROL)
        and e["topic"] == TOPIC_CHURN and e["frequency"] == 3
        for e in edges
    )


async def test_fire_skips_self_question(ledger, company_id):
    rx = _make_reactivity(threshold=3)
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id, registry=None,
        now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )
    # asker == askee → not a process.
    for i in range(1, 4):
        result = await rx.fire(
            _chat_entry(i, asker=BOB, askee=BOB, topic=TOPIC_CHURN), ctx,
        )
        assert result.fired is False


async def test_fire_skips_when_askee_unknown(ledger, company_id):
    rx = _make_reactivity(threshold=3)
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id, registry=None,
        now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )
    for i in range(1, 4):
        entry = _chat_entry(
            i, asker=BOB, askee=CAROL, topic=TOPIC_CHURN,
        )
        entry["payload"]["args"].pop("thread_parent_person", None)
        entry["payload"]["args"].pop("askee_person_id", None)
        result = await rx.fire(entry, ctx)
        assert result.fired is False


# ---------------------------------------------------------------------------
# Recency window — observations outside the trailing window don't count
# ---------------------------------------------------------------------------


async def test_observations_outside_window_are_pruned(ledger, company_id):
    """Two stale observations + one fresh one should NOT cross threshold."""
    rx = _make_reactivity(threshold=3, window_days=14)
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id, registry=None,
        now=lambda: state["now"], extras={"reactivity_id": rx.id},
    )
    # Two observations >14 days ago (stale).
    stale_ts = (state["now"] - timedelta(days=20)).timestamp()
    for i in range(1, 3):
        await rx.fire(
            _chat_entry(
                i, asker=BOB, askee=CAROL, topic=TOPIC_CHURN,
                ts=str(stale_ts), thread_ts=str(stale_ts - 1),
            ),
            ctx,
        )
    # Move now() forward; stale obs should prune. One fresh observation
    # alone shouldn't cross threshold.
    fresh_ts = state["now"].timestamp()
    result = await rx.fire(
        _chat_entry(
            3, asker=BOB, askee=CAROL, topic=TOPIC_CHURN,
            ts=str(fresh_ts), thread_ts=str(fresh_ts - 1),
        ),
        ctx,
    )
    assert result.fired is False  # only 1 fresh observation post-prune


# ---------------------------------------------------------------------------
# Re-fire suppression — same triplet at threshold doesn't re-fire forever
# ---------------------------------------------------------------------------


async def test_no_refire_within_24h_for_same_triplet(ledger, company_id):
    """Once a triplet fires, subsequent observations don't re-fire."""
    rx = _make_reactivity(threshold=3)
    state = {"now": datetime(2026, 4, 28, 12, 0, tzinfo=UTC)}
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id, registry=None,
        now=lambda: state["now"], extras={"reactivity_id": rx.id},
    )
    for i in range(1, 4):
        await rx.fire(
            _chat_entry(i, asker=BOB, askee=CAROL, topic=TOPIC_CHURN),
            ctx,
        )
    # Move forward 1h, send a 4th observation. Within 24h cooldown.
    state["now"] = state["now"] + timedelta(hours=1)
    result = await rx.fire(
        _chat_entry(4, asker=BOB, askee=CAROL, topic=TOPIC_CHURN), ctx,
    )
    assert result.fired is False


# ---------------------------------------------------------------------------
# Budget enforcement (registry-driven)
# ---------------------------------------------------------------------------


async def test_per_tenant_budget_blocks_after_5_fires(ledger, company_id):
    """Per-tenant cap is 5/day — the 6th fire is blocked even if a new triplet hits threshold."""
    rx = _make_reactivity(threshold=3, per_tenant_budget=5)
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id,
        now=lambda: datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
    )
    reg.register(rx)
    # Pre-load tenant budget to 5 (the cap).
    await reg._inc_budget(
        reactivity_id=rx.id, axis="tenant", key=str(company_id),
        day="2026-04-28", by=5,
    )
    # Drive 3 observations of a single triplet → would normally fire.
    for i in range(1, 4):
        await reg.dispatch(
            _chat_entry(i, asker=BOB, askee=CAROL, topic=TOPIC_CHURN),
        )
    rows = await ledger.fetch(company_id)
    tools = [r["payload"].get("tool") for r in rows
             if r["kind"] == "execute"]
    assert "emit_data_product_proposed" not in tools


# ---------------------------------------------------------------------------
# Multiple triplets — payload reflects the full graph
# ---------------------------------------------------------------------------


async def test_payload_reflects_multiple_triplets(ledger, company_id):
    """When a second triplet exists alongside the firing one, the
    payload edges include both."""
    rx = _make_reactivity(threshold=3)
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id, registry=None,
        now=lambda: datetime(2026, 4, 28, tzinfo=UTC),
        extras={"reactivity_id": rx.id},
    )
    # Triplet A: BOB → CAROL on churn (1 observation, below threshold).
    await rx.fire(
        _chat_entry(1, asker=BOB, askee=CAROL, topic=TOPIC_CHURN), ctx,
    )
    # Triplet B: DANA → CAROL on qbr (will hit threshold).
    for i in range(2, 5):
        result = await rx.fire(
            _chat_entry(i, asker=DANA, askee=CAROL, topic=TOPIC_QBR),
            ctx,
        )
    assert result.fired is True
    rows = await ledger.fetch(company_id)
    proposed = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_data_product_proposed"
    ][0]
    pm = proposed["payload"]["args"]["parameters"]
    edges = {(e["from"], e["to"], e["topic"]): e for e in pm["edges"]}
    assert (str(BOB), str(CAROL), TOPIC_CHURN) in edges
    assert (str(DANA), str(CAROL), TOPIC_QBR) in edges
    # Confidence = above-threshold edges / total edges = 1/2 = 0.5
    assert pm["confidence"] == pytest.approx(0.5, rel=0.01)
    # Carol shows up as askee; both BOB and DANA show up as askers.
    actor_ids = {n["actor_person_id"] for n in pm["nodes"]}
    assert {str(BOB), str(CAROL), str(DANA)} == actor_ids


# ---------------------------------------------------------------------------
# Domain-disabled gate respected via registry path
# ---------------------------------------------------------------------------


async def test_dispatch_via_registry_writes_reactivity_fired(
    ledger, company_id,
):
    """End-to-end through the registry: budget increments, fire log populated."""
    rx = _make_reactivity(threshold=3)
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id,
        now=lambda: datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
    )
    reg.register(rx)
    fired = []
    for i in range(1, 4):
        fired.extend(await reg.dispatch(
            _chat_entry(i, asker=BOB, askee=CAROL, topic=TOPIC_CHURN),
        ))
    assert fired == [rx.id]
    # Budget incremented for tenant axis.
    count = await reg.get_budget_count(
        reactivity_id=rx.id, axis="tenant", key=str(company_id),
        day="2026-04-28",
    )
    assert count == 1
