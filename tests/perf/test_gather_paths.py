"""Path A + Path B benchmarks — ledger-scan vs projection-promoted gather.

Path A: ``_make_gather_lookback_outcomes`` calls ``ctx.ledger.fetch()``
then in-memory filters by kind + age. O(N) per fire against the full
tenant ledger.

Path B: ``_make_gather_via_projection`` calls a
``QueryOutcomeProjectionReader`` (SQLite or Postgres). With SQLite the
cosine ranking happens in Python after a SELECT pre-filter; with
Postgres + pgvector + HNSW the ranking is index-served.

The cross-over point is what matters operationally — when does Path B
become net-cheaper? This file measures both at N ∈ {100, 1000, 5000}
and reports the data so the projection-promotion threshold can be
calibrated.

Methodology limits:

* SQLite proxies Postgres. The PYTHON-cosine step in
  ``SqliteQueryOutcomeProjectionReader`` is what we measure; the
  Postgres pgvector + HNSW path will be significantly faster on the
  same row count.
* tracemalloc adds ~5-10% overhead; memory column is indicative.
"""

from __future__ import annotations

import asyncio
import json
import tracemalloc
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

# Import the production functions we benchmark. Both factories live in
# the agent-gateway reactivities module (zero changes to production code).
from wormbase_agent_gateway.reactivities import (
    _make_gather_lookback_outcomes,
    _make_gather_via_projection,
)
from wormbase_core.projection_readers import (
    SqliteQueryOutcomeProjectionReader,
)
from wormbase_ledger.projections.migrations.v016_projection_query_outcomes import (
    Migration as V016Migration,
)

from .conftest import (
    EMBEDDING_DIM,
    StubContext,
    StubLedger,
    emit_report_line,
    format_table,
    make_seeded_rng,
    make_vector,
    near_duplicate_vector,
    seed_outcome_entries,
    summarize,
    time_async,
)


_GATHER_LOOKBACK_DAYS = 14


