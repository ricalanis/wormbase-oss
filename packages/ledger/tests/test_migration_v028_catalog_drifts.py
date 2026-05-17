"""v028 migration — projection_catalog_drifts.

L2 Sub-wave A (2026-06-09). Folded view of lake-side catalog-drift
detection proposals from the L2 Compounding axis + acknowledged/
rejected by admin operators. Schema mirrors the v028 migration; the
dialect-aware DDL pattern follows v014/v016/v021/v022/v023/v024/
v025/v026/v027 (SQLite-portable + Postgres-friendly).

The SQLite tests below cover the always-on path. The Postgres path
exercises the same Migration class — it's plain SQLAlchemy Core DDL
with no pgvector dependency, so the SQLite tests cover the
production schema by structural equivalence. A Postgres apply test
is gated on WORMBASE_INTEGRATION_DB=1 + a reachable
WORMBASE_TEST_DB_URL.
"""
from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations import MIGRATIONS
from wormbase_ledger.projections.migrations.v028_projection_catalog_drifts import (
    Migration as V028Migration,
    _TABLE_NAME,
)


_EXPECTED_COLUMNS = {
    "company_id",
    "drift_id",
    "source_id",
    "table_id",
    "column",
    "drift_kind",
    "before",
    "after",
    "strategy",
    "reasoning",
    "confidence",
    "evidence",
    "state",
    "state_changed_at",
    "state_changed_by",
}


# ---------------------------------------------------------------------------
# SQLite path — always exercised
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v028_creates_projection_catalog_drifts_idempotent() -> None:
    """First apply creates the table; second apply is a no-op (checkfirst)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V028Migration().up(conn)
    async with engine.begin() as conn:
        # Second apply — must not raise; checkfirst short-circuits.
        await V028Migration().up(conn)
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
async def test_v028_has_composite_primary_key() -> None:
    """Primary key spans (company_id, drift_id) per spec §3.6."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V028Migration().up(conn)
    async with engine.connect() as conn:
        pk = await conn.run_sync(
            lambda sc: inspect(sc).get_pk_constraint(_TABLE_NAME)
        )
    # Order doesn't matter for the constraint contract; compare as sets.
    assert set(pk["constrained_columns"]) == {
        "company_id",
        "drift_id",
    }


@pytest.mark.asyncio
async def test_v028_creates_expected_indexes() -> None:
    """Four secondary indexes: state / source_id / drift_kind / table_id."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V028Migration().up(conn)
    async with engine.connect() as conn:
        idxs = await conn.run_sync(
            lambda sc: {i["name"] for i in inspect(sc).get_indexes(_TABLE_NAME)}
        )
    assert "ix_projection_catalog_drifts_state" in idxs
    assert "ix_projection_catalog_drifts_source_id" in idxs
    assert "ix_projection_catalog_drifts_drift_kind" in idxs
    assert "ix_projection_catalog_drifts_table_id" in idxs


@pytest.mark.asyncio
async def test_v028_state_check_constraint_rejects_bogus_state() -> None:
    """CHECK on state pins the enum {proposed, acknowledged, rejected}.

    Note L2 uses ``acknowledged`` where L3/L7/L4/L5/L6/L8 use
    ``confirmed`` and L1 uses ``promoted`` — per spec §1, L2 is a
    no-op disposition record so the affirmative state name is
    "acknowledged" rather than "confirmed" or "promoted"."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V028Migration().up(conn)
    # Each documented state inserts cleanly.
    async with engine.begin() as conn:
        for i, state in enumerate(("proposed", "acknowledged", "rejected")):
            await conn.execute(
                text(
                    "INSERT INTO projection_catalog_drifts "
                    "(company_id, drift_id, source_id, table_id, "
                    " drift_kind, strategy, reasoning, confidence, "
                    " evidence, state, state_changed_at) "
                    f"VALUES ('co1', 'd{i}', 'src-1', 't1', "
                    f"'table_added', 'table_set', 'r', 0.9, '{{}}', "
                    f"'{state}', '2026-06-09T00:00:00Z')"
                )
            )
    # An out-of-enum state (e.g. L3-style "confirmed") is refused.
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_catalog_drifts "
                    "(company_id, drift_id, source_id, table_id, "
                    " drift_kind, strategy, reasoning, confidence, "
                    " evidence, state, state_changed_at) "
                    "VALUES ('co1', 'd-bad', 'src-1', 't1', "
                    "'table_added', 'table_set', 'r', 0.9, '{}', "
                    "'confirmed', '2026-06-09T00:00:00Z')"
                )
            )


