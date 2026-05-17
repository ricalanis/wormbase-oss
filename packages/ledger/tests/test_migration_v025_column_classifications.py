"""v025 migration — projection_column_classifications.

L6 Sub-wave A (2026-06-06). Folded view of lake-side column-level
governance classification proposals from the L6 Compounding axis +
confirmed/rejected by admin operators. Schema mirrors the v025
migration; the dialect-aware DDL pattern follows
v014/v016/v021/v022/v023/v024 (SQLite-portable + Postgres-friendly).

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
from wormbase_ledger.projections.migrations.v025_projection_column_classifications import (
    Migration as V025Migration,
    _TABLE_NAME,
)


_EXPECTED_COLUMNS = {
    "company_id",
    "classification_id",
    "table_id",
    "column",
    "classification_level",
    "upstream_semantic_type_id",
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
async def test_v025_creates_projection_column_classifications_idempotent() -> None:
    """First apply creates the table; second apply is a no-op (checkfirst)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V025Migration().up(conn)
    async with engine.begin() as conn:
        # Second apply — must not raise; checkfirst short-circuits.
        await V025Migration().up(conn)
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
async def test_v025_has_composite_primary_key() -> None:
    """Primary key spans (company_id, classification_id) per spec §4.5."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V025Migration().up(conn)
    async with engine.connect() as conn:
        pk = await conn.run_sync(
            lambda sc: inspect(sc).get_pk_constraint(_TABLE_NAME)
        )
    # Order doesn't matter for the constraint contract; compare as sets.
    assert set(pk["constrained_columns"]) == {
        "company_id",
        "classification_id",
    }


@pytest.mark.asyncio
async def test_v025_creates_expected_indexes() -> None:
    """Three secondary indexes: state / table_id / classification_level."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V025Migration().up(conn)
    async with engine.connect() as conn:
        idxs = await conn.run_sync(
            lambda sc: {i["name"] for i in inspect(sc).get_indexes(_TABLE_NAME)}
        )
    assert "ix_projection_column_classifications_state" in idxs
    assert "ix_projection_column_classifications_table_id" in idxs
    assert "ix_projection_column_classifications_level" in idxs


@pytest.mark.asyncio
async def test_v025_state_check_constraint_rejects_bogus_state() -> None:
    """CHECK on state pins the enum {proposed, confirmed, rejected}."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V025Migration().up(conn)
    # Each documented state inserts cleanly. ``"column"`` is double-quoted
    # because column is a reserved-word in some dialects; SQLite tolerates
    # the bare identifier but quoting keeps the test portable.
    async with engine.begin() as conn:
        for i, state in enumerate(("proposed", "confirmed", "rejected")):
            await conn.execute(
                text(
                    "INSERT INTO projection_column_classifications "
                    "(company_id, classification_id, table_id, \"column\", "
                    " classification_level, confidence, strategy, reasoning, "
                    " evidence, state, state_changed_at) "
                    f"VALUES ('co1', 'c{i}', 'tbl1', 'col1', "
                    f"'pii', 0.9, 'naming_pattern', 'r', '{{}}', "
                    f"'{state}', '2026-06-06T00:00:00Z')"
                )
            )
    # An out-of-enum state is refused at insert time.
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_column_classifications "
                    "(company_id, classification_id, table_id, \"column\", "
                    " classification_level, confidence, strategy, reasoning, "
                    " evidence, state, state_changed_at) "
                    "VALUES ('co1', 'cx', 'tbl1', 'col1', "
                    "'pii', 0.9, 'naming_pattern', 'r', '{}', "
                    "'rogue', '2026-06-06T00:00:00Z')"
                )
            )


@pytest.mark.asyncio
async def test_v025_nullable_upstream_and_state_changed_by() -> None:
    """``upstream_semantic_type_id`` and ``state_changed_by`` are NULL-able.

    Upstream is NULL when strategy was naming_pattern or
    domain_default (no L5 dependency); state_changed_by is NULL for
    proposed rows (system-written by the L6 Compounding axis)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V025Migration().up(conn)
        await conn.execute(
            text(
                "INSERT INTO projection_column_classifications "
                "(company_id, classification_id, table_id, \"column\", "
                " classification_level, upstream_semantic_type_id, "
                " confidence, strategy, reasoning, evidence, state, "
                " state_changed_at, state_changed_by) "
                "VALUES ('co1', 'c-null', 'tbl1', 'col1', 'confidential', "
                "NULL, 0.85, 'naming_pattern', 'r', '{}', "
                "'proposed', '2026-06-06T00:00:00Z', NULL)"
            )
        )
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT upstream_semantic_type_id, state_changed_by "
                    "FROM projection_column_classifications "
                    "WHERE classification_id = 'c-null'"
                )
            )
        ).first()
    assert row is not None
    assert row[0] is None  # upstream_semantic_type_id
    assert row[1] is None  # state_changed_by


# ---------------------------------------------------------------------------
# Registration / monotonicity
# ---------------------------------------------------------------------------


def test_v025_registered_in_canonical_migrations() -> None:
    """v025 lives in MIGRATIONS, monotonic and gap-free after v024."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"out of order: {versions}"
    assert 25 in versions, f"expected v25 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )


def test_v025_description_documents_projection_column_classifications() -> None:
    """Migration description names the table + key invariants for log scan."""
    m = V025Migration()
    assert "projection_column_classifications" in m.description
    assert "L6" in m.description or "classification" in m.description


def test_v025_forward_only_no_down_method() -> None:
    """Forward-only doctrine — no ``down`` method on Migration."""
    assert not hasattr(V025Migration(), "down")


# ---------------------------------------------------------------------------
# Postgres path — env-gated (mirrors v019 + v020 + v021 + v022 + v023 + v024)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v025_applies_cleanly_on_postgres() -> None:
    """v025 applies on Postgres when WORMBASE_INTEGRATION_DB=1.

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
            await V025Migration().up(conn)
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
