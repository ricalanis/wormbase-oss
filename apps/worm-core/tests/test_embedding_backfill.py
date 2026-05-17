"""v2.B Path 2 — embedding backfill CLI: business-logic contract.

These tests pin the ``run_backfill`` orchestration in
``wormbase_core.scripts.embedding_backfill``. The CLI itself is a thin
``click`` wrapper; correctness lives in the async core that the test
suite exercises against a real SQLite engine + a fake
:class:`EmbeddingService`.

The design we're validating (Option A — projection-only backfill, no
new ledger kind) means every test inserts rows directly into
``projection_query_outcomes`` and asserts the UPDATE landed (or didn't,
for dry-run / multi-tenant / failure paths).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from wormbase_ledger.projections.migrations.v016_projection_query_outcomes import (
    Migration as V016Migration,
)
from wormbase_ledger.projections.migrations.v017_projection_query_templates import (
    Migration as V017Migration,
)
from wormbase_ledger.projections.migrations.v018_resize_embeddings_to_768 import (
    Migration as V018Migration,
)

from click.testing import CliRunner

from wormbase_core.scripts.embedding_backfill import (
    AggregateBackfillReport,
    BackfillReport,
    ProjectionColumnDimMismatchError,
    check_projection_column_dim,
    discover_active_tenants,
    main as cli_main,
    run_backfill,
    run_backfill_all_tenants,
)


_COMPANY_A = UUID("00000000-0000-0000-0000-00000000a001")
_COMPANY_B = UUID("00000000-0000-0000-0000-00000000b001")
_NOW = datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Test infra: SQLite migrations + row insert + fake EmbeddingService
# ---------------------------------------------------------------------------


async def _setup_engine(tmp_path, name: str = "bf.db") -> Any:
    """Create a SQLite engine and apply the v016+v017+v018 migrations
    so ``projection_query_outcomes`` is ready for INSERT/UPDATE."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")
    async with engine.begin() as conn:
        await V016Migration().up(conn)
        await V017Migration().up(conn)
        await V018Migration().up(conn)
    return engine


async def _insert(
    engine: Any,
    *,
    row_id: str,
    company_id: UUID,
    nl_question: str,
    embedding: list[float] | None,
    recorded_at: datetime,
    quality_score: str = "0.95",
    used: bool = True,
    useful: bool = True,
) -> None:
    """Write one projection row. Mirrors the helper in
    ``test_query_outcome_projection_reader.py`` so the contract for
    SQLite-JSON embedding storage stays consistent."""
    emb_param: str | None = (
        json.dumps(embedding) if embedding is not None else None
    )
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO projection_query_outcomes (
                    id, company_id, agent_query_id, nl_question,
                    final_query_spec, result_summary, used, useful,
                    user_correction, quality_score, embedding, recorded_at
                )
                VALUES (
                    :id, :cid, :aqi, :nl, :fqs, :rs, :used, :useful,
                    NULL, :q, :emb, :ts
                )
                """
            ),
            {
                "id": row_id,
                "cid": str(company_id),
                "aqi": f"aqi-{row_id}",
                "nl": nl_question,
                "fqs": "{}",
                "rs": "{}",
                "used": 1 if used else 0,
                "useful": 1 if useful else 0,
                "q": quality_score,
                "emb": emb_param,
                "ts": recorded_at,
            },
        )


async def _read_embedding(engine: Any, row_id: str) -> list[float] | None:
    """Return the persisted embedding for one row (SQLite JSON path)."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT embedding FROM projection_query_outcomes WHERE id = :rid"),
            {"rid": row_id},
        )
        row = result.first()
    if row is None:
        return None
    val = row[0]
    if val is None:
        return None
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (TypeError, ValueError):
            return None
    return list(val) if isinstance(val, (list, tuple)) else None