# ---------------------------------------------------------------------------
# Carry-forward #1 (2026-05-12) — Path B benchmarks intentionally measure
# the SQLite projection-reader path. The production guard in
# ``build_projection_reader_from_ledger`` refuses
# ``WORMBASE_GATHER_VIA_PROJECTION=true`` against SQLite engines (the
# 2026-05-27 baseline measured a 2000x regression vs Path A). The
# benchmark suite is the canonical legitimate use case for the
# documented escape hatch: ``WORMBASE_GATHER_VIA_PROJECTION_FORCE=true``.
#
# Path B tests below all build the SqliteQueryOutcomeProjectionReader
# DIRECTLY (bypassing the construction site), so the guard does not
# fire in-process for them today. The autouse fixture below sets FORCE
# defensively so any future refactor that routes Path B perf through
# ``build_projection_reader_from_ledger`` continues to work without
# rediscovering the guard.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _path_b_force_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set ``WORMBASE_GATHER_VIA_PROJECTION_FORCE=true`` for every test
    in this file so the SQLite runtime guard is bypassed end-to-end.

    Belt-and-suspenders: the current Path B tests instantiate the
    reader directly, so the guard never fires in practice. If a
    future refactor routes Path B through
    ``build_projection_reader_from_ledger`` (the construction site),
    the FORCE override stays valid — no test edits required.
    """
    monkeypatch.setenv("WORMBASE_GATHER_VIA_PROJECTION_FORCE", "true")


# ---------------------------------------------------------------------------
# Path A — ledger-scan gather
# ---------------------------------------------------------------------------


@pytest.mark.perf
@pytest.mark.parametrize("n_entries", [100, 1000, 5000])
async def test_path_a_ledger_scan_gather_walltime(
    n_entries: int, company_id: Any,
) -> None:
    """Path A wall-clock for N ledger entries.

    Seeds N outcome-execute entries, builds the lookback gather_fn at
    14 days, and times ``gather_fn(triggering_entry, ctx)``. The 14d
    cutoff exercises the time-filter branch; some entries fall outside
    the window (we seed across a 14d span).
    """
    entries = seed_outcome_entries(n_entries, with_embedding=True)
    ledger = StubLedger(entries)
    ctx = StubContext(ledger=ledger, company_id=company_id)

    gather_fn = _make_gather_lookback_outcomes(_GATHER_LOOKBACK_DAYS)
    triggering = entries[-1]

    async def _run() -> None:
        await gather_fn(triggering, ctx)

    samples = await time_async(_run, warmup=2, n_samples=20)
    result = summarize(f"path_a_n={n_entries}", samples)
    row = result.as_row()
    emit_report_line("path_a", json.dumps(row))

    # Sanity: result must actually contain in-window entries.
    rows = await gather_fn(triggering, ctx)
    assert isinstance(rows, list)
    assert len(rows) > 0
    assert len(rows) <= n_entries


@pytest.mark.perf
@pytest.mark.parametrize("n_entries", [100, 1000, 5000])
async def test_path_a_memory_per_fire(
    n_entries: int, company_id: Any,
) -> None:
    """Path A peak memory allocation per fire (tracemalloc).

    Includes the list-copy that ``ledger.fetch`` produces + the
    filtered output list. Excludes the seed itself (allocated before
    tracemalloc starts).
    """
    entries = seed_outcome_entries(n_entries, with_embedding=True)
    ledger = StubLedger(entries)
    ctx = StubContext(ledger=ledger, company_id=company_id)
    gather_fn = _make_gather_lookback_outcomes(_GATHER_LOOKBACK_DAYS)
    triggering = entries[-1]

    # Warm up — first-fire allocations include lazy imports.
    await gather_fn(triggering, ctx)

    tracemalloc.start()
    try:
        await gather_fn(triggering, ctx)
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    peak_kb = peak_bytes / 1024.0
    emit_report_line(
        "path_a_mem",
        json.dumps({"n_entries": n_entries, "peak_kb": round(peak_kb, 2)}),
    )
    # Sanity: peak should grow with N, but not catastrophically.
    assert peak_kb >= 0


# ---------------------------------------------------------------------------
# Path B — projection-promoted gather (SQLite reader)
# ---------------------------------------------------------------------------


async def _build_projection_engine_and_seed(
    n_entries: int,
    *,
    with_embedding: bool = True,
) -> Any:
    """Provision a fresh SQLite engine with v016 schema + N rows.

    Returns the engine; caller is responsible for dispose if
    deterministic teardown matters. Pytest fixture lifecycle handles
    process exit.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V016Migration().up(conn)

    rng = make_seeded_rng()
    centers = [make_vector(rng) for _ in range(5)]

    entries: list[dict[str, Any]] = []
    now = datetime.now(UTC)
    for i in range(n_entries):
        cluster_ix = i % 5
        emb = (
            near_duplicate_vector(centers[cluster_ix], rng, jitter=0.005)
            if with_embedding
            else None
        )
        entries.append(
            {
                "id": f"out-{i:06d}",
                "company_id": "00000000-0000-0000-0000-0000000fbe17",
                "agent_query_id": f"aq-{i:06d}",
                "nl_question": f"question batch_{cluster_ix} #{i}",
                "final_query_spec": json.dumps({"domain_id": "d", "sql": "SELECT 1"}),
                "result_summary": json.dumps({"rows": 1}),
                "used": True,
                "useful": True,
                "user_correction": None,
                "quality_score": "0.95",
                "embedding": json.dumps(emb) if emb is not None else None,
                "recorded_at": now,
            },
        )

    from sqlalchemy import text as _text
    insert_sql = _text(
        """
        INSERT INTO projection_query_outcomes
        (id, company_id, agent_query_id, nl_question,
         final_query_spec, result_summary, used, useful,
         user_correction, quality_score, embedding, recorded_at)
        VALUES
        (:id, :company_id, :agent_query_id, :nl_question,
         :final_query_spec, :result_summary, :used, :useful,
         :user_correction, :quality_score, :embedding, :recorded_at)
        """
    )
    async with engine.begin() as conn:
        # Batch insert in chunks to keep the per-statement overhead bounded.
        for chunk_start in range(0, len(entries), 500):
            chunk = entries[chunk_start : chunk_start + 500]
            await conn.execute(insert_sql, chunk)
    return engine


