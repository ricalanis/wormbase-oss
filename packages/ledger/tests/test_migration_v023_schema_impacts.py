"""v023 migration — projection_schema_impacts.

L4 Sub-wave A (2026-06-02). Folded view of lake-side
schema-evolution impacts proposed by the L4 Compounding axis +
confirmed/rejected by admin operators. Schema mirrors the v023
migration; the dialect-aware DDL pattern follows v014/v016/v021/v022
(SQLite-portable + Postgres-friendly).

The SQLite tests below cover the always-on path. The Postgres path
exercises the same Migration class — it's plain SQLAlchemy Core DDL
with no pgvector dependency, so the SQLite tests cover the
production schema by structural equivalence. A Postgres apply test
is gated on WORMBASE_INTEGRATION_DB=1 + a reachable WORMBASE_TEST_DB_URL.
"""
from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations import MIGRATIONS
from wormbase_ledger.projections.migrations.v023_projection_schema_impacts import (
    Migration as V023Migration,
    _TABLE_NAME,
)


_EXPECTED_COLUMNS = {
    "company_id",
    "impact_id",
    "source_id",
    "src_table",
    "src_column",
    "change_kind",
    "impact_kind",
    "tgt_table_id",
    "tgt_column",
    "upstream_lineage_edge_id",
    "confidence",
    "strategy",
    "reasoning",
    "evidence",
    "state",
    "state_changed_at",
    "state_changed_by",
}


# ---------------------------------------------------------------------------
# SQLite path — always exercised
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v023_creates_projection_schema_impacts_idempotent() -> None:
    """First apply creates the table; second apply is a no-op (checkfirst)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V023Migration().up(conn)
    async with engine.begin() as conn:
        # Second apply — must not raise; checkfirst short-circuits.
        await V023Migration().up(conn)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {
                c["name"]
                for c in inspect(sc).get_columns(_TABLE_NAME)
            }
        )
    assert cols == _EXPECTED_COLUMNS, (
        f"unexpected schema: missing={_EXPECTED_COLUMNS - cols} "
        f"extra={cols - _EXPECTED_COLUMNS}"
    )


@pytest.mark.asyncio
async def test_v023_has_composite_primary_key() -> None:
    """Primary key spans (company_id, impact_id) per spec §3.5."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V023Migration().up(conn)
    async with engine.connect() as conn:
        pk = await conn.run_sync(
            lambda sc: inspect(sc).get_pk_constraint(_TABLE_NAME)
        )
    # Order doesn't matter for the constraint contract; compare as sets.
    assert set(pk["constrained_columns"]) == {"company_id", "impact_id"}


@pytest.mark.asyncio
async def test_v023_creates_expected_indexes() -> None:
    """Four secondary indexes: state / source / tgt_table / change_kind."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V023Migration().up(conn)
    async with engine.connect() as conn:
        idxs = await conn.run_sync(
            lambda sc: {i["name"] for i in inspect(sc).get_indexes(_TABLE_NAME)}
        )
    assert "ix_projection_schema_impacts_state" in idxs
    assert "ix_projection_schema_impacts_source" in idxs
    assert "ix_projection_schema_impacts_tgt_table" in idxs
    assert "ix_projection_schema_impacts_change_kind" in idxs


@pytest.mark.asyncio
async def test_v023_state_check_constraint_rejects_bogus_state() -> None:
    """CHECK on state pins the enum {proposed, confirmed, rejected}."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V023Migration().up(conn)
    # Each documented state inserts cleanly.
    async with engine.begin() as conn:
        for i, state in enumerate(("proposed", "confirmed", "rejected")):
            await conn.execute(
                text(
                    "INSERT INTO projection_schema_impacts "
                    "(company_id, impact_id, source_id, src_table, "
                    " src_column, change_kind, impact_kind, "
                    " tgt_table_id, tgt_column, confidence, strategy, "
                    " reasoning, evidence, state, state_changed_at) "
                    f"VALUES ('co1', 'i{i}', 'src1', 't1', 'c1', "
                    f"'column_added', 'tgt_column_unaware', 'tgt1', "
                    f"'tc1', 0.9, 'lineage_edge', 'r', '{{}}', "
                    f"'{state}', '2026-06-02T00:00:00Z')"
                )
            )
    # An out-of-enum state is refused at insert time.
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_schema_impacts "
                    "(company_id, impact_id, source_id, src_table, "
                    " src_column, change_kind, impact_kind, "
                    " tgt_table_id, tgt_column, confidence, strategy, "
                    " reasoning, evidence, state, state_changed_at) "
                    "VALUES ('co1', 'ix', 'src1', 't1', 'c1', "
                    "'column_added', 'tgt_column_unaware', 'tgt1', "
                    "'tc1', 0.9, 'lineage_edge', 'r', '{}', "
                    "'rogue', '2026-06-02T00:00:00Z')"
                )
            )


