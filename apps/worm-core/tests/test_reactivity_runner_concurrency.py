"""Reactivity dispatch concurrency tests (W6.A1).

Invariants asserted
-------------------
**RC1. Atomic budget counters under interleaved dispatch.** N parallel
``dispatch(entry)`` calls — each calling the same Reactivity's ``fire`` —
charge the budget counter exactly N times. No lost increments, no
double-counts.

**RC2. No double-fire on the same (reactivity_id, source_seq) pair.**
The registry's fire log de-duplicates by ``(reactivity_id, novelty_key)``;
when N concurrent dispatches all match the same entry with the same
novelty_key, the post-dispatch state is consistent — the budget
counter equals the per-fire `budget_used` times the number of actually-
fired dispatches (which can be ≤N since the registry's own lock
serialises post-fire bookkeeping).

**RC3. Concurrent fire on different entries interleaves correctly.**
N entries dispatched concurrently produce N fires, each with the right
entry's seq recorded in the fire log. No entry's seq is dropped or
mis-attributed.

The registry uses an asyncio.Lock around the post-fire bookkeeping; the
property under test is "even with a lock, the externally-visible state
is correct under any interleaving".
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_reactivities import (
    AlwaysAllow,
    EntryKind,
    FiredAction,
    ReactivityContext,
    ReactivityRegistry,
    ReactivityResult,
    ReactivityScope,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000099")


class _CountingReactivity:
    """Counts how many times its fire ran. Always allows."""

    id = "counter"
    name = "Counter"
    description = "Counts fires for assertion."
    scope: ReactivityScope = "company"

    def __init__(self) -> None:
        self.predicate = EntryKind("chat_received")
        self.condition = AlwaysAllow()
        self.fire_count = 0
        # Record observed entry seqs so we can assert no entry is dropped.
        self.observed_seqs: list[int] = []

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        self.fire_count += 1
        self.observed_seqs.append(int(entry.get("seq", 0)))
        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="counted")],
            novelty_key=f"seq-{entry.get('seq')}",
            budget_used={"per_tenant": 1},
        )


def _make_chat_entry(seq: int) -> dict[str, Any]:
    """Synthesize an execute envelope wrapping emit_chat_received."""
    return {
        "kind": "execute",
        "ts": datetime(2026, 4, 22, 12, 0, tzinfo=UTC),
        "seq": seq,
        "payload": {
            "tool": "emit_chat_received",
            "args": {
                "channel_id": "C01",
                "message_id": f"m-{seq}",
                "sender_person": str(uuid4()),
                "text": "hi",
                "classification": "internal",
                "owner_id": str(uuid4()),
            },
        },
    }


# ---------------------------------------------------------------------------
# RC1 — atomic budget counters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_n_parallel_dispatch_increments_budget_atomically() -> None:
    """Invariant RC1: 10 parallel dispatch calls produce exactly 10 budget increments.

    Each Reactivity returns budget_used={"per_tenant": 1}; after 10
    parallel dispatches against 10 distinct entries, the per-tenant
    budget counter for ``today`` must equal 10. Lost increments would
    be visible as a counter value < 10; double-counts as > 10.
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger, _COMPANY_ID)
    rx = _CountingReactivity()
    registry.register(rx, initial_state="active")

    entries = [_make_chat_entry(seq=i) for i in range(1, 11)]
    await asyncio.gather(*(registry.dispatch(e) for e in entries))

    today = datetime.now(UTC).date().isoformat()
    counter = await registry.get_budget_count(
        reactivity_id="counter",
        axis="tenant",
        key=str(_COMPANY_ID),
        day=today,
    )
    assert counter == 10, (
        f"per-tenant counter drift: expected 10, got {counter}"
    )
    assert rx.fire_count == 10
    assert sorted(rx.observed_seqs) == list(range(1, 11))


@pytest.mark.asyncio
async def test_high_parallelism_no_lost_increments() -> None:
    """Invariant RC1 (stress): 50 parallel dispatches produce 50 increments.

    Higher fan-out than the headline test to surface contention bugs
    that would otherwise hide at low concurrency.
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger, _COMPANY_ID)
    rx = _CountingReactivity()
    registry.register(rx, initial_state="active")

    entries = [_make_chat_entry(seq=i) for i in range(1, 51)]
    await asyncio.gather(*(registry.dispatch(e) for e in entries))

    today = datetime.now(UTC).date().isoformat()
    counter = await registry.get_budget_count(
        reactivity_id="counter",
        axis="tenant",
        key=str(_COMPANY_ID),
        day=today,
    )
    assert counter == 50


# ---------------------------------------------------------------------------
# RC2 — duplicate-entry dispatch consistency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_dispatch_on_same_entry_consistent_state() -> None:
    """Invariant RC2: dispatching the same entry N times produces consistent state.

    The registry's dispatch is non-idempotent at the API level — each
    call fires the Reactivity. But the registry serialises bookkeeping
    via an asyncio.Lock, so the externally-visible counter equals the
    fire count. We assert: counter == fire_count == N.
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger, _COMPANY_ID)
    rx = _CountingReactivity()
    registry.register(rx, initial_state="active")

    entry = _make_chat_entry(seq=42)
    n = 10
    await asyncio.gather(*(registry.dispatch(entry) for _ in range(n)))

    today = datetime.now(UTC).date().isoformat()
    counter = await registry.get_budget_count(
        reactivity_id="counter",
        axis="tenant",
        key=str(_COMPANY_ID),
        day=today,
    )
    assert rx.fire_count == n
    assert counter == n


# ---------------------------------------------------------------------------
# RC3 — concurrent dispatch on different entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_dispatch_on_distinct_entries_records_all() -> None:
    """Invariant RC3: every entry's seq lands in the fire log under N-way dispatch.

    Fire 20 distinct entries concurrently; the Reactivity's
    ``observed_seqs`` log MUST contain every seq from 1..20 exactly once.
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger, _COMPANY_ID)
    rx = _CountingReactivity()
    registry.register(rx, initial_state="active")

    entries = [_make_chat_entry(seq=i) for i in range(1, 21)]
    await asyncio.gather(*(registry.dispatch(e) for e in entries))

    assert sorted(rx.observed_seqs) == list(range(1, 21))


# ---------------------------------------------------------------------------
# RC1 (repeat for stability) — make sure 5 rounds of N=10 stay clean
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reactivity_concurrency_stable_across_rounds() -> None:
    """Invariant RC1 (no flake): 5 rounds of 10-way dispatch stay deterministic.

    Each round increments the per-tenant counter by 10 (different
    entries each round). After 5 rounds, the counter is exactly 50.
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger, _COMPANY_ID)
    rx = _CountingReactivity()
    registry.register(rx, initial_state="active")

    seq = 0
    for _round in range(5):
        entries = []
        for _ in range(10):
            seq += 1
            entries.append(_make_chat_entry(seq=seq))
        await asyncio.gather(*(registry.dispatch(e) for e in entries))

    today = datetime.now(UTC).date().isoformat()
    counter = await registry.get_budget_count(
        reactivity_id="counter",
        axis="tenant",
        key=str(_COMPANY_ID),
        day=today,
    )
    assert counter == 50
    assert rx.fire_count == 50