@pytest.mark.perf
@pytest.mark.parametrize("n_projection_rows", [100, 1000, 5000])
async def test_path_b_projection_gather_walltime(
    n_projection_rows: int, company_id: Any,
) -> None:
    """Path B wall-clock vs N rows in projection_query_outcomes.

    Topk_limit fixed at default 100; SQLite reader scans all rows then
    cosine-ranks them in Python. The Postgres + pgvector + HNSW path
    bypasses the per-row Python scoring step.
    """
    engine = await _build_projection_engine_and_seed(n_projection_rows)
    reader = SqliteQueryOutcomeProjectionReader(engine=engine)

    # Trigger with a known embedding so the cosine branch runs.
    rng = make_seeded_rng(seed=42)
    trig_emb = make_vector(rng)

    triggering = {
        "kind": "execute",
        "payload": {
            "tool": "emit_query_outcome_recorded",
            "args": {"embedding": trig_emb, "nl_question": "trigger"},
        },
    }
    ctx = StubContext(ledger=None, company_id=company_id)
    ctx.now = lambda: datetime.now(UTC)

    gather_fn = _make_gather_via_projection(
        reader, lookback_days=_GATHER_LOOKBACK_DAYS, topk_limit=100,
    )

    async def _run() -> None:
        await gather_fn(triggering, ctx)

    samples = await time_async(_run, warmup=2, n_samples=10)
    result = summarize(f"path_b_n={n_projection_rows}", samples)
    emit_report_line("path_b", json.dumps(result.as_row()))

    rows = await gather_fn(triggering, ctx)
    assert isinstance(rows, list)
    # TopK caps the result at 100 regardless of N (when N >= 100).
    assert len(rows) <= 100

    await engine.dispose()


@pytest.mark.perf
@pytest.mark.parametrize("topk_limit", [10, 50, 100, 500])
async def test_path_b_topk_sensitivity(
    topk_limit: int, company_id: Any,
) -> None:
    """Path B at fixed N=2000 across varying topk_limit values.

    Establishes that the SQLite reader's cost is dominated by the
    full-row Python scoring loop, not the topk slice — topk only
    bounds the output list size. The Postgres + HNSW path inverts
    this: topk controls how many rows the index walks. Document the
    delta in the report.
    """
    n_projection_rows = 2000
    engine = await _build_projection_engine_and_seed(n_projection_rows)
    reader = SqliteQueryOutcomeProjectionReader(engine=engine)

    rng = make_seeded_rng(seed=42)
    trig_emb = make_vector(rng)
    triggering = {
        "kind": "execute",
        "payload": {
            "tool": "emit_query_outcome_recorded",
            "args": {"embedding": trig_emb, "nl_question": "trigger"},
        },
    }
    ctx = StubContext(ledger=None, company_id=company_id)
    ctx.now = lambda: datetime.now(UTC)

    gather_fn = _make_gather_via_projection(
        reader, lookback_days=_GATHER_LOOKBACK_DAYS, topk_limit=topk_limit,
    )

    async def _run() -> None:
        await gather_fn(triggering, ctx)

    samples = await time_async(_run, warmup=1, n_samples=10)
    result = summarize(f"path_b_topk={topk_limit}", samples)
    emit_report_line("path_b_topk", json.dumps(result.as_row()))

    await engine.dispose()


@pytest.mark.perf
async def test_path_b_no_embedding_fallback(company_id: Any) -> None:
    """Path B with ``triggering_embedding=None`` — non-cosine fallback.

    When the triggering entry lacks an embedding (Phase 3b disabled
    or pre-3b ledger), the reader skips the cosine ranking and
    returns the day-window slice. This should be materially cheaper
    than the cosine path because the per-row scoring step disappears.
    """
    n_projection_rows = 1000
    engine = await _build_projection_engine_and_seed(n_projection_rows)
    reader = SqliteQueryOutcomeProjectionReader(engine=engine)

    triggering = {
        "kind": "execute",
        "payload": {
            "tool": "emit_query_outcome_recorded",
            "args": {"nl_question": "trigger without embedding"},
        },
    }
    ctx = StubContext(ledger=None, company_id=company_id)
    ctx.now = lambda: datetime.now(UTC)

    gather_fn = _make_gather_via_projection(
        reader, lookback_days=_GATHER_LOOKBACK_DAYS, topk_limit=100,
    )

    async def _run() -> None:
        await gather_fn(triggering, ctx)

    samples = await time_async(_run, warmup=1, n_samples=10)
    result = summarize("path_b_no_embedding_n=1000", samples)
    emit_report_line("path_b_no_embedding", json.dumps(result.as_row()))

    await engine.dispose()