@pytest.mark.asyncio
async def test_v023_nullable_columns() -> None:
    """upstream_lineage_edge_id + state_changed_by are NULL-able.

    Type-coercion-strategy proposals carry NULL upstream_lineage_edge_id
    (no L3 edge required to detect a coercion impact). A proposed row
    before resolution carries NULL state_changed_by.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V023Migration().up(conn)
        # Insert with NULL upstream_lineage_edge_id + NULL state_changed_by.
        await conn.execute(
            text(
                "INSERT INTO projection_schema_impacts "
                "(company_id, impact_id, source_id, src_table, src_column, "
                " change_kind, impact_kind, tgt_table_id, tgt_column, "
                " upstream_lineage_edge_id, confidence, strategy, reasoning, "
                " evidence, state, state_changed_at, state_changed_by) "
                "VALUES ('co1', 'i-null', 'src1', 't1', 'c1', "
                "'column_type_changed', 'type_coercion_required', "
                "'tgt1', 'tc1', NULL, 0.8, 'type_coercion', 'r', '{}', "
                "'proposed', '2026-06-02T00:00:00Z', NULL)"
            )
        )
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT upstream_lineage_edge_id, state_changed_by "
                    "FROM projection_schema_impacts WHERE impact_id = 'i-null'"
                )
            )
        ).first()
    assert row is not None
    assert row[0] is None
    assert row[1] is None


# ---------------------------------------------------------------------------
# Registration / monotonicity
# ---------------------------------------------------------------------------


def test_v023_registered_in_canonical_migrations() -> None:
    """v023 lives in MIGRATIONS, monotonic and gap-free after v022."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"out of order: {versions}"
    assert 23 in versions, f"expected v23 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )


def test_v023_description_documents_projection_schema_impacts() -> None:
    """Migration description names the table + key invariants for log scan."""
    m = V023Migration()
    assert "projection_schema_impacts" in m.description
    assert "L4" in m.description or "schema-evolution" in m.description


def test_v023_forward_only_no_down_method() -> None:
    """Forward-only doctrine — no ``down`` method on Migration."""
    assert not hasattr(V023Migration(), "down")


# ---------------------------------------------------------------------------
# Postgres path — env-gated (mirrors v019 + v020 + v021 + v022)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v023_applies_cleanly_on_postgres() -> None:
    """v023 applies on Postgres when WORMBASE_INTEGRATION_DB=1.

    Skip cleanly when the integration env is unset OR when the test
    URL points at a non-Postgres backend (SQLite default). The
    migration is plain Core DDL with no pgvector dependency, so the
    SQLite path covers the production shape by structural equivalence;
    this test is belt-and-suspenders.
    """
    if not os.environ.get("WORMBASE_INTEGRATION_DB"):
        pytest.skip("WORMBASE_INTEGRATION_DB not set")
    url = os.environ.get("WORMBASE_TEST_DB_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip(f"WORMBASE_TEST_DB_URL is not Postgres: {url!r}")

    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await V023Migration().up(conn)
        async with engine.connect() as conn:
            cols = await conn.run_sync(
                lambda sc: {
                    c["name"]
                    for c in inspect(sc).get_columns(_TABLE_NAME)
                }
            )
        assert cols == _EXPECTED_COLUMNS
    finally:
        # Clean up so re-runs are idempotent at the schema level.
        async with engine.begin() as conn:
            await conn.execute(sa.text(f"DROP TABLE IF EXISTS {_TABLE_NAME}"))
        await engine.dispose()
