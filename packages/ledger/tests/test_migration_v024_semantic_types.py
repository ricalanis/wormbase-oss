"""v024 migration — projection_semantic_types.

L5 Sub-wave A (2026-06-05). Folded view of lake-side sample-data
fingerprinting semantic-type proposals from the L5 Compounding axis +
confirmed/rejected by admin operators. Schema mirrors the v024
migration; the dialect-aware DDL pattern follows
v014/v016/v021/v022/v023 (SQLite-portable + Postgres-friendly).

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
from wormbase_ledger.projections.migrations.v024_projection_semantic_types import (
    Migration as V024Migration,
    _TABLE_NAME,
)


_EXPECTED_COLUMNS = {
    "company_id",
    "type_id",
    "table_id",
    "column",
    "semantic_type",
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
async def test_v024_creates_projection_semantic_types_idempotent() -> None:
    """First apply creates the table; second apply is a no-op (checkfirst)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V024Migration().up(conn)
    async with engine.begin() as conn:
        # Second apply — must not raise; checkfirst short-circuits.
        await V024Migration().up(conn)
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
async def test_v024_has_composite_primary_key() -> None:
    """Primary key spans (company_id, type_id) per spec §3.5."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V024Migration().up(conn)
    async with engine.connect() as conn:
        pk = await conn.run_sync(
            lambda sc: inspect(sc).get_pk_constraint(_TABLE_NAME)
        )
    # Order doesn't matter for the constraint contract; compare as sets.
    assert set(pk["constrained_columns"]) == {"company_id", "type_id"}


@pytest.mark.asyncio
async def test_v024_creates_expected_indexes() -> None:
    """Three secondary indexes: state / table_id / semantic_type."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V024Migration().up(conn)
    async with engine.connect() as conn:
        idxs = await conn.run_sync(
            lambda sc: {i["name"] for i in inspect(sc).get_indexes(_TABLE_NAME)}
        )
    assert "ix_projection_semantic_types_state" in idxs
    assert "ix_projection_semantic_types_table_id" in idxs
    assert "ix_projection_semantic_types_semantic_type" in idxs


@pytest.mark.asyncio
async def test_v024_state_check_constraint_rejects_bogus_state() -> None:
    """CHECK on state pins the enum {proposed, confirmed, rejected}."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V024Migration().up(conn)
    # Each documented state inserts cleanly. ``"column"`` is double-quoted
    # because column is a reserved-word in some dialects; SQLite tolerates
    # the bare identifier but quoting keeps the test portable.
    async with engine.begin() as conn:
        for i, state in enumerate(("proposed", "confirmed", "rejected")):
            await conn.execute(
                text(
                    "INSERT INTO projection_semantic_types "
                    "(company_id, type_id, table_id, \"column\", "
                    " semantic_type, confidence, strategy, reasoning, "
                    " evidence, state, state_changed_at) "
                    f"VALUES ('co1', 't{i}', 'tbl1', 'col1', "
                    f"'email', 0.9, 'column_name', 'r', '{{}}', "
                    f"'{state}', '2026-06-05T00:00:00Z')"
                )
            )
    # An out-of-enum state is refused at insert time.
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_semantic_types "
                    "(company_id, type_id, table_id, \"column\", "
                    " semantic_type, confidence, strategy, reasoning, "
                    " evidence, state, state_changed_at) "
                    "VALUES ('co1', 'tx', 'tbl1', 'col1', "
                    "'email', 0.9, 'column_name', 'r', '{}', "
                    "'rogue', '2026-06-05T00:00:00Z')"
                )
            )


@pytest.mark.asyncio
async def test_v024_nullable_state_changed_by() -> None:
    """state_changed_by is NULL-able.

    A proposed row before resolution carries NULL state_changed_by
    (the system, not an operator, wrote it)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V024Migration().up(conn)
        await conn.execute(
            text(
                "INSERT INTO projection_semantic_types "
                "(company_id, type_id, table_id, \"column\", semantic_type, "
                " confidence, strategy, reasoning, evidence, state, "
                " state_changed_at, state_changed_by) "
                "VALUES ('co1', 't-null', 'tbl1', 'col1', 'email', "
                "0.85, 'value_pattern', 'r', '{}', "
                "'proposed', '2026-06-05T00:00:00Z', NULL)"
            )
        )
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT state_changed_by "
                    "FROM projection_semantic_types WHERE type_id = 't-null'"
                )
            )
        ).first()
    assert row is not None
    assert row[0] is None


# ---------------------------------------------------------------------------
# Registration / monotonicity
# ---------------------------------------------------------------------------


def test_v024_registered_in_canonical_migrations() -> None:
    """v024 lives in MIGRATIONS, monotonic and gap-free after v023."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"out of order: {versions}"
    assert 24 in versions, f"expected v24 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )


def test_v024_description_documents_projection_semantic_types() -> None:
    """Migration description names the table + key invariants for log scan."""
    m = V024Migration()
    assert "projection_semantic_types" in m.description
    assert "L5" in m.description or "fingerprinting" in m.description


def test_v024_forward_only_no_down_method() -> None:
    """Forward-only doctrine — no ``down`` method on Migration."""
    assert not hasattr(V024Migration(), "down")


# ---------------------------------------------------------------------------
# Postgres path — env-gated (mirrors v019 + v020 + v021 + v022 + v023)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v024_applies_cleanly_on_postgres() -> None:
    """v024 applies on Postgres when WORMBASE_INTEGRATION_DB=1.

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
            await V024Migration().up(conn)
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