class FakeEmbeddingService:
    """Deterministic EmbeddingService stand-in for the test suite.

    Maps ``text → [hash(text)/2^64, 0.0, ..., 0.0]`` (``dim`` floats).
    Same text → same vector, so the idempotency tests work without
    depending on Ollama Cloud. ``raise_on`` toggles deterministic
    failure for one specified text — exercises the failure-path
    coverage. ``dim`` / ``model`` are configurable so cross-model
    migration tests can stand in for ``mxbai-embed-large`` (1024 dim)
    while default-arg callers still get the 768-dim stand-in for
    ``nomic-embed-text``.
    """

    def __init__(
        self,
        *,
        raise_on: str | None = None,
        dim: int = 768,
        model: str = "fake-embed",
    ) -> None:
        self._raise_on = raise_on
        self.call_count = 0
        self.dim = dim
        self.model = model

    async def embed(self, text: str) -> Any:
        self.call_count += 1
        if self._raise_on is not None and text == self._raise_on:
            raise RuntimeError(f"forced failure on {text!r}")

        # Deterministic seed in [0, 1) from the text — same text → same
        # vector across runs (idempotency).
        import hashlib

        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        seed = int(h[:16], 16) / float(1 << 64)
        vec = [seed] + [0.0] * (self.dim - 1)
        model_name = self.model

        # Return the same shape the real OllamaCloudEmbeddingService
        # returns — anything with a ``.vector`` attr.
        class _R:
            def __init__(self, vec: Sequence[float]) -> None:
                self.vector = tuple(vec)
                self.dim = len(vec)
                self.model = model_name
                self.latency_ms = 0
                self.cached = False

        return _R(vec)

    async def aclose(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_on_empty_ledger_processes_nothing(tmp_path) -> None:
    """No projection rows at all → report shows found=0, processed=0."""
    engine = await _setup_engine(tmp_path, "empty.db")
    svc = FakeEmbeddingService()

    report = await run_backfill(
        engine=engine,
        embedding_service=svc,
        company_id=_COMPANY_A,
        days=None,
        max_count=100,
        dry_run=False,
        now=_NOW,
    )
    assert isinstance(report, BackfillReport)
    assert report.found == 0
    assert report.processed == 0
    assert report.skipped_already_embedded == 0
    assert report.failed == 0
    assert svc.call_count == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_skips_rows_already_embedded(tmp_path) -> None:
    """Rows where embedding IS NOT NULL are counted as skipped and
    left untouched. Confirms the script doesn't re-embed."""
    engine = await _setup_engine(tmp_path, "skip.db")
    original = [0.42] * 768
    await _insert(
        engine,
        row_id="already",
        company_id=_COMPANY_A,
        nl_question="what is Q3 revenue?",
        embedding=original,
        recorded_at=_NOW,
    )
    svc = FakeEmbeddingService()

    report = await run_backfill(
        engine=engine,
        embedding_service=svc,
        company_id=_COMPANY_A,
        days=None,
        max_count=100,
        dry_run=False,
        now=_NOW,
    )
    assert report.found == 1
    assert report.processed == 0
    assert report.skipped_already_embedded == 1
    assert svc.call_count == 0
    # The persisted embedding is unchanged (the original 0.42 vector).
    persisted = await _read_embedding(engine, "already")
    assert persisted is not None
    assert persisted[0] == 0.42
    await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_computes_and_updates_missing_embeddings(tmp_path) -> None:
    """N rows with embedding=None → tool computes + UPDATEs all N;
    persisted column matches FakeEmbeddingService output."""
    engine = await _setup_engine(tmp_path, "compute.db")
    for i in range(3):
        await _insert(
            engine,
            row_id=f"r-{i}",
            company_id=_COMPANY_A,
            nl_question=f"question {i}",
            embedding=None,
            recorded_at=_NOW - timedelta(hours=i),
        )
    svc = FakeEmbeddingService()

    report = await run_backfill(
        engine=engine,
        embedding_service=svc,
        company_id=_COMPANY_A,
        days=None,
        max_count=100,
        dry_run=False,
        now=_NOW,
    )
    assert report.found == 3
    assert report.processed == 3
    assert report.skipped_already_embedded == 0
    assert report.failed == 0
    assert svc.call_count == 3

    for i in range(3):
        emb = await _read_embedding(engine, f"r-{i}")
        assert emb is not None, f"row r-{i} should have embedding written"
        assert len(emb) == 768
        # Vector matches the FakeEmbeddingService deterministic shape.
        expected = await svc.embed(f"question {i}")
        assert emb[0] == expected.vector[0]
    await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_multitenant_isolation(tmp_path) -> None:
    """--company-id A only touches A's rows; B's stay untouched."""
    engine = await _setup_engine(tmp_path, "mt.db")
    await _insert(
        engine,
        row_id="a-row",
        company_id=_COMPANY_A,
        nl_question="company A question",
        embedding=None,
        recorded_at=_NOW,
    )
    await _insert(
        engine,
        row_id="b-row",
        company_id=_COMPANY_B,
        nl_question="company B question",
        embedding=None,
        recorded_at=_NOW,
    )
    svc = FakeEmbeddingService()

    report = await run_backfill(
        engine=engine,
        embedding_service=svc,
        company_id=_COMPANY_A,
        days=None,
        max_count=100,
        dry_run=False,
        now=_NOW,
    )
    assert report.found == 1
    assert report.processed == 1

    # A got its embedding; B is still NULL.
    assert await _read_embedding(engine, "a-row") is not None
    assert await _read_embedding(engine, "b-row") is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_dry_run_computes_but_does_not_write(tmp_path) -> None:
    """--dry-run computes embeddings (calls EmbeddingService) but
    leaves the DB column NULL."""
    engine = await _setup_engine(tmp_path, "dry.db")
    await _insert(
        engine,
        row_id="dry-r",
        company_id=_COMPANY_A,
        nl_question="dry run question",
        embedding=None,
        recorded_at=_NOW,
    )
    svc = FakeEmbeddingService()

    report = await run_backfill(
        engine=engine,
        embedding_service=svc,
        company_id=_COMPANY_A,
        days=None,
        max_count=100,
        dry_run=True,
        now=_NOW,
    )
    assert report.found == 1
    assert report.processed == 1
    assert report.dry_run is True
    # EmbeddingService was called …
    assert svc.call_count == 1
    # … but the DB column is still NULL.
    assert await _read_embedding(engine, "dry-r") is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_logs_and_continues_on_embedding_service_failure(
    tmp_path,
) -> None:
    """One row's embed() raises; the script logs, increments failed,
    and continues processing the rest."""
    engine = await _setup_engine(tmp_path, "fail.db")
    await _insert(
        engine,
        row_id="ok-1",
        company_id=_COMPANY_A,
        nl_question="ok one",
        embedding=None,
        recorded_at=_NOW - timedelta(hours=2),
    )
    await _insert(
        engine,
        row_id="boom",
        company_id=_COMPANY_A,
        nl_question="explode",  # FakeEmbeddingService raises on this text
        embedding=None,
        recorded_at=_NOW - timedelta(hours=1),
    )
    await _insert(
        engine,
        row_id="ok-2",
        company_id=_COMPANY_A,
        nl_question="ok two",
        embedding=None,
        recorded_at=_NOW,
    )
    svc = FakeEmbeddingService(raise_on="explode")

    report = await run_backfill(
        engine=engine,
        embedding_service=svc,
        company_id=_COMPANY_A,
        days=None,
        max_count=100,
        dry_run=False,
        now=_NOW,
    )
    assert report.found == 3
    assert report.processed == 2  # ok-1 + ok-2
    assert report.failed == 1
    assert any("boom" in row_id for row_id, _err in report.failures)
    # Persistence: ok-1 + ok-2 got embeddings; boom did not.
    assert await _read_embedding(engine, "ok-1") is not None
    assert await _read_embedding(engine, "boom") is None
    assert await _read_embedding(engine, "ok-2") is not None
    await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_respects_max_count_cap(tmp_path) -> None:
    """5 rows in scope, --max-count=2 → script processes 2 and stops.

    Older-by-recorded_at rows go first (ORDER BY recorded_at ASC), so
    the next run will pick up the remaining 3.
    """
    engine = await _setup_engine(tmp_path, "cap.db")
    for i in range(5):
        await _insert(
            engine,
            row_id=f"r-{i}",
            company_id=_COMPANY_A,
            nl_question=f"q{i}",
            embedding=None,
            # i=0 oldest → i=4 newest. Cap=2 picks r-0 and r-1.
            recorded_at=_NOW - timedelta(hours=5 - i),
        )
    svc = FakeEmbeddingService()

    report = await run_backfill(
        engine=engine,
        embedding_service=svc,
        company_id=_COMPANY_A,
        days=None,
        max_count=2,
        dry_run=False,
        now=_NOW,
    )
    assert report.found == 2
    assert report.processed == 2
    assert await _read_embedding(engine, "r-0") is not None
    assert await _read_embedding(engine, "r-1") is not None
    assert await _read_embedding(engine, "r-2") is None
    assert await _read_embedding(engine, "r-3") is None
    assert await _read_embedding(engine, "r-4") is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_is_idempotent_across_runs(tmp_path) -> None:
    """First run backfills N rows; second run reports processed=0
    skipped=N. Same projection state after run-1 and run-2."""
    engine = await _setup_engine(tmp_path, "idem.db")
    for i in range(3):
        await _insert(
            engine,
            row_id=f"r-{i}",
            company_id=_COMPANY_A,
            nl_question=f"idem q{i}",
            embedding=None,
            recorded_at=_NOW - timedelta(hours=i),
        )
    svc = FakeEmbeddingService()

    # First run — does the work.
    r1 = await run_backfill(
        engine=engine,
        embedding_service=svc,
        company_id=_COMPANY_A,
        days=None,
        max_count=100,
        dry_run=False,
        now=_NOW,
    )
    assert r1.processed == 3
    assert r1.skipped_already_embedded == 0
    snapshot1 = [await _read_embedding(engine, f"r-{i}") for i in range(3)]
    assert all(snap is not None for snap in snapshot1)

    # Second run — everything is already embedded, nothing to do.
    r2 = await run_backfill(
        engine=engine,
        embedding_service=svc,
        company_id=_COMPANY_A,
        days=None,
        max_count=100,
        dry_run=False,
        now=_NOW,
    )
    assert r2.found == 3
    assert r2.processed == 0
    assert r2.skipped_already_embedded == 3
    assert r2.failed == 0

    # Persistence: vectors unchanged between run-1 and run-2.
    snapshot2 = [await _read_embedding(engine, f"r-{i}") for i in range(3)]
    assert snapshot1 == snapshot2
    await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_day_window_filters_old_rows(tmp_path) -> None:
    """--days N excludes rows recorded before now - N days.

    Pins the optional time-window scope filter independent of
    --company-id / --max-count.
    """
    engine = await _setup_engine(tmp_path, "window.db")
    await _insert(
        engine,
        row_id="recent",
        company_id=_COMPANY_A,
        nl_question="recent",
        embedding=None,
        recorded_at=_NOW - timedelta(days=2),
    )
    await _insert(
        engine,
        row_id="ancient",
        company_id=_COMPANY_A,
        nl_question="ancient",
        embedding=None,
        recorded_at=_NOW - timedelta(days=60),
    )
    svc = FakeEmbeddingService()

    report = await run_backfill(
        engine=engine,
        embedding_service=svc,
        company_id=_COMPANY_A,
        days=7,
        max_count=100,
        dry_run=False,
        now=_NOW,
    )
    assert report.found == 1
    assert report.processed == 1
    assert await _read_embedding(engine, "recent") is not None
    assert await _read_embedding(engine, "ancient") is None
    await engine.dispose()


# ---------------------------------------------------------------------------
# --all-tenants tests (Phase 3c follow-up: multi-tenant fan-out)
# ---------------------------------------------------------------------------


def test_cli_all_tenants_and_company_id_are_mutually_exclusive() -> None:
    """--all-tenants and --company-id can't both be passed — click
    surfaces a ``UsageError`` (exit code 2 from click).

    Pins the mutual-exclusion gate without spinning up an engine; the
    CLI must reject the combo before any backfill work starts.
    """
    runner = CliRunner()
    result = runner.invoke(
        cli_main,
        [
            "--all-tenants",
            "--company-id",
            str(_COMPANY_A),
            "--dsn",
            "sqlite+aiosqlite:///:memory:",
        ],
    )
    # click renders UsageError as exit code 2.
    assert result.exit_code == 2, result.output
    assert "mutually exclusive" in result.output

    # Symmetric: neither flag also errors out (single-tenant safety).
    result_neither = runner.invoke(
        cli_main,
        ["--dsn", "sqlite+aiosqlite:///:memory:"],
    )
    assert result_neither.exit_code == 2, result_neither.output
    assert "required" in result_neither.output


@pytest.mark.asyncio
async def test_all_tenants_discovers_and_iterates_tenants(tmp_path) -> None:
    """``run_backfill_all_tenants`` discovers distinct company_ids from
    the projection table and runs ``run_backfill`` for each.

    Two tenants seeded; each gets its own per-tenant report; both rows
    end up embedded.
    """
    engine = await _setup_engine(tmp_path, "discover.db")
    await _insert(
        engine,
        row_id="a-row",
        company_id=_COMPANY_A,
        nl_question="company A question",
        embedding=None,
        recorded_at=_NOW,
    )
    await _insert(
        engine,
        row_id="b-row",
        company_id=_COMPANY_B,
        nl_question="company B question",
        embedding=None,
        recorded_at=_NOW,
    )

    # Sanity: the discovery helper sees both.
    discovered = await discover_active_tenants(engine)
    assert sorted(str(cid) for cid in discovered) == sorted(
        [str(_COMPANY_A), str(_COMPANY_B)]
    )

    svc = FakeEmbeddingService()
    seen_tenants: list[UUID] = []

    def _on_report(cid: UUID, report: BackfillReport | None) -> None:
        seen_tenants.append(cid)

    aggregate = await run_backfill_all_tenants(
        engine=engine,
        embedding_service=svc,
        days=None,
        max_count=100,
        dry_run=False,
        now=_NOW,
        on_tenant_report=_on_report,
    )
    assert isinstance(aggregate, AggregateBackfillReport)
    assert aggregate.tenants_discovered == 2
    assert aggregate.tenants_succeeded == 2
    assert aggregate.total_processed == 2
    assert aggregate.total_found == 2
    assert len(aggregate.tenant_failures) == 0
    assert set(str(c) for c in seen_tenants) == {
        str(_COMPANY_A),
        str(_COMPANY_B),
    }
    # Both rows persisted with embeddings.
    assert await _read_embedding(engine, "a-row") is not None
    assert await _read_embedding(engine, "b-row") is not None
    await engine.dispose()


@pytest.mark.asyncio
async def test_all_tenants_with_zero_tenants_exits_cleanly(tmp_path) -> None:
    """Empty projection table → ``run_backfill_all_tenants`` returns an
    aggregate with ``tenants_discovered=0`` and no failures.

    The CLI maps this to exit code 0 (vacuous truth — nothing to do is
    not a failure).
    """
    engine = await _setup_engine(tmp_path, "zero.db")
    svc = FakeEmbeddingService()

    aggregate = await run_backfill_all_tenants(
        engine=engine,
        embedding_service=svc,
        days=None,
        max_count=100,
        dry_run=False,
        now=_NOW,
    )
    assert aggregate.tenants_discovered == 0
    assert aggregate.tenants_succeeded == 0
    assert aggregate.total_processed == 0
    assert aggregate.total_found == 0
    assert len(aggregate.tenant_failures) == 0
    assert svc.call_count == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_all_tenants_one_tenant_failure_continues_with_others(
    tmp_path,
) -> None:
    """If one tenant's embed() raises (catastrophic, e.g. service
    permanently rate-limited for that text), the loop logs it and
    continues with the remaining tenants.

    Here ``_COMPANY_A``'s only row text triggers FakeEmbeddingService's
    ``raise_on`` → the row counts as a row-level failure inside A's
    report (not a tenant-level failure); ``_COMPANY_B``'s row processes
    normally. Tenant-level success count is 2 (both reports returned);
    row-level total_failed is 1.
    """
    engine = await _setup_engine(tmp_path, "fail_one.db")
    await _insert(
        engine,
        row_id="a-row",
        company_id=_COMPANY_A,
        nl_question="boom-text",
        embedding=None,
        recorded_at=_NOW,
    )
    await _insert(
        engine,
        row_id="b-row",
        company_id=_COMPANY_B,
        nl_question="ok-text",
        embedding=None,
        recorded_at=_NOW,
    )
    svc = FakeEmbeddingService(raise_on="boom-text")

    aggregate = await run_backfill_all_tenants(
        engine=engine,
        embedding_service=svc,
        days=None,
        max_count=100,
        dry_run=False,
        now=_NOW,
    )
    assert aggregate.tenants_discovered == 2
    assert aggregate.tenants_succeeded == 2  # both reports came back
    assert aggregate.total_failed == 1  # one row inside A
    assert aggregate.total_processed == 1  # B's row
    # Per-tenant breakdown:
    by_tenant = {cid: rep for cid, rep in aggregate.tenant_reports}
    assert by_tenant[_COMPANY_A].processed == 0
    assert by_tenant[_COMPANY_A].failed == 1
    assert by_tenant[_COMPANY_B].processed == 1
    assert by_tenant[_COMPANY_B].failed == 0
    # B's persisted embedding lands; A's row stays NULL.
    assert await _read_embedding(engine, "a-row") is None
    assert await _read_embedding(engine, "b-row") is not None
    await engine.dispose()


@pytest.mark.asyncio
async def test_all_tenants_respects_dry_run(tmp_path) -> None:
    """``--dry-run`` propagates to every per-tenant call: each tenant's
    EmbeddingService.embed() runs (so we can profile latency / cost
    pre-flight), but no DB writes happen.

    Aggregate ``total_processed`` reflects rows-that-would-be-processed
    (matches single-tenant ``--dry-run`` semantics).
    """
    engine = await _setup_engine(tmp_path, "dry_all.db")
    await _insert(
        engine,
        row_id="a-row",
        company_id=_COMPANY_A,
        nl_question="dry A",
        embedding=None,
        recorded_at=_NOW,
    )
    await _insert(
        engine,
        row_id="b-row",
        company_id=_COMPANY_B,
        nl_question="dry B",
        embedding=None,
        recorded_at=_NOW,
    )
    svc = FakeEmbeddingService()

    aggregate = await run_backfill_all_tenants(
        engine=engine,
        embedding_service=svc,
        days=None,
        max_count=100,
        dry_run=True,
        now=_NOW,
    )
    assert aggregate.tenants_discovered == 2
    assert aggregate.tenants_succeeded == 2
    assert aggregate.total_processed == 2  # would-have-been-processed
    # Every per-tenant report carries dry_run=True.
    for _cid, report in aggregate.tenant_reports:
        assert report.dry_run is True
    # EmbeddingService still got called for both rows (dry-run profiles).
    assert svc.call_count == 2
    # No DB writes happened — both rows remain NULL.
    assert await _read_embedding(engine, "a-row") is None
    assert await _read_embedding(engine, "b-row") is None
    await engine.dispose()


# ---------------------------------------------------------------------------
# --target-model / --target-dim tests (next-pass #5: cross-model migration)
# ---------------------------------------------------------------------------


def test_cli_target_model_with_mismatched_target_dim_errors() -> None:
    """--target-model nomic-embed-text + --target-dim 1024 → UsageError.

    The native dim of nomic-embed-text is 768; passing 1024 is a
    misconfiguration that would silently corrupt cosine distances if
    accepted. The CLI rejects at parse time, mirroring the loud-at-
    construction policy on OllamaCloudEmbeddingService.
    """
    runner = CliRunner()
    result = runner.invoke(
        cli_main,
        [
            "--all-tenants",
            "--target-model", "nomic-embed-text",
            "--target-dim", "1024",
            "--dsn", "sqlite+aiosqlite:///:memory:",
        ],
    )
    assert result.exit_code == 2, result.output
    assert "nomic-embed-text" in result.output
    assert "768" in result.output


def test_cli_target_model_accepts_supported_model() -> None:
    """--target-model mxbai-embed-large + --target-dim 1024 passes parse
    validation (it's a supported model whose native dim is 1024).

    We can't easily wire a real run from inside a unit test because the
    CLI tries to open a Ledger, but we can verify the parse-time gates
    don't reject the combo. Passing an unreachable DSN means we expect
    a non-zero exit but NOT a UsageError(exit_code=2).
    """
    runner = CliRunner()
    result = runner.invoke(
        cli_main,
        [
            "--all-tenants",
            "--target-model", "mxbai-embed-large",
            "--target-dim", "1024",
            "--dsn", "sqlite+aiosqlite:///:memory:",
        ],
    )
    # Parse-time validation must pass (UsageError → exit code 2). The
    # actual run may fail later (in-memory SQLite has no tables); the
    # important thing is we got past parse without "not supported" /
    # "must be supplied together" / dim mismatch.
    assert "must be supplied together" not in result.output
    assert "not supported" not in result.output
    assert "produces 1024-dim" not in result.output


def test_cli_target_model_requires_target_dim() -> None:
    """--target-model without --target-dim → UsageError (and vice versa).

    The flags travel as a pair; either both or neither.
    """
    runner = CliRunner()

    result = runner.invoke(
        cli_main,
        [
            "--all-tenants",
            "--target-model", "mxbai-embed-large",
            "--dsn", "sqlite+aiosqlite:///:memory:",
        ],
    )
    assert result.exit_code == 2, result.output
    assert "must be supplied together" in result.output

    result_inv = runner.invoke(
        cli_main,
        [
            "--all-tenants",
            "--target-dim", "1024",
            "--dsn", "sqlite+aiosqlite:///:memory:",
        ],
    )
    assert result_inv.exit_code == 2, result_inv.output
    assert "must be supplied together" in result_inv.output


@pytest.mark.asyncio
async def test_pre_flight_check_is_noop_on_sqlite(tmp_path) -> None:
    """``check_projection_column_dim`` is a no-op on SQLite (JSON column
    is dim-implicit). Whatever target_dim the operator picks, the
    pre-flight passes; the actual mismatch surface is the cross-model
    re-embed path itself.
    """
    engine = await _setup_engine(tmp_path, "preflight_sqlite.db")
    # Target dim doesn't match the v018 (768) state — but SQLite stores
    # JSON, so the pre-flight skips the check entirely.
    await check_projection_column_dim(engine, target_dim=1024)
    await check_projection_column_dim(engine, target_dim=768)
    await engine.dispose()


@pytest.mark.asyncio
async def test_pre_flight_check_raises_on_postgres_dim_mismatch() -> None:
    """``check_projection_column_dim`` raises ``ProjectionColumnDimMismatchError``
    when the Postgres column dim differs from the target.

    The Postgres path is exercised via a stub engine that returns the
    current column dim from a faked ``execute`` chain. The point of the
    test is the error text — operator must see "Vector(768)", the target
    "Vector(1024)", and the runbook pointer.
    """

    class _StubResult:
        def __init__(self, dim: int) -> None:
            self._dim = dim

        def scalar(self) -> int:
            return self._dim

    class _StubConn:
        def __init__(self, dim: int) -> None:
            self._dim = dim

        async def execute(self, *args, **kwargs) -> _StubResult:
            return _StubResult(self._dim)

        async def __aenter__(self) -> "_StubConn":
            return self

        async def __aexit__(self, *args) -> None:
            return None

    class _StubDialect:
        name = "postgresql"

    class _StubEngine:
        dialect = _StubDialect()

        def __init__(self, dim: int) -> None:
            self._dim = dim

        def connect(self) -> _StubConn:
            return _StubConn(self._dim)

    engine = _StubEngine(dim=768)
    with pytest.raises(ProjectionColumnDimMismatchError) as exc_info:
        await check_projection_column_dim(engine, target_dim=1024)
    msg = str(exc_info.value)
    assert "Vector(768)" in msg
    assert "Vector(1024)" in msg
    assert "WORMBASE_EMBEDDING_DIM=1024" in msg
    assert "v020" in msg or "cross-model-embedding-migration" in msg

    # Same dim → no raise.
    engine_ok = _StubEngine(dim=1024)
    await check_projection_column_dim(engine_ok, target_dim=1024)


@pytest.mark.asyncio
async def test_cross_model_re_embeds_dim_mismatched_rows(tmp_path) -> None:
    """``run_backfill(target_dim=1024)`` re-embeds rows whose persisted
    embedding has a different dim (cross-model migration).

    Three rows: one at the target dim (skip), one at the wrong dim
    (re-embed), one NULL (re-embed). The report distinguishes
    ``re_embedded_cross_model`` from ``processed``.
    """
    engine = await _setup_engine(tmp_path, "cross_model.db")
    # Row already at target dim (1024) — should be skipped.
    await _insert(
        engine,
        row_id="at-target",
        company_id=_COMPANY_A,
        nl_question="already migrated",
        embedding=[0.1] * 1024,
        recorded_at=_NOW - timedelta(hours=3),
    )
    # Row at the wrong dim (768) — should be re-embedded at 1024.
    await _insert(
        engine,
        row_id="wrong-dim",
        company_id=_COMPANY_A,
        nl_question="needs re-embed",
        embedding=[0.5] * 768,
        recorded_at=_NOW - timedelta(hours=2),
    )
    # NULL row — should be re-embedded at 1024 (counts as processed but
    # NOT as cross-model, since the original was empty).
    await _insert(
        engine,
        row_id="null-row",
        company_id=_COMPANY_A,
        nl_question="never embedded",
        embedding=None,
        recorded_at=_NOW - timedelta(hours=1),
    )

    svc = FakeEmbeddingService(dim=1024, model="fake-mxbai")

    report = await run_backfill(
        engine=engine,
        embedding_service=svc,
        company_id=_COMPANY_A,
        days=None,
        max_count=100,
        dry_run=False,
        now=_NOW,
        target_dim=1024,
    )
    assert report.found == 3
    assert report.processed == 2  # wrong-dim + null-row
    assert report.re_embedded_cross_model == 1  # only the wrong-dim row
    assert report.skipped_already_embedded == 1  # at-target
    assert report.failed == 0
    assert svc.call_count == 2

    # at-target unchanged (still 1024-dim [0.1, ...]).
    at_target = await _read_embedding(engine, "at-target")
    assert at_target is not None
    assert len(at_target) == 1024
    assert at_target[0] == 0.1
    # wrong-dim is now 1024-dim (was 768) with the FakeEmbeddingService vec.
    wrong = await _read_embedding(engine, "wrong-dim")
    assert wrong is not None
    assert len(wrong) == 1024
    # null-row now has an embedding.
    null_row = await _read_embedding(engine, "null-row")
    assert null_row is not None
    assert len(null_row) == 1024
    await engine.dispose()


@pytest.mark.asyncio
async def test_cross_model_dry_run_counts_without_writing(tmp_path) -> None:
    """``run_backfill(target_dim=1024, dry_run=True)`` counts rows that
    would be re-embedded but writes nothing. Useful for pre-flight cost
    estimates on a fleet before kicking the real migration off.
    """
    engine = await _setup_engine(tmp_path, "cross_model_dry.db")
    await _insert(
        engine,
        row_id="wrong-dim",
        company_id=_COMPANY_A,
        nl_question="needs re-embed",
        embedding=[0.5] * 768,
        recorded_at=_NOW - timedelta(hours=2),
    )
    await _insert(
        engine,
        row_id="null-row",
        company_id=_COMPANY_A,
        nl_question="never embedded",
        embedding=None,
        recorded_at=_NOW - timedelta(hours=1),
    )

    svc = FakeEmbeddingService(dim=1024, model="fake-mxbai")

    report = await run_backfill(
        engine=engine,
        embedding_service=svc,
        company_id=_COMPANY_A,
        days=None,
        max_count=100,
        dry_run=True,
        now=_NOW,
        target_dim=1024,
    )
    assert report.found == 2
    assert report.processed == 2  # would-have-been-processed
    assert report.re_embedded_cross_model == 1  # the dim-mismatched row
    assert report.dry_run is True
    # EmbeddingService got called (dry-run profiles)…
    assert svc.call_count == 2
    # …but neither row was UPDATEd.
    wrong = await _read_embedding(engine, "wrong-dim")
    assert wrong is not None
    assert len(wrong) == 768  # unchanged
    assert wrong[0] == 0.5
    null_row = await _read_embedding(engine, "null-row")
    assert null_row is None  # still NULL
    await engine.dispose()


@pytest.mark.asyncio
async def test_default_behavior_unchanged_when_target_model_unset(
    tmp_path,
) -> None:
    """Without ``target_dim``, the script preserves the original
    behavior byte-identical: rows with ANY non-NULL embedding (even at a
    "wrong" dim from another model) are skipped, not re-embedded.

    This is the back-compat guarantee — operators running the existing
    `wormbase-embedding-backfill --company-id ... --days 30` invocation
    see the same outcome before and after the cross-model flag landed.
    """
    engine = await _setup_engine(tmp_path, "default_unchanged.db")
    # Row with a 768-dim embedding (pre-Phase-3b shape). Default
    # behavior must NOT re-embed it.
    await _insert(
        engine,
        row_id="pre-existing",
        company_id=_COMPANY_A,
        nl_question="already has 768-dim",
        embedding=[0.7] * 768,
        recorded_at=_NOW - timedelta(hours=2),
    )
    # Row with no embedding — default behavior re-embeds.
    await _insert(
        engine,
        row_id="null-row",
        company_id=_COMPANY_A,
        nl_question="never embedded",
        embedding=None,
        recorded_at=_NOW - timedelta(hours=1),
    )

    svc = FakeEmbeddingService()  # default 768

    # target_dim NOT passed — exercises the default path.
    report = await run_backfill(
        engine=engine,
        embedding_service=svc,
        company_id=_COMPANY_A,
        days=None,
        max_count=100,
        dry_run=False,
        now=_NOW,
    )
    assert report.found == 2
    assert report.processed == 1  # null-row only
    assert report.skipped_already_embedded == 1  # pre-existing untouched
    assert report.re_embedded_cross_model == 0  # never set without target_dim
    assert report.failed == 0
    assert svc.call_count == 1

    # pre-existing row's vector is unchanged.
    pre = await _read_embedding(engine, "pre-existing")
    assert pre is not None
    assert pre[0] == 0.7
    # null-row now has an embedding.
    null_row = await _read_embedding(engine, "null-row")
    assert null_row is not None
    await engine.dispose()
