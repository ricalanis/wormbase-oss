"""Contract tests for ``ClockTickPayload`` (v2.B Phase 3, 2026-05-12).

A periodic ledger-resident tick written by ``ClockTickEmitter`` to drive
time-based Reactivities (the ``Periodic(every_seconds=N)`` predicate).
Replaces the gap-escalation axis's previous "fire on new gap write"
trigger with a real cadence-driven tick.

Per the schema-evolution doctrine (Rule 2 additive-only), this kind
brings ``KIND_REGISTRY`` from 99 → 100, under the 120 ceiling raised by
Wave F Addendum 1.

Tests pin:

* The kind auto-registers in ``KIND_REGISTRY`` + ``ALL_KINDS`` via
  ``EntryPayload.__init_subclass__``.
* Construction with valid args + rejection of extras (Pydantic
  ``extra='forbid'``).
* Round-trip via ``model_dump → model_validate`` byte-equivalently.
* ``tick_interval_s`` and ``sequence_number`` are the only payload
  fields (self-describing cadence; per-tenant per-cadence monotonic).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError
from wormbase_ledger import ClockTickPayload
from wormbase_ledger.entries import ALL_KINDS, KIND_REGISTRY


def test_clock_tick_kind_registered() -> None:
    """``clock_tick`` auto-registers in ``KIND_REGISTRY`` (and ``ALL_KINDS``)."""
    assert "clock_tick" in KIND_REGISTRY
    assert KIND_REGISTRY["clock_tick"] is ClockTickPayload
    assert "clock_tick" in ALL_KINDS


def test_clock_tick_constructs() -> None:
    """Construction with the two payload fields succeeds."""
    p = ClockTickPayload(tick_interval_s=3600, sequence_number=0)
    assert p.tick_interval_s == 3600
    assert p.sequence_number == 0
    assert p.kind == "clock_tick"


def test_clock_tick_rejects_extras() -> None:
    """``extra='forbid'`` keeps the payload tight — no opportunistic
    extra fields slip past the validator."""
    with pytest.raises(ValidationError):
        ClockTickPayload(
            tick_interval_s=3600,
            sequence_number=0,
            not_allowed=True,  # type: ignore[call-arg]
        )


def test_clock_tick_roundtrips() -> None:
    """``model_dump → model_validate`` is byte-stable so wire-replay
    reproduces the entry exactly."""
    p = ClockTickPayload(tick_interval_s=900, sequence_number=42)
    again = ClockTickPayload.model_validate(p.model_dump())
    assert again == p


def test_clock_tick_requires_both_fields() -> None:
    """Both fields are required (no defaults) — the emitter writes
    them explicitly every tick, and forgetting either is a bug
    surface we want loud about."""
    with pytest.raises(ValidationError):
        ClockTickPayload(tick_interval_s=3600)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ClockTickPayload(sequence_number=0)  # type: ignore[call-arg]
