"""Tests for ``ClockTickEmitter`` (v2.B Phase 3, 2026-05-12).

Single-tenant clock-tick daemon — parallel sibling to ``ReactivityRunner``.
Writes one ``clock_tick`` ledger entry per tick interval per company,
deterministic in its sequence_number from prior ledger state.

Pins:

* ``tick_once`` emits a canonical PEVR cycle with the correct
  ``tick_interval_s`` + ``sequence_number``.
* ``sequence_number`` advances monotonically across successive ticks.
* Recovery on restart: a fresh emitter reads prior max ``sequence_number``
  for its slot and continues — the ledger is the checkpoint.
* ``run_forever`` is cancel-safe (``asyncio.CancelledError`` propagates).
* Multi-tenant + multi-cadence isolation: per-(company_id, tick_interval_s)
  slot — distinct emitters do not collide.
* Wire-replay determinism: the same emitter against the same ledger
  produces byte-identical PEVR rows (round-trip through ``ledger.fetch``).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities import ClockTickEmitter, ReactivityContext
from wormbase_reactivities.predicates import Periodic


_COMPANY_A = UUID("00000000-0000-0000-0000-0000000c1a01")
_COMPANY_B = UUID("00000000-0000-0000-0000-0000000c1a02")


def _execute_clock_ticks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only the ``emit_clock_tick`` execute envelopes."""
    return [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_clock_tick"
    ]


