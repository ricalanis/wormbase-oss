"""v2.B Phase 3c — QueryOutcomeProjectionReader correctness.

The reader pulls recent ``projection_query_outcomes`` rows for the
projection-promoted gather path. These tests pin:

  * cosine-ranking: when ``triggering_embedding`` is supplied, the
    returned rows are ordered ASC by cosine distance (DESC by
    similarity).
  * day-window filter: rows older than ``now - days`` are excluded.
  * multi-tenant isolation: rows for company B never leak to company A.
  * empty embedding fallback: when ``triggering_embedding is None``,
    rows are returned in the day window without cosine ordering.
  * Reader-row shape: returned rows look like entry-dicts (kind /
    payload.args.nl_question / .embedding) — Decision D1.

SQLite path uses the Python-cosine implementation; the Postgres path
uses pgvector's ``<=>`` operator. The SQLite tests cover the bulk of
the contract; a smoke test against an actual Postgres+pgvector engine
runs in the integration suite.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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

from wormbase_core.projection_readers import (
    PostgresQueryOutcomeProjectionReader,
    SqliteQueryOutcomeProjectionReader,
    make_projection_reader_for_engine,
)


_COMPANY_A = UUID("00000000-0000-0000-0000-00000000a001")
_COMPANY_B = UUID("00000000-0000-0000-0000-00000000b001")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _setup_sqlite_with_migrations(db_url: str) -> object:
    """Build a SQLite engine + apply v016+v017+v018 migrations."""
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await V016Migration().up(conn)
        await V017Migration().up(conn)
        await V018Migration().up(conn)
    return engine


async def _insert_outcome(
    engine: object,
    *,
    row_id: str,
    company_id: UUID,
    agent_query_id: str,
    nl_question: str,
    embedding: list[float] | None,
    recorded_at: datetime,
    quality_score: str = "0.95",
    used: bool = True,
    useful: bool = True,
) -> None:
    """Write one row into ``projection_query_outcomes`` for testing."""
    import json as _json

    emb_param: str | None = (
        _json.dumps(embedding) if embedding is not None else None
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
                "aqi": agent_query_id,
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


# ---------------------------------------------------------------------------
# Reader correctness (SQLite)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sqlite_reader_returns_entry_shaped_rows(tmp_path) -> None:
    """SQLite path: row dicts come back as ``{kind, entry_id, payload.args.*}``."""
    engine = await _setup_sqlite_with_migrations(
        f"sqlite+aiosqlite:///{tmp_path / 'reader.db'}",
    )
    now = datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc)
    await _insert_outcome(
        engine,
        row_id="row-a",
        company_id=_COMPANY_A,
        agent_query_id="aqi-1",
        nl_question="What is Q3 revenue?",
        embedding=[1.0, 0.5, 0.3, 0.2, 0.1, 0.0, 0.0, 0.0],
        recorded_at=now,
    )

    reader = SqliteQueryOutcomeProjectionReader(engine=engine)
    rows = await reader.recent_outcomes(
        company_id=_COMPANY_A,
        triggering_embedding=None,
        days=30,
        topk_limit=10,
        now=now + timedelta(seconds=1),
    )
    assert len(rows) == 1
    r = rows[0]
    # Entry-shape (Decision D1)
    assert r["kind"] == "execute"
    assert r["entry_id"] == "row-a"
    assert r["payload"]["tool"] == "emit_query_outcome_recorded"
    args = r["payload"]["args"]
    assert args["nl_question"] == "What is Q3 revenue?"
    assert args["agent_query_id"] == "aqi-1"
    assert args["used"] is True
    assert args["useful"] is True
    assert args["embedding"] == [1.0, 0.5, 0.3, 0.2, 0.1, 0.0, 0.0, 0.0]


@pytest.mark.asyncio
async def test_sqlite_reader_orders_by_cosine_similarity(tmp_path) -> None:
    """SQLite path: with a triggering embedding, closer vectors come first."""
    engine = await _setup_sqlite_with_migrations(
        f"sqlite+aiosqlite:///{tmp_path / 'cosine.db'}",
    )
    now = datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc)

    # Trigger vector — direction [1, 0, ...]
    base = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    # Row "near" (cosine ~1)
    await _insert_outcome(
        engine,
        row_id="near",
        company_id=_COMPANY_A,
        agent_query_id="aqi-near",
        nl_question="near vector",
        embedding=[0.99, 0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        recorded_at=now,
    )
    # Row "mid" (cosine ~0.7)
    await _insert_outcome(
        engine,
        row_id="mid",
        company_id=_COMPANY_A,
        agent_query_id="aqi-mid",
        nl_question="mid vector",
        embedding=[0.7, 0.7, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        recorded_at=now,
    )
    # Row "far" (cosine 0; orthogonal)
    await _insert_outcome(
        engine,
        row_id="far",
        company_id=_COMPANY_A,
        agent_query_id="aqi-far",
        nl_question="far vector",
        embedding=[0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        recorded_at=now,
    )

    reader = SqliteQueryOutcomeProjectionReader(engine=engine)
    rows = await reader.recent_outcomes(
        company_id=_COMPANY_A,
        triggering_embedding=base,
        days=30,
        topk_limit=10,
        now=now + timedelta(seconds=1),
    )
    assert [r["entry_id"] for r in rows] == ["near", "mid", "far"]


@pytest.mark.asyncio
async def test_sqlite_reader_topk_limit_truncates(tmp_path) -> None:
    """``topk_limit=N`` returns at most N rows, ordered by similarity."""
    engine = await _setup_sqlite_with_migrations(
        f"sqlite+aiosqlite:///{tmp_path / 'topk.db'}",
    )
    now = datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc)
    base = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    for i in range(5):
        await _insert_outcome(
            engine,
            row_id=f"row-{i}",
            company_id=_COMPANY_A,
            agent_query_id=f"aqi-{i}",
            nl_question=f"q{i}",
            embedding=[1.0 - i * 0.1, i * 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            recorded_at=now,
        )
    reader = SqliteQueryOutcomeProjectionReader(engine=engine)
    rows = await reader.recent_outcomes(
        company_id=_COMPANY_A,
        triggering_embedding=base,
        days=30,
        topk_limit=2,
        now=now + timedelta(seconds=1),
    )
    assert len(rows) == 2
    # Top-2 are the closest (smallest i).
    assert [r["entry_id"] for r in rows] == ["row-0", "row-1"]


@pytest.mark.asyncio
async def test_sqlite_reader_day_window_excludes_old_rows(tmp_path) -> None:
    """Rows older than ``now - days`` are excluded by the SQL filter."""
    engine = await _setup_sqlite_with_migrations(
        f"sqlite+aiosqlite:///{tmp_path / 'window.db'}",
    )
    now = datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc)
    # Recent row — inside the 14d window
    await _insert_outcome(
        engine,
        row_id="recent",
        company_id=_COMPANY_A,
        agent_query_id="aqi-recent",
        nl_question="recent q",
        embedding=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        recorded_at=now - timedelta(days=2),
    )
    # Old row — outside the 14d window
    await _insert_outcome(
        engine,
        row_id="ancient",
        company_id=_COMPANY_A,
        agent_query_id="aqi-ancient",
        nl_question="ancient q",
        embedding=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        recorded_at=now - timedelta(days=30),
    )
    reader = SqliteQueryOutcomeProjectionReader(engine=engine)
    rows = await reader.recent_outcomes(
        company_id=_COMPANY_A,
        triggering_embedding=None,
        days=14,
        topk_limit=10,
        now=now,
    )
    assert [r["entry_id"] for r in rows] == ["recent"]


@pytest.mark.asyncio
async def test_sqlite_reader_multitenant_isolation(tmp_path) -> None:
    """Reader for company A must NOT return company B rows."""
    engine = await _setup_sqlite_with_migrations(
        f"sqlite+aiosqlite:///{tmp_path / 'mt.db'}",
    )
    now = datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc)
    await _insert_outcome(
        engine,
        row_id="a-row",
        company_id=_COMPANY_A,
        agent_query_id="aqi-a",
        nl_question="company A",
        embedding=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        recorded_at=now,
    )
    await _insert_outcome(
        engine,
        row_id="b-row",
        company_id=_COMPANY_B,
        agent_query_id="aqi-b",
        nl_question="company B",
        embedding=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        recorded_at=now,
    )
    reader = SqliteQueryOutcomeProjectionReader(engine=engine)
    rows_a = await reader.recent_outcomes(
        company_id=_COMPANY_A,
        triggering_embedding=None,
        days=30,
        topk_limit=10,
        now=now + timedelta(seconds=1),
    )
    assert [r["entry_id"] for r in rows_a] == ["a-row"]
    rows_b = await reader.recent_outcomes(
        company_id=_COMPANY_B,
        triggering_embedding=None,
        days=30,
        topk_limit=10,
        now=now + timedelta(seconds=1),
    )
    assert [r["entry_id"] for r in rows_b] == ["b-row"]


@pytest.mark.asyncio
async def test_sqlite_reader_no_embedding_skipped_when_ranking(tmp_path) -> None:
    """When triggering_embedding is supplied, rows lacking an embedding
    are skipped from the cosine rank (mirrors the Postgres
    ``embedding IS NOT NULL`` predicate in the vector branch)."""
    engine = await _setup_sqlite_with_migrations(
        f"sqlite+aiosqlite:///{tmp_path / 'skip.db'}",
    )
    now = datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc)
    await _insert_outcome(
        engine,
        row_id="with-emb",
        company_id=_COMPANY_A,
        agent_query_id="aqi-with",
        nl_question="has embedding",
        embedding=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        recorded_at=now,
    )
    await _insert_outcome(
        engine,
        row_id="no-emb",
        company_id=_COMPANY_A,
        agent_query_id="aqi-without",
        nl_question="no embedding",
        embedding=None,
        recorded_at=now,
    )
    reader = SqliteQueryOutcomeProjectionReader(engine=engine)
    # With a trigger embedding, only the row carrying an embedding
    # returns.
    rows = await reader.recent_outcomes(
        company_id=_COMPANY_A,
        triggering_embedding=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        days=30,
        topk_limit=10,
        now=now + timedelta(seconds=1),
    )
    assert [r["entry_id"] for r in rows] == ["with-emb"]
    # Without a trigger embedding, BOTH rows return (the fallback
    # branch doesn't filter on embedding presence).
    rows2 = await reader.recent_outcomes(
        company_id=_COMPANY_A,
        triggering_embedding=None,
        days=30,
        topk_limit=10,
        now=now + timedelta(seconds=1),
    )
    assert {r["entry_id"] for r in rows2} == {"with-emb", "no-emb"}


@pytest.mark.asyncio
async def test_sqlite_reader_fallback_returns_all_recent(tmp_path) -> None:
    """``triggering_embedding=None`` returns all recent rows without
    cosine ordering (Decision D3 fallback branch)."""
    engine = await _setup_sqlite_with_migrations(
        f"sqlite+aiosqlite:///{tmp_path / 'fb.db'}",
    )
    now = datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(3):
        await _insert_outcome(
            engine,
            row_id=f"r-{i}",
            company_id=_COMPANY_A,
            agent_query_id=f"aqi-{i}",
            nl_question=f"q{i}",
            embedding=None,
            recorded_at=now - timedelta(days=i),
        )
    reader = SqliteQueryOutcomeProjectionReader(engine=engine)
    rows = await reader.recent_outcomes(
        company_id=_COMPANY_A,
        triggering_embedding=None,
        days=30,
        topk_limit=100,
        now=now + timedelta(seconds=1),
    )
    assert len(rows) == 3
    # All rows are in the day window.
    assert {r["entry_id"] for r in rows} == {"r-0", "r-1", "r-2"}


@pytest.mark.asyncio
async def test_make_projection_reader_factory_dispatches_to_sqlite(
    tmp_path,
) -> None:
    """``make_projection_reader_for_engine`` selects the SQLite impl for
    a SQLite engine."""
    engine = await _setup_sqlite_with_migrations(
        f"sqlite+aiosqlite:///{tmp_path / 'factory.db'}",
    )
    reader = make_projection_reader_for_engine(engine)
    assert isinstance(reader, SqliteQueryOutcomeProjectionReader)


# ---------------------------------------------------------------------------
# Postgres path (smoke — instantiation + SQL shape only)
# ---------------------------------------------------------------------------


def test_postgres_reader_is_dataclass_with_engine_field() -> None:
    """The Postgres reader's contract: dataclass with ``engine`` field
    so the construction site (worm-core agent_gateway_construction)
    can build it from ``ledger.engine`` symmetrically with the SQLite
    impl."""
    # No actual Postgres connection needed; just confirm the class
    # composes and exposes ``engine``.
    sentinel = object()
    reader = PostgresQueryOutcomeProjectionReader(engine=sentinel)
    assert reader.engine is sentinel


# ---------------------------------------------------------------------------
# Carry-forward #1 (2026-05-12) — SQLite runtime guard for the opt-in
# WORMBASE_GATHER_VIA_PROJECTION env knob. The 2026-05-27 benchmarks
# (docs/superpowers/notes/2026-05-27-perf-baseline.md) measured Path B
# on SQLite at 7.3s for N=5000 entries vs Path A at 3.4ms — a 2000x
# regression. The guard refuses the opt-in against non-Postgres engines
# unless the operator explicitly bypasses via the FORCE env knob.
# ---------------------------------------------------------------------------


class _StubLedger:
    """Minimal ledger stand-in exposing ``engine`` for the construction
    site. ``build_projection_reader_from_ledger`` only ever inspects
    ``ledger.engine``."""

    def __init__(self, engine: object | None) -> None:
        self.engine = engine


class _StubEngine:
    """Minimal engine stand-in exposing ``dialect.name`` for the
    dialect check at the construction site."""

    class _Dialect:
        def __init__(self, name: str) -> None:
            self.name = name

    def __init__(self, dialect_name: str) -> None:
        self.dialect = self._Dialect(dialect_name)


def test_sqlite_runtime_guard_raises_when_env_knob_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQLite + ``WORMBASE_GATHER_VIA_PROJECTION=true`` (no FORCE) →
    raises :class:`GatherViaProjectionUnavailableError` with an
    operator-actionable message that points at the perf-baseline doc."""
    from wormbase_core.agent_gateway_construction import (
        GatherViaProjectionUnavailableError,
        build_projection_reader_from_ledger,
    )

    monkeypatch.setenv("WORMBASE_GATHER_VIA_PROJECTION", "true")
    monkeypatch.delenv(
        "WORMBASE_GATHER_VIA_PROJECTION_FORCE", raising=False,
    )
    ledger = _StubLedger(engine=_StubEngine("sqlite"))

    with pytest.raises(GatherViaProjectionUnavailableError) as exc:
        build_projection_reader_from_ledger(ledger)
    # Operator-actionable message names the dialect, the perf doc, and
    # both escape hatches (unset the knob OR migrate to Postgres OR
    # the FORCE override).
    msg = str(exc.value)
    assert "sqlite" in msg.lower()
    assert "2026-05-27-perf-baseline.md" in msg
    assert "WORMBASE_GATHER_VIA_PROJECTION" in msg
    assert "WORMBASE_GATHER_VIA_PROJECTION_FORCE" in msg


