"""v2.B Phase 2/3 Axis 4 — SemanticGapToEscalation integration tests.

Pins the contract for the gap-escalation compounding axis:

  * source predicate: ``Periodic(every_seconds=...)`` — v2.B Phase 3
    (2026-05-12) replaces the Phase-2 ``EntryKind("semantic_gap_proposed")``
    trigger with a real cadence-driven tick. New-gap writes do NOT
    trigger escalation; only ``clock_tick`` entries do. A
    freshly-installed worm with pre-existing gaps can now escalate
    them at the next tick, instead of waiting for a second gap to
    land.
  * quality_filter: always True (every tick is a potential trigger);
  * gather_fn: scan ledger for ``semantic_gap_proposed`` propose rows
    older than the configured age window (default 7 days) that have
    no resolution;
  * cluster_fn: each unresolved gap is its own cluster;
  * promotion_threshold: ``>= 1``;
  * promotion_action: emit ``semantic_gap_escalated`` PEVR cycle;
  * idempotency_filter: skip if a ``semantic_gap_escalated`` already
    exists for the original ``gap_id``.

Uses the real ``ReactivityRegistry`` + ``ReactivityRunner`` +
``InMemoryLedger`` + ``ClockTickEmitter`` so this is a true
integration test — no mocks.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.clock_tick_emitter import ClockTickEmitter
from wormbase_reactivities.registry import ReactivityRegistry
from wormbase_reactivities.runner import ReactivityRunner

from wormbase_agent_gateway.reactivities import (
    make_semantic_gap_to_escalation_reactivity,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000a0002")
_TICK_S = 3600  # hourly cadence used by the factory's default.


async def _write_semantic_gap_proposed(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    nl_question: str,
    reason: str = "no_match",
    agent_id: str = "agent-test",
    proposed_metric_name: str | None = None,
    timestamp: datetime | None = None,
) -> dict:
    """Drive the canonical PEVR shape ``lake.semantic.gap`` emits.

    Returns the propose row as a dict so the test can reference its
    ``entry_id`` (which becomes ``original_gap_id`` on escalation).
    """
    gap_id = str(uuid4())
    payload_args: dict = {
        "agent_id": agent_id,
        "nl_question": nl_question,
        "reason": reason,
        "proposed_metric_name": proposed_metric_name,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "semantic_gap_proposed",
            "ref_id": gap_id,
            "reason": f"test gap nl={nl_question}",
            "proposed_by": "test_agent",
        },
        execute_fn=lambda: {
            "tool": "emit_semantic_gap_proposed",
            "args": payload_args,
            "result_ref": gap_id,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "semantic_gap_proposed", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "semantic_gap_proposed",
        },
        timestamp=timestamp,
        quadrant="active_probabilistic",
    )
    rows = await ledger.fetch(company_id)
    proposes = [
        r for r in rows
        if r["kind"] == "propose"
        and (r.get("payload") or {}).get("target_kind") == "semantic_gap_proposed"
        and (r.get("payload") or {}).get("ref_id") == gap_id
    ]
    return proposes[-1]


def _fetch_escalations(rows: list[dict]) -> list[dict]:
    """Return propose rows targeting ``semantic_gap_escalated``."""
    return [
        r for r in rows
        if r["kind"] == "propose"
        and (r.get("payload") or {}).get("target_kind") == "semantic_gap_escalated"
    ]


def _fetch_escalation_executes(rows: list[dict]) -> list[dict]:
    """Return execute rows for the ``semantic_gap_escalated`` cycle."""
    return [
        r for r in rows
        if r["kind"] == "execute"
        and "original_gap_id" in (r.get("payload") or {})
        and "days_unresolved" in (r.get("payload") or {})
    ]


def _make_emitter(ledger: InMemoryLedger) -> ClockTickEmitter:
    return ClockTickEmitter(
        ledger=ledger, company_id=_COMPANY_ID, tick_interval_s=_TICK_S,
    )


@pytest.mark.asyncio
async def test_old_unresolved_gap_escalates_on_tick() -> None:
    """An old (>7d) unresolved gap escalates when a ``clock_tick``
    triggers the Reactivity. Critical Phase-3 contract: the tick is
    the driver, NOT a new gap write."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_semantic_gap_to_escalation_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    old_ts = datetime.now(UTC) - timedelta(days=10)
    old_gap = await _write_semantic_gap_proposed(
        ledger, company_id=_COMPANY_ID,
        nl_question="What was net retention rate for Q3?",
        reason="no_match",
        proposed_metric_name="net_retention_rate_q3",
        timestamp=old_ts,
    )

    # Tick — drives the gap-to-escalation Reactivity.
    emitter = _make_emitter(ledger)
    await emitter.tick_once()

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    escalations = _fetch_escalations(rows)
    assert len(escalations) == 1, (
        f"expected 1 semantic_gap_escalated (for the 10-day-old gap); "
        f"got {len(escalations)}"
    )
    assert escalations[0]["payload"]["original_gap_id"] == str(old_gap["entry_id"])

    executes = _fetch_escalation_executes(rows)
    assert len(executes) == 1
    ex_payload = executes[0]["payload"]
    assert ex_payload["original_gap_id"] == str(old_gap["entry_id"])
    assert ex_payload["nl_question"] == "What was net retention rate for Q3?"
    assert ex_payload["reason"] == "no_match"
    assert ex_payload["proposed_metric_name"] == "net_retention_rate_q3"
    # days_unresolved is a frozen integer snapshot at promotion time
    assert ex_payload["days_unresolved"] >= 7


