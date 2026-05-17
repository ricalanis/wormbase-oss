"""Path E benchmarks — ReactivityRunner.run_once dispatch loop.

The Runner is the outer loop of every Reactivity. Each cycle:

1. ``ledger.fetch(company_id)`` — full scan of the tenant ledger.
2. Sort by seq, find new rows since cursor.
3. For each new row, dispatch through every registered Reactivity
   (predicate.match → condition.allows → fire).
4. Second ``ledger.fetch`` for post-cycle tail-hash bookkeeping.

The cost shape is roughly:

    fetch_cost(N) + sort(N) + per_entry_dispatch · new_entries · reactivities

The fetch+sort cost dominates when N is large and few rows are new
(steady-state). The dispatch cost dominates during seed-replay or
backlog catch-up.

Methodology limits:

* InMemoryLedger only. The DB-backed ``Ledger`` has different fetch
  cost (one Postgres query per cycle vs in-memory list copy).
* No real reactivities — we use a counting fake. Real reactivity
  fires write more PEVR cycles to the ledger, which the Runner sees
  on the NEXT cycle. The dispatch microbenchmark covers per-call
  cost; an end-to-end test would measure the cascade.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_reactivities import (
    AlwaysAllow,
    EntryKind,
    FiredAction,
    ReactivityContext,
    ReactivityRegistry,
    ReactivityResult,
    ReactivityRunner,
    ReactivityScope,
)

from .conftest import (
    TEST_COMPANY_ID,
    emit_report_line,
    summarize,
    time_async,
)


# ---------------------------------------------------------------------------
# Cheap counting reactivity (minimum work in fire())
# ---------------------------------------------------------------------------


class _NoopReactivity:
    """Minimum-work reactivity that fires on every chat_received."""

    def __init__(self, rid: str = "noop") -> None:
        self.id = rid
        self.name = f"Noop-{rid}"
        self.description = ""
        self.scope: ReactivityScope = "company"
        self.predicate = EntryKind("chat_received")
        self.condition = AlwaysAllow()
        self.fire_count = 0

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        self.fire_count += 1
        # Returning fired=False prevents the registry from doing
        # the post-fire bookkeeping (budget increment + ledger write
        # + novelty record). That keeps the benchmark focused on the
        # dispatch loop itself rather than the post-fire side-effects.
        return ReactivityResult(fired=False)


class _NonMatchingReactivity:
    """Reactivity whose predicate never matches.

    Stress-tests the cost of the predicate.match() short-circuit
    when many reactivities are registered but few apply per entry.
    """

    def __init__(self, rid: str) -> None:
        self.id = rid
        self.name = f"NonMatch-{rid}"
        self.description = ""
        self.scope: ReactivityScope = "company"
        self.predicate = EntryKind("__never_match__")
        self.condition = AlwaysAllow()
        self.fire_count = 0

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        self.fire_count += 1
        return ReactivityResult(fired=False)


# ---------------------------------------------------------------------------
# Ledger seeding (outside the timed region)
# ---------------------------------------------------------------------------


async def _seed_chat_received_pevr(
    ledger: InMemoryLedger, company_id: UUID, n: int,
) -> None:
    """Write N chat_received PEVR cycles. 4 entries per cycle.

    Real chat_received PEVR is what ChannelAdapter writes; this
    matches the shape so the runner's dispatch path is exercised
    against production-realistic entries.
    """
    from uuid import uuid4
    for i in range(n):
        args = {
            "channel_id": "C0",
            "message_id": str(uuid4()),
            "sender_person": str(uuid4()),
            "text": f"perf msg {i}",
            "classification": "internal",
            "platform": "slack",
            "platform_user_id": f"U-{i}",
        }
        await ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "chat_received",
                "ref_id": args["message_id"],
                "reason": "perf-seed",
                "proposed_by": "perf",
            },
            execute_fn=lambda a=args: {
                "tool": "channel_adapter.emit_chat_received",
                "args": a,
                "result_ref": a["message_id"],
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
            quadrant="passive_probabilistic",
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.perf
@pytest.mark.parametrize("n_new_entries", [100, 1000])
async def test_path_e_run_once_walltime(
    n_new_entries: int, company_id: UUID,
) -> None:
    """run_once cost with N new entries + 5 registered reactivities.

    All 5 reactivities are EntryKind("chat_received") so each
    chat_received execute row triggers 5 predicate matches; only
    the matching ones run condition.allows + fire.
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=company_id)
    reactivities = [_NoopReactivity(f"r{i}") for i in range(5)]
    for r in reactivities:
        registry.register(r)
    runner = ReactivityRunner(
        ledger=ledger, company_id=company_id, registry=registry,
        poll_interval_s=1.0,
    )

    # Seed BEFORE measurement. Each PEVR is 4 entries → 4N total.
    await _seed_chat_received_pevr(ledger, company_id, n_new_entries)

    # First call processes all N entries (cursor=0).
    # Second call is steady-state (cursor at tail, no new rows).
    cold_samples = await time_async(runner.run_once, warmup=0, n_samples=1)
    cold = summarize(f"path_e_cold_n_new={n_new_entries}", cold_samples)
    emit_report_line("path_e_cold", json.dumps(cold.as_row()))

    # Warm: cursor at tail, no new entries. Just the fetch + sort cost.
    warm_samples = await time_async(runner.run_once, warmup=1, n_samples=10)
    warm = summarize(f"path_e_warm_n_entries={n_new_entries * 4}", warm_samples)
    emit_report_line("path_e_warm", json.dumps(warm.as_row()))

    # All 5 reactivities fired on each chat_received execute row
    # (N execute rows out of 4N entries).
    for r in reactivities:
        assert r.fire_count == n_new_entries