def test_sqlite_runtime_guard_bypassed_by_force_override(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SQLite + env-knob ON + FORCE ON → proceeds (returns a reader)
    AND emits a WARNING log line operators can capture."""
    import logging

    from wormbase_core.agent_gateway_construction import (
        build_projection_reader_from_ledger,
    )

    monkeypatch.setenv("WORMBASE_GATHER_VIA_PROJECTION", "true")
    monkeypatch.setenv("WORMBASE_GATHER_VIA_PROJECTION_FORCE", "true")

    # Use a real SQLite engine so the inner factory returns a real
    # SqliteQueryOutcomeProjectionReader (matches the on-disk path
    # the benchmark uses).
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    ledger = _StubLedger(engine=engine)

    with caplog.at_level(
        logging.WARNING,
        logger="wormbase_core.agent_gateway_construction",
    ):
        reader = build_projection_reader_from_ledger(ledger)

    assert isinstance(reader, SqliteQueryOutcomeProjectionReader)
    # The WARN log captures the operator-explicit override decision.
    warn_records = [
        r for r in caplog.records
        if r.levelno == logging.WARNING
        and "WORMBASE_GATHER_VIA_PROJECTION_FORCE" in r.getMessage()
    ]
    assert len(warn_records) >= 1, (
        "expected at least one WARNING log capturing the override"
    )
    assert "2026-05-27-perf-baseline.md" in warn_records[0].getMessage()


def test_postgres_dialect_proceeds_normally_when_env_knob_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Postgres + env-knob ON → no guard fires; reader builds normally.

    Critical regression check: Postgres deployments are the
    legitimate target of the opt-in knob and must not be impacted.
    """
    from wormbase_core.agent_gateway_construction import (
        build_projection_reader_from_ledger,
    )
    from wormbase_core.projection_readers import (
        PostgresQueryOutcomeProjectionReader,
    )

    monkeypatch.setenv("WORMBASE_GATHER_VIA_PROJECTION", "true")
    monkeypatch.delenv(
        "WORMBASE_GATHER_VIA_PROJECTION_FORCE", raising=False,
    )
    # Stub engine with dialect.name = "postgresql" (sqlalchemy's
    # canonical Postgres dialect identifier). No real Postgres
    # connection needed for the guard logic.
    ledger = _StubLedger(engine=_StubEngine("postgresql"))

    reader = build_projection_reader_from_ledger(ledger)
    assert isinstance(reader, PostgresQueryOutcomeProjectionReader)


def test_env_knob_off_skips_guard_entirely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQLite + env-knob OFF → no guard fires; current behavior unchanged.

    Default deployments (env knob unset) must remain byte-identical.
    The reader still builds (the construction site is called
    unconditionally from cli.py only when ``is_gather_via_projection_enabled()``
    is true — but the guard is internal to
    ``build_projection_reader_from_ledger`` and must respect the
    knob value as the gating signal).
    """
    from wormbase_core.agent_gateway_construction import (
        build_projection_reader_from_ledger,
    )

    monkeypatch.delenv("WORMBASE_GATHER_VIA_PROJECTION", raising=False)
    monkeypatch.delenv(
        "WORMBASE_GATHER_VIA_PROJECTION_FORCE", raising=False,
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    ledger = _StubLedger(engine=engine)

    # Env knob OFF: guard does not fire — reader builds normally.
    reader = build_projection_reader_from_ledger(ledger)
    assert isinstance(reader, SqliteQueryOutcomeProjectionReader)


def test_no_engine_ledger_returns_none_without_guard_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ledger with no ``engine`` attribute (InMemoryLedger pattern)
    returns None regardless of env-knob state — guard does not apply
    because there's no engine to inspect."""
    from wormbase_core.agent_gateway_construction import (
        build_projection_reader_from_ledger,
    )

    monkeypatch.setenv("WORMBASE_GATHER_VIA_PROJECTION", "true")
    ledger = _StubLedger(engine=None)
    assert build_projection_reader_from_ledger(ledger) is None


def test_unknown_dialect_treated_as_non_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dialect name that is neither Postgres nor SQLite (e.g. a
    hypothetical MySQL or DuckDB engine) is treated as non-Postgres
    and triggers the guard. The 2000x regression characterization
    is specific to the SQLite Python-cosine path but the guard is
    conservative: only the Postgres + HNSW combination is known to
    deliver Path B's promised speedup."""
    from wormbase_core.agent_gateway_construction import (
        GatherViaProjectionUnavailableError,
        build_projection_reader_from_ledger,
    )

    monkeypatch.setenv("WORMBASE_GATHER_VIA_PROJECTION", "true")
    monkeypatch.delenv(
        "WORMBASE_GATHER_VIA_PROJECTION_FORCE", raising=False,
    )
    ledger = _StubLedger(engine=_StubEngine("mysql"))

    with pytest.raises(GatherViaProjectionUnavailableError):
        build_projection_reader_from_ledger(ledger)


def test_force_override_only_kicks_in_when_main_knob_also_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The FORCE knob has no effect unless ``WORMBASE_GATHER_VIA_PROJECTION``
    is also set. The two knobs compose: main knob gates the swap,
    FORCE gates the SQLite-dialect bypass. Neither alone activates
    the projection-promoted path."""
    from wormbase_core.agent_gateway_construction import (
        build_projection_reader_from_ledger,
    )

    monkeypatch.delenv("WORMBASE_GATHER_VIA_PROJECTION", raising=False)
    monkeypatch.setenv("WORMBASE_GATHER_VIA_PROJECTION_FORCE", "true")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    ledger = _StubLedger(engine=engine)

    # Main knob OFF → guard does not fire → reader still builds
    # (FORCE alone is a no-op; the construction site never calls
    # this function unless the main knob is on, but the function
    # must be safe regardless).
    reader = build_projection_reader_from_ledger(ledger)
    assert isinstance(reader, SqliteQueryOutcomeProjectionReader)