@pytest.mark.asyncio
async def test_new_gap_without_tick_does_not_trigger_escalation() -> None:
    """Phase-3 load-bearing assertion: writing a new gap (even if old
    gaps are sitting unresolved on the ledger) does NOT trigger
    escalation. Only a ``clock_tick`` triggers the Reactivity.

    This is the exact bug Phase 3 closes — Phase 2's
    ``EntryKind("semantic_gap_proposed")`` would have fired on the
    second gap landing. Phase 3 separates new-gap traffic from
    escalation cadence."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_semantic_gap_to_escalation_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    old_ts = datetime.now(UTC) - timedelta(days=14)
    await _write_semantic_gap_proposed(
        ledger, company_id=_COMPANY_ID,
        nl_question="Ancient gap",
        timestamp=old_ts,
    )

    # Write another semantic_gap_proposed — Phase 3 must NOT escalate.
    await _write_semantic_gap_proposed(
        ledger, company_id=_COMPANY_ID,
        nl_question="Another fresh gap (no tick)",
    )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_escalations(rows) == [], (
        "no clock_tick written — Phase 3 must not escalate on "
        "semantic_gap_proposed writes alone"
    )


@pytest.mark.asyncio
async def test_fresh_gap_does_not_escalate_itself() -> None:
    """A gap landing fresh (age < 7d) does NOT immediately
    self-escalate even when a tick lands."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_semantic_gap_to_escalation_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_semantic_gap_proposed(
        ledger, company_id=_COMPANY_ID,
        nl_question="What was Q4 EMEA churn?",
        reason="no_match",
    )
    emitter = _make_emitter(ledger)
    await emitter.tick_once()

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_escalations(rows) == []


@pytest.mark.asyncio
async def test_recent_unresolved_gap_does_not_escalate() -> None:
    """A 3-day-old gap (within the 7-day window) is not escalated yet
    when a tick lands."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_semantic_gap_to_escalation_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    recent_ts = datetime.now(UTC) - timedelta(days=3)
    await _write_semantic_gap_proposed(
        ledger, company_id=_COMPANY_ID,
        nl_question="3-day-old gap",
        timestamp=recent_ts,
    )

    # tick
    emitter = _make_emitter(ledger)
    await emitter.tick_once()

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_escalations(rows) == []


@pytest.mark.asyncio
async def test_gap_resolved_by_external_metric_does_not_escalate() -> None:
    """A gap that has been resolved (an ``external_metric_imported``
    entry references it via ``promoted_from_gap_id``) does NOT
    escalate even if older than 7d and a tick lands."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_semantic_gap_to_escalation_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    old_ts = datetime.now(UTC) - timedelta(days=10)
    old_gap = await _write_semantic_gap_proposed(
        ledger, company_id=_COMPANY_ID,
        nl_question="Resolved-old gap",
        timestamp=old_ts,
    )

    # Simulate admin importing an external_metric referencing this gap_id
    # (the resolution boundary recognised by `_resolved_gap_ids`).
    metric_id = str(uuid4())
    await ledger.write(
        company_id=_COMPANY_ID,
        propose={
            "target_kind": "external_metric_imported",
            "ref_id": metric_id,
            "reason": "admin import",
            "proposed_by": "admin",
        },
        execute_fn=lambda: {
            "tool": "emit_external_metric_imported",
            "args": {
                "metric_id": metric_id,
                "name": "resolved_metric",
                "promoted_from_gap_id": str(old_gap["entry_id"]),
            },
            "result_ref": metric_id,
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "imported"},
        quadrant="active_deterministic",
    )

    # tick
    emitter = _make_emitter(ledger)
    await emitter.tick_once()

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_escalations(rows) == [], (
        "resolved gap (has external_metric_imported with "
        "promoted_from_gap_id) must not escalate"
    )