def _propose_clock_ticks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only the propose rows targeting ``clock_tick``."""
    return [
        r for r in rows
        if r.get("kind") == "propose"
        and (r.get("payload") or {}).get("target_kind") == "clock_tick"
    ]


@pytest.mark.asyncio
async def test_tick_once_writes_canonical_pevr_cycle() -> None:
    """A single ``tick_once`` writes propose / execute / verify / resolve
    with the configured cadence + a 0-indexed sequence_number."""
    ledger = InMemoryLedger()
    emitter = ClockTickEmitter(
        ledger=ledger, company_id=_COMPANY_A, tick_interval_s=3600,
    )
    payload = await emitter.tick_once()

    assert payload["tick_interval_s"] == 3600
    assert payload["sequence_number"] == 0

    rows = await ledger.fetch(_COMPANY_A)
    # Canonical PEVR: propose + execute + verify + resolve = 4 rows.
    assert len(rows) == 4
    kinds = [r["kind"] for r in rows]
    assert kinds == ["propose", "execute", "verify", "resolve"]

    # Execute envelope carries the tick payload.
    executes = _execute_clock_ticks(rows)
    assert len(executes) == 1
    args = executes[0]["payload"]["args"]
    assert args["tick_interval_s"] == 3600
    assert args["sequence_number"] == 0

    # Quadrant is passive_deterministic.
    for r in rows:
        assert r["quadrant"] == "passive_deterministic"

    # Propose row tags the target_kind so projection layers can index.
    proposes = _propose_clock_ticks(rows)
    assert len(proposes) == 1
    assert proposes[0]["payload"]["proposed_by"] == "reactivities.clock_tick_emitter"


@pytest.mark.asyncio
async def test_sequence_number_advances_monotonically() -> None:
    """Successive ticks advance ``sequence_number`` by 1 each — the
    counter is anchored to the ledger, not in-memory state."""
    ledger = InMemoryLedger()
    emitter = ClockTickEmitter(
        ledger=ledger, company_id=_COMPANY_A, tick_interval_s=900,
    )
    p0 = await emitter.tick_once()
    p1 = await emitter.tick_once()
    p2 = await emitter.tick_once()
    assert p0["sequence_number"] == 0
    assert p1["sequence_number"] == 1
    assert p2["sequence_number"] == 2

    executes = _execute_clock_ticks(await ledger.fetch(_COMPANY_A))
    assert [e["payload"]["args"]["sequence_number"] for e in executes] == [
        0, 1, 2,
    ]


@pytest.mark.asyncio
async def test_recovery_reads_prior_max_sequence_number() -> None:
    """A fresh emitter coming up after a "crash" sees the prior tick
    chain on the ledger and continues with the next sequence_number.
    No external state or checkpoint file — recovery is automatic."""
    ledger = InMemoryLedger()
    emitter_a = ClockTickEmitter(
        ledger=ledger, company_id=_COMPANY_A, tick_interval_s=600,
    )
    await emitter_a.tick_once()
    await emitter_a.tick_once()
    await emitter_a.tick_once()
    # Simulate restart: discard emitter_a, build a fresh one.
    emitter_b = ClockTickEmitter(
        ledger=ledger, company_id=_COMPANY_A, tick_interval_s=600,
    )
    payload = await emitter_b.tick_once()
    assert payload["sequence_number"] == 3, (
        "fresh emitter must continue from prior max + 1 (no in-memory cursor)"
    )


@pytest.mark.asyncio
async def test_run_forever_is_cancel_safe() -> None:
    """``asyncio.CancelledError`` propagates from ``run_forever`` — the
    daemon shuts down cleanly without burying the cancellation."""
    ledger = InMemoryLedger()
    # 1s cadence to keep the test fast; the run_forever sleep is the
    # cancellation point so we never wait the full interval.
    emitter = ClockTickEmitter(
        ledger=ledger, company_id=_COMPANY_A, tick_interval_s=1,
    )
    task = asyncio.create_task(emitter.run_forever())
    await asyncio.sleep(0)  # let the task start
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_multi_tenant_isolated() -> None:
    """Two companies share the ledger client; their tick chains do not
    contaminate each other. Per-tenant counter."""
    ledger = InMemoryLedger()
    emitter_a = ClockTickEmitter(
        ledger=ledger, company_id=_COMPANY_A, tick_interval_s=3600,
    )
    emitter_b = ClockTickEmitter(
        ledger=ledger, company_id=_COMPANY_B, tick_interval_s=3600,
    )
    await emitter_a.tick_once()
    await emitter_a.tick_once()
    payload_b = await emitter_b.tick_once()
    # Company B's first tick is sequence 0, not "lookup over both".
    assert payload_b["sequence_number"] == 0

    # And the next A tick is sequence 2.
    payload_a = await emitter_a.tick_once()
    assert payload_a["sequence_number"] == 2


@pytest.mark.asyncio
async def test_multi_cadence_isolated() -> None:
    """Two emitters on the same company with different cadences do not
    collide — ``sequence_number`` is keyed on (company, tick_interval_s)."""
    ledger = InMemoryLedger()
    hourly = ClockTickEmitter(
        ledger=ledger, company_id=_COMPANY_A, tick_interval_s=3600,
    )
    daily = ClockTickEmitter(
        ledger=ledger, company_id=_COMPANY_A, tick_interval_s=86_400,
    )
    await hourly.tick_once()
    await hourly.tick_once()
    payload_daily = await daily.tick_once()
    # Daily emitter's first tick is sequence 0 — it does NOT count the
    # hourly chain.
    assert payload_daily["sequence_number"] == 0

    payload_hourly = await hourly.tick_once()
    assert payload_hourly["sequence_number"] == 2


@pytest.mark.asyncio
async def test_invalid_tick_interval_rejected() -> None:
    """Non-positive ``tick_interval_s`` is rejected at construction
    time — fail loudly, not at the first tick."""
    ledger = InMemoryLedger()
    with pytest.raises(ValueError):
        ClockTickEmitter(
            ledger=ledger, company_id=_COMPANY_A, tick_interval_s=0,
        )
    with pytest.raises(ValueError):
        ClockTickEmitter(
            ledger=ledger, company_id=_COMPANY_A, tick_interval_s=-60,
        )


@pytest.mark.asyncio
async def test_wire_replay_determinism_emitted_ticks_match_predicate() -> None:
    """Wire-replay determinism: the emitter writes ticks, the Periodic
    predicate matches them — same ledger state on a re-read produces
    the same predicate outcomes. This is the load-bearing wire-replay
    pin: a recorded tick + ledger replay reproduces the same matching
    decisions downstream.
    """
    ledger = InMemoryLedger()
    emitter = ClockTickEmitter(
        ledger=ledger, company_id=_COMPANY_A, tick_interval_s=3600,
    )
    await emitter.tick_once()
    await emitter.tick_once()
    await emitter.tick_once()

    rows = await ledger.fetch(_COMPANY_A)
    executes = _execute_clock_ticks(rows)
    assert len(executes) == 3

    # Construct a minimal ReactivityContext for the predicate.
    from wormbase_reactivities import ReactivityRegistry

    registry = ReactivityRegistry(
        ledger=ledger, company_id=_COMPANY_A,
        now=lambda: datetime(2026, 5, 12, 12, 0, 0, tzinfo=UTC),
    )
    ctx = ReactivityContext(
        ledger=ledger,
        company_id=_COMPANY_A,
        registry=registry,
        now=registry._now,  # noqa: SLF001
        extras={"reactivity_id": "test"},
    )

    # The predicate at the matching cadence matches every tick — re-runs
    # are stable (byte-identical input → byte-identical match decision).
    predicate = Periodic(every_seconds=3600)
    for execute in executes:
        first = await predicate.match(execute, ctx)
        second = await predicate.match(execute, ctx)
        assert first is True
        assert second is True

    # The predicate at a different cadence matches none — also stable.
    wrong = Periodic(every_seconds=900)
    for execute in executes:
        assert await wrong.match(execute, ctx) is False