@pytest.mark.perf
async def test_path_e_dispatch_cost_per_reactivity(company_id: UUID) -> None:
    """Per-reactivity dispatch overhead.

    1, 5, 10, 25 reactivities registered. Same N=100 new entries.
    The fetch + sort cost is constant; the dispatch cost scales
    with reactivities × matching_entries.
    """
    rows: list[dict] = []
    for n_reacs in [1, 5, 10, 25]:
        ledger = InMemoryLedger()
        registry = ReactivityRegistry(ledger=ledger, company_id=company_id)
        for i in range(n_reacs):
            registry.register(_NoopReactivity(f"r{i}"))
        runner = ReactivityRunner(
            ledger=ledger, company_id=company_id, registry=registry,
            poll_interval_s=1.0,
        )
        await _seed_chat_received_pevr(ledger, company_id, 100)

        samples = await time_async(runner.run_once, warmup=0, n_samples=1)
        result = summarize(f"path_e_dispatch_n_reacs={n_reacs}", samples)
        emit_report_line("path_e_dispatch_scale", json.dumps(result.as_row()))
        rows.append(result.as_row())


@pytest.mark.perf
async def test_path_e_nonmatching_predicate_cost(company_id: UUID) -> None:
    """Cost when most registered reactivities don't match.

    25 non-matching + 1 matching reactivity. Most cycles short-circuit
    on predicate.match. Measures the EntryKind cheap-path cost.
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=company_id)
    for i in range(25):
        registry.register(_NonMatchingReactivity(f"nm{i}"))
    matcher = _NoopReactivity("match")
    registry.register(matcher)

    runner = ReactivityRunner(
        ledger=ledger, company_id=company_id, registry=registry,
        poll_interval_s=1.0,
    )
    await _seed_chat_received_pevr(ledger, company_id, 100)

    samples = await time_async(runner.run_once, warmup=0, n_samples=1)
    result = summarize("path_e_nonmatching_n_reacs=26_n_new=100", samples)
    emit_report_line("path_e_nonmatch", json.dumps(result.as_row()))
    assert matcher.fire_count == 100


@pytest.mark.perf
async def test_path_e_steady_state_no_new_entries(company_id: UUID) -> None:
    """Steady-state run_once cost when nothing is new.

    This is the dominant production cost — the runner polls every
    1s + reads the full ledger every cycle. With 5000 entries already
    in the ledger and zero new ones, run_once should be doing just
    two ledger.fetch + sort + cursor-check.
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=company_id)
    for i in range(5):
        registry.register(_NoopReactivity(f"r{i}"))
    runner = ReactivityRunner(
        ledger=ledger, company_id=company_id, registry=registry,
        poll_interval_s=1.0,
    )

    # Seed 1250 chat_received PEVR cycles = 5000 entries.
    await _seed_chat_received_pevr(ledger, company_id, 1250)
    # Drive cursor to tail.
    await runner.run_once()

    samples = await time_async(runner.run_once, warmup=2, n_samples=10)
    result = summarize("path_e_steady_state_n_entries=5000", samples)
    emit_report_line("path_e_steady", json.dumps(result.as_row()))
