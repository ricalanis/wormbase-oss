"""Tests for the ``Periodic`` predicate (v2.B Phase 3, 2026-05-12).

Matches ``clock_tick`` execute envelopes with a given ``tick_interval_s``.
Drives time-based Reactivities — the v2.B Phase 3 swap moves axis 4
(``semantic_gap_to_escalation``) from
``EntryKind("semantic_gap_proposed")`` to
``Periodic(every_seconds=3600)`` so the Reactivity fires on a real
cadence regardless of new-gap traffic.

Note on name collision: ``wormbase_reactivities.conditions.Periodic`` is
a Condition (wall-clock bucket gate used by ``KeepRatePublishReactivity``);
the predicate tested here is a Predicate. The package surface re-exports
the predicate as ``Periodic`` and aliases the condition to
``ConditionPeriodic`` so both can be imported side-by-side.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from wormbase_reactivities import (
    EntryKind,
    ReactivityContext,
    ReactivityRegistry,
)
from wormbase_reactivities.predicates import Periodic


def _ctx(ledger, company_id: UUID) -> ReactivityContext:
    registry = ReactivityRegistry(
        ledger=ledger, company_id=company_id,
        now=lambda: datetime(2026, 5, 12, 12, 0, 0, tzinfo=UTC),
    )
    return ReactivityContext(
        ledger=ledger,
        company_id=company_id,
        registry=registry,
        now=registry._now,  # noqa: SLF001
        extras={"reactivity_id": "test_periodic"},
    )


def _clock_tick_execute(
    *, tick_interval_s: int, sequence_number: int,
) -> dict[str, Any]:
    """Construct a canonical ``clock_tick`` execute envelope (the shape
    ``ClockTickEmitter`` writes to the ledger)."""
    return {
        "kind": "execute",
        "seq": 1,
        "payload": {
            "tool": "emit_clock_tick",
            "args": {
                "tick_interval_s": tick_interval_s,
                "sequence_number": sequence_number,
            },
            "result_ref": f"clock_tick:{tick_interval_s}:{sequence_number}",
        },
    }


@pytest.mark.asyncio
async def test_matches_clock_tick_with_matching_interval(
    ledger, company_id: UUID,
) -> None:
    """The canonical happy path: a clock_tick execute envelope at the
    same cadence the predicate was configured with — match."""
    ctx = _ctx(ledger, company_id)
    p = Periodic(every_seconds=3600)
    entry = _clock_tick_execute(tick_interval_s=3600, sequence_number=0)
    assert await p.match(entry, ctx) is True


@pytest.mark.asyncio
async def test_does_not_match_wrong_kind(ledger, company_id: UUID) -> None:
    """The predicate only matches ``emit_clock_tick`` — any other tool
    on an execute envelope is skipped, even at the same cadence."""
    ctx = _ctx(ledger, company_id)
    p = Periodic(every_seconds=3600)
    entry = {
        "kind": "execute",
        "seq": 1,
        "payload": {
            "tool": "emit_semantic_gap_proposed",
            "args": {"tick_interval_s": 3600},
        },
    }
    assert await p.match(entry, ctx) is False


@pytest.mark.asyncio
async def test_does_not_match_wrong_interval(
    ledger, company_id: UUID,
) -> None:
    """A clock_tick at a different cadence than configured — no match.
    Critical for multi-cadence support (hourly vs daily emitters)."""
    ctx = _ctx(ledger, company_id)
    p = Periodic(every_seconds=3600)
    entry = _clock_tick_execute(tick_interval_s=900, sequence_number=0)
    assert await p.match(entry, ctx) is False


@pytest.mark.asyncio
async def test_does_not_match_missing_args(ledger, company_id: UUID) -> None:
    """Defensive: a malformed clock_tick row missing ``args`` returns
    False instead of raising — the runner should keep moving."""
    ctx = _ctx(ledger, company_id)
    p = Periodic(every_seconds=3600)
    entry = {
        "kind": "execute",
        "seq": 1,
        "payload": {"tool": "emit_clock_tick"},  # no args
    }
    assert await p.match(entry, ctx) is False


@pytest.mark.asyncio
async def test_does_not_match_envelope_kind_clock_tick(
    ledger, company_id: UUID,
) -> None:
    """A non-execute envelope (propose / verify / resolve) for the
    clock_tick cycle does NOT match. The predicate intentionally fires
    on the execute envelope so it lines up with how every other
    emit_*-shaped event flows through the runner."""
    ctx = _ctx(ledger, company_id)
    p = Periodic(every_seconds=3600)
    entry = {
        "kind": "propose",
        "seq": 1,
        "payload": {
            "target_kind": "clock_tick",
            "ref_id": "clock_tick:0",
        },
    }
    assert await p.match(entry, ctx) is False


@pytest.mark.asyncio
async def test_composes_with_and(ledger, company_id: UUID) -> None:
    """``Periodic`` composes via ``&`` like every other predicate.
    Useful for Phase 3+ Reactivities that want "every tick AND some
    extra condition"."""
    ctx = _ctx(ledger, company_id)
    composed = Periodic(every_seconds=3600) & EntryKind("clock_tick")
    entry = _clock_tick_execute(tick_interval_s=3600, sequence_number=0)
    # EntryKind("clock_tick") on an execute envelope matches when
    # payload.tool == "emit_clock_tick" (per EntryKind contract).
    assert await composed.match(entry, ctx) is True


@pytest.mark.asyncio
async def test_composes_with_or(ledger, company_id: UUID) -> None:
    """``Periodic | EntryKind`` matches both — supports "react to tick
    OR an out-of-band trigger" patterns if a Phase 3+ axis needs it."""
    ctx = _ctx(ledger, company_id)
    composed = Periodic(every_seconds=3600) | EntryKind("semantic_gap_proposed")

    # Match via Periodic side
    tick = _clock_tick_execute(tick_interval_s=3600, sequence_number=0)
    assert await composed.match(tick, ctx) is True

    # Match via EntryKind side
    gap = {
        "kind": "execute",
        "seq": 1,
        "payload": {
            "tool": "emit_semantic_gap_proposed",
            "args": {"agent_id": "agent-x", "nl_question": "?"},
        },
    }
    assert await composed.match(gap, ctx) is True


@pytest.mark.asyncio
async def test_periodic_is_frozen_dataclass(
    ledger, company_id: UUID,
) -> None:
    """The dataclass is frozen — the predicate is value-typed so it can
    be shared safely between Reactivities + (eventually) hashed."""
    p = Periodic(every_seconds=3600)
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        p.every_seconds = 900  # type: ignore[misc]
