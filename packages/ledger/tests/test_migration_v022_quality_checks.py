"""v022 migration — projection_quality_checks.

L7 Sub-wave A (2026-05-30). Folded view of lake-side quality checks
proposed by the L7 Compounding axis + confirmed/rejected by admin
operators. Schema mirrors the v022 migration; the dialect-aware
DDL pattern follows v014/v016/v021 (SQLite-portable + Postgres-friendly).

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
from wormbase_ledger.projections.migrations.v022_projection_quality_checks import (
    Migration as V022Migration,
    _TABLE_NAME,
)


_EXPECTED_COLUMNS = {
    "company_id",
    "check_id",
    "table_id",
    "column",
    "check_kind",
    "config",
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
async def test_v022_creates_projection_quality_checks_idempotent() -> None:
    """First apply creates the table; second apply is a no-op (checkfirst)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V022Migration().up(conn)
    async with engine.begin() as conn:
        # Second apply — must not raise; checkfirst short-circuits.
        await V022Migration().up(conn)
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
async def test_v022_has_composite_primary_key() -> None:
    """Primary key spans (company_id, check_id) per spec §3.6."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V022Migration().up(conn)
    async with engine.connect() as conn:
        pk = await conn.run_sync(
            lambda sc: inspect(sc).get_pk_constraint(_TABLE_NAME)
        )
    # Order doesn't matter for the constraint contract; compare as sets.
    assert set(pk["constrained_columns"]) == {"company_id", "check_id"}


@pytest.mark.asyncio
async def test_v022_creates_expected_indexes() -> None:
    """Three secondary indexes: state, table, kind — each tenant-scoped."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V022Migration().up(conn)
    async with engine.connect() as conn:
        idxs = await conn.run_sync(
            lambda sc: {i["name"] for i in inspect(sc).get_indexes(_TABLE_NAME)}
        )
    assert "ix_projection_quality_checks_state" in idxs
    assert "ix_projection_quality_checks_table" in idxs
    assert "ix_projection_quality_checks_kind" in idxs


@pytest.mark.asyncio
async def test_v022_state_check_constraint_rejects_bogus_state() -> None:
    """CHECK on state pins the enum {proposed, confirmed, rejected}."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V022Migration().up(conn)
    # Each documented state inserts cleanly.
    async with engine.begin() as conn:
        for i, state in enumerate(("proposed", "confirmed", "rejected")):
            await conn.execute(
                text(
                    "INSERT INTO projection_quality_checks "
                    "(company_id, check_id, table_id, check_kind, "
                    " config, confidence, strategy, reasoning, "
                    " evidence, state, state_changed_at) "
                    f"VALUES ('co1', 'c{i}', 't1', 'not_null', "
                    f"'{{}}', 0.9, 'schema_pattern', 'r', '{{}}', "
                    f"'{state}', '2026-05-30T00:00:00Z')"
                )
            )
    # An out-of-enum state is refused at insert time.
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_quality_checks "
                    "(company_id, check_id, table_id, check_kind, "
                    " config, confidence, strategy, reasoning, "
                    " evidence, state, state_changed_at) "
                    "VALUES ('co1', 'cx', 't1', 'not_null', "
                    "'{}', 0.9, 'schema_pattern', 'r', '{}', "
                    "'rogue', '2026-05-30T00:00:00Z')"
                )
            )


@pytest.mark.asyncio
async def test_v022_nullable_columns() -> None:
    """column / state_changed_by are NULL-able.

    Table-level checks have NULL column (e.g. row_count_range,
    freshness); a proposed row before resolution has NULL
    state_changed_by.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V022Migration().up(conn)
        # Insert a table-level check with NULL column + NULL state_changed_by.
        await conn.execute(
            text(
                "INSERT INTO projection_quality_checks "
                "(company_id, check_id, table_id, \"column\", check_kind, "
                " config, confidence, strategy, reasoning, evidence, "
                " state, state_changed_at, state_changed_by) "
                "VALUES ('co1', 'c-null', 't1', NULL, 'row_count_range', "
                "'{}', 1.0, 'dbt_tests', 'r', '{}', "
                "'proposed', '2026-05-30T00:00:00Z', NULL)"
            )
        )
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT \"column\", state_changed_by "
                    "FROM projection_quality_checks WHERE check_id = 'c-null'"
                )
            )
        ).first()
    assert row is not None
    assert row[0] is None
    assert row[1] is None


# ---------------------------------------------------------------------------
# Registration / monotonicity
# ---------------------------------------------------------------------------


def test_v022_registered_in_canonical_migrations() -> None:
    """v022 lives in MIGRATIONS, monotonic and gap-free after v021."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"out of order: {versions}"
    assert 22 in versions, f"expected v22 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )


def test_v022_description_documents_projection_quality_checks() -> None:
    """Migration description names the table + key invariants for log scan."""
    m = V022Migration()
    assert "projection_quality_checks" in m.description
    assert "L7" in m.description or "quality" in m.description


def test_v022_forward_only_no_down_method() -> None:
    """Forward-only doctrine — no ``down`` method on Migration."""
    assert not hasattr(V022Migration(), "down")


# ---------------------------------------------------------------------------
# Postgres path — env-gated (mirrors v019 + v020 + v021)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v022_applies_cleanly_on_postgres() -> None:
    """v022 applies on Postgres when WORMBASE_INTEGRATION_DB=1.

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
            await V022Migration().up(conn)
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