@pytest.mark.asyncio
async def test_v028_drift_kind_check_constraint_rejects_bogus_kind() -> None:
    """CHECK on drift_kind pins the enum to the 5 documented values."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V028Migration().up(conn)
    # Each documented drift_kind inserts cleanly.
    valid_kinds = (
        "table_added", "table_removed",
        "column_added", "column_removed", "column_type_changed",
    )
    async with engine.begin() as conn:
        for i, kind in enumerate(valid_kinds):
            await conn.execute(
                text(
                    "INSERT INTO projection_catalog_drifts "
                    "(company_id, drift_id, source_id, table_id, "
                    " drift_kind, strategy, reasoning, confidence, "
                    " evidence, state, state_changed_at) "
                    f"VALUES ('co1', 'd{i}', 'src-1', 't1', "
                    f"'{kind}', 'table_set', 'r', 0.9, '{{}}', "
                    f"'proposed', '2026-06-09T00:00:00Z')"
                )
            )
    # An out-of-enum drift_kind is refused.
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_catalog_drifts "
                    "(company_id, drift_id, source_id, table_id, "
                    " drift_kind, strategy, reasoning, confidence, "
                    " evidence, state, state_changed_at) "
                    "VALUES ('co1', 'd-x', 'src-1', 't1', "
                    "'rename_table', 'table_set', 'r', 0.9, '{}', "
                    "'proposed', '2026-06-09T00:00:00Z')"
                )
            )


@pytest.mark.asyncio
async def test_v028_nullable_column_before_after_changed_by() -> None:
    """``column``, ``before``, ``after``, and ``state_changed_by`` are
    NULL-able.

    column is NULL for table_added/table_removed; before is NULL on
    *_added rows (no prior value); after is NULL on *_removed rows
    (no current value); state_changed_by is NULL for proposed rows
    (system-written by the L2 Compounding axis)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V028Migration().up(conn)
        # table_added: column=NULL, before=NULL, after set
        await conn.execute(
            text(
                "INSERT INTO projection_catalog_drifts "
                "(company_id, drift_id, source_id, table_id, "
                " \"column\", drift_kind, before, after, "
                " strategy, reasoning, confidence, evidence, "
                " state, state_changed_at, state_changed_by) "
                "VALUES ('co1', 'd-null', 'src-1', 't1', NULL, "
                "'table_added', NULL, '{\"t\": 1}', "
                "'table_set', 'r', 0.9, '{}', "
                "'proposed', '2026-06-09T00:00:00Z', NULL)"
            )
        )
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT \"column\", before, after, state_changed_by "
                    "FROM projection_catalog_drifts "
                    "WHERE drift_id = 'd-null'"
                )
            )
        ).first()
    assert row is not None
    assert row[0] is None  # column
    assert row[1] is None  # before
    assert row[3] is None  # state_changed_by


@pytest.mark.asyncio
async def test_v028_composite_pk_collapses_same_drift_id_per_tenant() -> None:
    """Within one tenant, the same drift_id can only be inserted
    once — the composite PK enforces that the dedup hash from
    ``make_drift_id`` actually dedups at the projection layer."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V028Migration().up(conn)
        await conn.execute(
            text(
                "INSERT INTO projection_catalog_drifts "
                "(company_id, drift_id, source_id, table_id, "
                " drift_kind, strategy, reasoning, confidence, "
                " evidence, state, state_changed_at) "
                "VALUES ('co1', 'd-shared', 'src-1', 't1', "
                "'table_added', 'table_set', 'r1', 0.9, '{}', "
                "'proposed', '2026-06-09T00:00:00Z')"
            )
        )
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_catalog_drifts "
                    "(company_id, drift_id, source_id, table_id, "
                    " drift_kind, strategy, reasoning, confidence, "
                    " evidence, state, state_changed_at) "
                    "VALUES ('co1', 'd-shared', 'src-1', 't1', "
                    "'table_added', 'table_set', 'r2', 0.95, '{}', "
                    "'proposed', '2026-06-09T01:00:00Z')"
                )
            )


@pytest.mark.asyncio
async def test_v028_same_drift_id_isolated_across_tenants() -> None:
    """Different tenants can hold the same drift_id (tenant
    isolation via the composite PK leg)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V028Migration().up(conn)
        for company_id in ("co-a", "co-b"):
            await conn.execute(
                text(
                    "INSERT INTO projection_catalog_drifts "
                    "(company_id, drift_id, source_id, table_id, "
                    " drift_kind, strategy, reasoning, confidence, "
                    " evidence, state, state_changed_at) "
                    f"VALUES ('{company_id}', 'd-shared', 'src-1', "
                    f"'t1', 'table_added', 'table_set', 'r', 0.9, "
                    f"'{{}}', 'proposed', '2026-06-09T00:00:00Z')"
                )
            )
    async with engine.connect() as conn:
        count = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM projection_catalog_drifts "
                    "WHERE drift_id = 'd-shared'"
                )
            )
        ).scalar()
    assert count == 2


# ---------------------------------------------------------------------------
# Registration / monotonicity
# ---------------------------------------------------------------------------


def test_v028_registered_in_canonical_migrations() -> None:
    """v028 lives in MIGRATIONS, monotonic and gap-free after v027."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"out of order: {versions}"
    assert 28 in versions, f"expected v28 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )


def test_v028_description_documents_projection_catalog_drifts() -> None:
    """Migration description names the table + key invariants for log scan."""
    m = V028Migration()
    assert "projection_catalog_drifts" in m.description
    assert "L2" in m.description or "drift" in m.description


def test_v028_forward_only_no_down_method() -> None:
    """Forward-only doctrine — no ``down`` method on Migration."""
    assert not hasattr(V028Migration(), "down")


# ---------------------------------------------------------------------------
# Postgres path — env-gated (mirrors v019..v027)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v028_applies_cleanly_on_postgres() -> None:
    """v028 applies on Postgres when WORMBASE_INTEGRATION_DB=1.

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
            await V028Migration().up(conn)
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
