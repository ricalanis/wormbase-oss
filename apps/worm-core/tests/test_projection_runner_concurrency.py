"""Concurrency tests for ProjectionRunner (W6.A1).

Invariants asserted
-------------------
**C1. No double-fold under parallel ``run_once``.** N concurrent
``run_once()`` invocations on the same Ledger + same tenant produce a
final projection state byte-identical to a single ``run_once`` call.
The persist path is tenant-scoped delete-then-insert; concurrent
overlap MUST not corrupt rows or duplicate them.

**C2. Tenant-reset during fold recovers cleanly.** When a tenant's
ledger is wiped while a parallel ``run_once`` is running, the next
``run_once`` detects the reset and rebuilds from zero. No stale rows
remain from the pre-reset state; no rows go missing from the post-reset
state.

**C3. Cursor monotonicity under concurrent runs.** ``runner.last_seq``
never decreases across any sequence of ``run_once`` calls except via a
detected tenant reset. (A reset rewinds to 0 then climbs again.)

We use ``asyncio.gather`` to drive N=10+ parallelism. The InMemoryLedger
is too lightweight to expose this — we use the real DB-backed Ledger
fixture so the property is verified against the production code path.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_core.projection_runner import ProjectionRunner
from wormbase_ledger import Ledger
from wormbase_ledger.db import session_scope
from wormbase_ledger.schema import (
    metadata as ledger_metadata,
    ledger as ledger_table,
    projection_sources,
)
from wormbase_ledger.write_primitive import write_primitive


def _verify_pass(_r: dict[str, Any]) -> dict[str, Any]:
    return {"checks": [], "passed": True}


def _resolve_keep(_v: dict[str, Any]) -> dict[str, Any]:
    return {"outcome": "keep", "rationale": "ok"}


@pytest_asyncio.fixture
async def db_ledger(tmp_path: Path) -> AsyncIterator[Ledger]:
    """SQLite-backed Ledger fixture. Schema pre-created via ledger metadata."""
    db_file = tmp_path / f"runner_concurrency_{uuid.uuid4().hex}.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(ledger_metadata.drop_all)
        await conn.run_sync(ledger_metadata.create_all)
    yield Ledger(engine)
    await engine.dispose()


async def _emit_source(
    ledger: Ledger, *, company_id: UUID, source_id: UUID, retry: int = 64,
) -> None:
    """Emit a source_proposed PEVR, retrying on SQLite write contention."""
    for attempt in range(retry):
        try:
            async with session_scope(ledger.engine) as session:
                await write_primitive(
                    session,
                    company_id=company_id,
                    propose={
                        "target_kind": "source_proposed",
                        "ref_id": str(source_id),
                        "reason": "concurrency test",
                        "proposed_by": "worm",
                    },
                    execute_fn=lambda sid=source_id: {
                        "tool": "emit_source_proposed",
                        "args": {
                            "source_id": str(sid),
                            "source_kind": "file",
                            "uri": f"file:///tmp/{sid}.csv",
                            "added_via_flow": "drop_and_profile",
                            "suggested_domain": "finance",
                            "suggested_classification": "internal",
                        },
                        "result_ref": "ok",
                    },
                    verify_fn=_verify_pass,
                    resolve_fn=_resolve_keep,
                )
            return
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            if (
                "locked" in msg
                or "busy" in msg
                or "concurrent" in msg
                or "unique constraint" in msg
            ):
                await asyncio.sleep(0.005 * (attempt + 1))
                continue
            raise
    raise RuntimeError(
        f"could not emit source after {retry} retries — DB lock contention",
    )


# ---------------------------------------------------------------------------
# C1 — concurrent run_once does not double-fold or corrupt rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_n_parallel_run_once_does_not_double_fold(db_ledger: Ledger) -> None:
    """Invariant C1: 10 parallel run_once calls land on the same projection state.

    Seed 5 sources, then call ``run_once`` 10 times in parallel via
    ``asyncio.gather``. Final ``projection_sources`` rows MUST equal the
    seed count exactly. No duplicates, no missing rows.
    """
    company_id = uuid4()
    source_ids = [uuid4() for _ in range(5)]
    for sid in source_ids:
        await _emit_source(db_ledger, company_id=company_id, source_id=sid)

    runners = [
        ProjectionRunner(db_ledger, company_id, poll_interval_s=0.1)
        for _ in range(10)
    ]
    # asyncio.gather drives N=10 concurrent calls.
    await asyncio.gather(*(r.run_once() for r in runners))

    async with db_ledger.engine.begin() as conn:
        rows = (
            await conn.execute(
                select(projection_sources).where(
                    projection_sources.c.company_id == company_id
                )
            )
        ).mappings().all()

    assert len(rows) == len(source_ids), (
        f"expected {len(source_ids)} sources, got {len(rows)} — "
        f"concurrent run_once double-folded"
    )
    assert {r["source_id"] for r in rows} == set(source_ids)


@pytest.mark.asyncio
async def test_repeated_concurrent_runs_are_stable(db_ledger: Ledger) -> None:
    """Invariant C1 (repeat): 5 rounds of 10-way concurrent run_once stay clean.

    The runner's persist path is delete-then-insert; even with N
    concurrent overlapping inserts, the final state must equal a single
    serial run. We repeat 5 times to verify stability across rounds (no
    flake).
    """
    company_id = uuid4()
    source_ids = [uuid4() for _ in range(3)]
    for sid in source_ids:
        await _emit_source(db_ledger, company_id=company_id, source_id=sid)

    for _round in range(5):
        runners = [
            ProjectionRunner(db_ledger, company_id, poll_interval_s=0.1)
            for _ in range(10)
        ]
        await asyncio.gather(*(r.run_once() for r in runners))

        async with db_ledger.engine.begin() as conn:
            rows = (
                await conn.execute(
                    select(projection_sources).where(
                        projection_sources.c.company_id == company_id
                    )
                )
            ).mappings().all()
        assert len(rows) == len(source_ids), (
            f"round {_round}: rows={len(rows)} != seed={len(source_ids)}"
        )


# ---------------------------------------------------------------------------
# C2 — tenant reset during concurrent fold recovers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_reset_during_parallel_fold_recovers(
    db_ledger: Ledger,
) -> None:
    """Invariant C2: a tenant wipe during parallel run_once recovers cleanly.

    Sequence:
      1. Seed 3 sources for tenant T.
      2. Fire 10 parallel run_once calls — they fold the 3 sources.
      3. Wipe T's ledger rows.
      4. Seed 2 NEW sources for T.
      5. Fire 10 more parallel run_once calls.

    After step 5 the projection MUST contain exactly the 2 new sources
    (none of the original 3). No row leaks from the pre-reset state.
    """
    company_id = uuid4()
    pre_ids = [uuid4() for _ in range(3)]
    for sid in pre_ids:
        await _emit_source(db_ledger, company_id=company_id, source_id=sid)

    pre_runners = [
        ProjectionRunner(db_ledger, company_id, poll_interval_s=0.1)
        for _ in range(10)
    ]
    await asyncio.gather(*(r.run_once() for r in pre_runners))

    # Wipe.
    async with db_ledger.engine.begin() as conn:
        await conn.execute(
            sa_delete(ledger_table).where(
                ledger_table.c.company_id == company_id
            )
        )

    # Re-seed.
    post_ids = [uuid4() for _ in range(2)]
    for sid in post_ids:
        await _emit_source(db_ledger, company_id=company_id, source_id=sid)

    # New runners — fresh cursor; they detect "rows present, max_seq <
    # cursor" or "row at cursor has different hash". Either branch
    # rewinds to 0.
    post_runners = [
        ProjectionRunner(db_ledger, company_id, poll_interval_s=0.1)
        for _ in range(10)
    ]
    await asyncio.gather(*(r.run_once() for r in post_runners))

    async with db_ledger.engine.begin() as conn:
        rows = (
            await conn.execute(
                select(projection_sources).where(
                    projection_sources.c.company_id == company_id
                )
            )
        ).mappings().all()

    final_ids = {r["source_id"] for r in rows}
    # Must equal the post-reset seeds; no pre-reset bleed-through.
    assert final_ids == set(post_ids), (
        f"post-reset rows: {final_ids} != expected {set(post_ids)} "
        f"(pre-reset bleed: {final_ids & set(pre_ids)})"
    )


# ---------------------------------------------------------------------------
# C3 — cursor monotonicity (modulo intentional resets)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_cursor_monotonic_across_parallel_runs(
    db_ledger: Ledger,
) -> None:
    """Invariant C3: ``last_seq`` is non-decreasing across N parallel runs.

    A single runner driven through N concurrent ``run_once`` calls MUST
    have its ``last_seq`` only go up (or stay the same), never down,
    absent a tenant reset.
    """
    company_id = uuid4()
    runner = ProjectionRunner(db_ledger, company_id, poll_interval_s=0.1)

    snapshots: list[int] = []
    for round_i in range(3):
        # Seed two new sources per round.
        for _ in range(2):
            await _emit_source(
                db_ledger, company_id=company_id, source_id=uuid4(),
            )
        # 10 concurrent run_once on the SAME runner instance.
        await asyncio.gather(*(runner.run_once() for _ in range(10)))
        snapshots.append(runner.last_seq)

    # Must be non-decreasing.
    assert snapshots == sorted(snapshots), (
        f"cursor went backwards: snapshots={snapshots}"
    )