@pytest.mark.asyncio
async def test_idempotency_filter_suppresses_duplicate_escalation() -> None:
    """An already-escalated gap is not escalated a second time —
    the first-class ``idempotency_filter`` short-circuits the action.
    Even when a second tick lands, idempotency stops the duplicate."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_semantic_gap_to_escalation_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    old_ts = datetime.now(UTC) - timedelta(days=14)
    await _write_semantic_gap_proposed(
        ledger, company_id=_COMPANY_ID,
        nl_question="Ancient gap",
        timestamp=old_ts,
    )

    # First tick: triggers escalation
    emitter = _make_emitter(ledger)
    await emitter.tick_once()
    await runner.run_once()
    first = _fetch_escalations(await ledger.fetch(_COMPANY_ID))
    assert len(first) == 1

    # Spin up a fresh registry (bypass NotRecentlyFired debounce) and
    # write another tick — idempotency_filter inside the primitive
    # must suppress a second escalation for the same gap.
    fresh_registry = ReactivityRegistry(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    fresh_registry.register(make_semantic_gap_to_escalation_reactivity())
    fresh_runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=fresh_registry,
        poll_interval_s=0.01,
    )
    await emitter.tick_once()
    await fresh_runner.run_once()

    second = _fetch_escalations(await ledger.fetch(_COMPANY_ID))
    assert len(second) == 1, (
        f"idempotency_filter failed: expected 1 escalation after "
        f"re-dispatch, got {len(second)}"
    )


@pytest.mark.asyncio
async def test_multiple_old_gaps_all_escalate_one_each_on_tick() -> None:
    """Each unresolved gap older than 7d gets its own escalation when
    a single tick lands (no cross-gap clustering)."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_semantic_gap_to_escalation_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    old_ts = datetime.now(UTC) - timedelta(days=8)
    gap_a = await _write_semantic_gap_proposed(
        ledger, company_id=_COMPANY_ID,
        nl_question="gap A",
        timestamp=old_ts,
    )
    gap_b = await _write_semantic_gap_proposed(
        ledger, company_id=_COMPANY_ID,
        nl_question="gap B",
        timestamp=old_ts,
    )

    # tick — one tick fires the Reactivity once; the gather_fn surfaces
    # both candidates and emits one escalation per cluster.
    emitter = _make_emitter(ledger)
    await emitter.tick_once()

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    escalations = _fetch_escalations(rows)
    assert len(escalations) == 2
    original_ids = {e["payload"]["original_gap_id"] for e in escalations}
    assert original_ids == {str(gap_a["entry_id"]), str(gap_b["entry_id"])}


@pytest.mark.asyncio
async def test_wire_replay_determinism_tick_then_state() -> None:
    """Wire-replay determinism: the cluster decision is fully a
    function of (tick_time, ledger_state_at_tick_time). Two runs of
    the same ledger end state — one continuous, one ledger-recorded-
    then-re-evaluated — produce the same escalation set.

    This is the load-bearing wire-replay pin for v2.B Phase 3.
    Because ticks are ledger-resident, a replay of the recorded
    JSONL trail through ``channel_adapter`` (or here, through a
    fresh registry + runner against the same ledger) reproduces the
    same escalation chain.
    """
    ledger = InMemoryLedger()
    old_ts = datetime.now(UTC) - timedelta(days=9)
    gap_a = await _write_semantic_gap_proposed(
        ledger, company_id=_COMPANY_ID,
        nl_question="determinism gap A",
        timestamp=old_ts,
    )
    gap_b = await _write_semantic_gap_proposed(
        ledger, company_id=_COMPANY_ID,
        nl_question="determinism gap B",
        timestamp=old_ts,
    )
    emitter = _make_emitter(ledger)
    await emitter.tick_once()

    # First dispatch — gap-to-escalation Reactivity fires once.
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_semantic_gap_to_escalation_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )
    await runner.run_once()
    first = sorted(
        e["payload"]["original_gap_id"]
        for e in _fetch_escalations(await ledger.fetch(_COMPANY_ID))
    )
    assert first == sorted([str(gap_a["entry_id"]), str(gap_b["entry_id"])])

    # Second dispatch on a fresh registry against the recorded ledger —
    # idempotency_filter must produce the same escalation set with no
    # duplicates (replay-stable).
    replay_registry = ReactivityRegistry(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    replay_registry.register(make_semantic_gap_to_escalation_reactivity())
    replay_runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=replay_registry,
        poll_interval_s=0.01,
    )
    await replay_runner.run_once()
    second = sorted(
        e["payload"]["original_gap_id"]
        for e in _fetch_escalations(await ledger.fetch(_COMPANY_ID))
    )
    assert second == first, (
        "wire-replay determinism broken: re-dispatch produced a "
        "different escalation set than the original run"
    )
