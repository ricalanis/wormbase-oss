"""v026 migration — projection_entity_stitches.

L8 Sub-wave A (2026-06-07). Folded view of lake-side cross-source
entity-stitch proposals from the L8 Compounding axis +
confirmed/rejected by admin operators. Schema mirrors the v026
migration; the dialect-aware DDL pattern follows
v014/v016/v021/v022/v023/v024/v025 (SQLite-portable + Postgres-friendly).

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
from wormbase_ledger.projections.migrations.v026_projection_entity_stitches import (
    Migration as V026Migration,
    _TABLE_NAME,
)


_EXPECTED_COLUMNS = {
    "company_id",
    "stitch_id",
    "src_source_id_a",
    "src_table_a",
    "src_column_a",
    "src_source_id_b",
    "src_table_b",
    "src_column_b",
    "upstream_semantic_type_id",
    "entity_kind",
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
async def test_v026_creates_projection_entity_stitches_idempotent() -> None:
    """First apply creates the table; second apply is a no-op (checkfirst)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V026Migration().up(conn)
    async with engine.begin() as conn:
        # Second apply — must not raise; checkfirst short-circuits.
        await V026Migration().up(conn)
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
async def test_v026_has_composite_primary_key() -> None:
    """Primary key spans (company_id, stitch_id) per spec §4.5."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V026Migration().up(conn)
    async with engine.connect() as conn:
        pk = await conn.run_sync(
            lambda sc: inspect(sc).get_pk_constraint(_TABLE_NAME)
        )
    # Order doesn't matter for the constraint contract; compare as sets.
    assert set(pk["constrained_columns"]) == {
        "company_id",
        "stitch_id",
    }


@pytest.mark.asyncio
async def test_v026_creates_expected_indexes() -> None:
    """Four secondary indexes: state / src_source_id_a / src_source_id_b /
    entity_kind."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V026Migration().up(conn)
    async with engine.connect() as conn:
        idxs = await conn.run_sync(
            lambda sc: {i["name"] for i in inspect(sc).get_indexes(_TABLE_NAME)}
        )
    assert "ix_projection_entity_stitches_state" in idxs
    assert "ix_projection_entity_stitches_src_source_id_a" in idxs
    assert "ix_projection_entity_stitches_src_source_id_b" in idxs
    assert "ix_projection_entity_stitches_entity_kind" in idxs


@pytest.mark.asyncio
async def test_v026_state_check_constraint_rejects_bogus_state() -> None:
    """CHECK on state pins the enum {proposed, confirmed, rejected}."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V026Migration().up(conn)
    # Each documented state inserts cleanly.
    async with engine.begin() as conn:
        for i, state in enumerate(("proposed", "confirmed", "rejected")):
            await conn.execute(
                text(
                    "INSERT INTO projection_entity_stitches "
                    "(company_id, stitch_id, src_source_id_a, src_table_a, "
                    " src_column_a, src_source_id_b, src_table_b, src_column_b, "
                    " entity_kind, confidence, strategy, reasoning, "
                    " evidence, state, state_changed_at) "
                    f"VALUES ('co1', 's{i}', 'src-a', 'tbl-a', 'col-a', "
                    f"'src-b', 'tbl-b', 'col-b', 'person', 0.9, "
                    f"'sample_overlap', 'r', '{{}}', "
                    f"'{state}', '2026-06-07T00:00:00Z')"
                )
            )
    # An out-of-enum state is refused at insert time.
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_entity_stitches "
                    "(company_id, stitch_id, src_source_id_a, src_table_a, "
                    " src_column_a, src_source_id_b, src_table_b, src_column_b, "
                    " entity_kind, confidence, strategy, reasoning, "
                    " evidence, state, state_changed_at) "
                    "VALUES ('co1', 'sx', 'src-a', 'tbl-a', 'col-a', "
                    "'src-b', 'tbl-b', 'col-b', 'person', 0.9, "
                    "'sample_overlap', 'r', '{}', "
                    "'rogue', '2026-06-07T00:00:00Z')"
                )
            )


@pytest.mark.asyncio
async def test_v026_nullable_upstream_and_state_changed_by() -> None:
    """``upstream_semantic_type_id`` and ``state_changed_by`` are NULL-able.

    Upstream is NULL when strategy did not consult L5 (e.g.
    ``name_match`` / ``schema_shape`` without an L5 hit);
    state_changed_by is NULL for proposed rows (system-written by the
    L8 Compounding axis)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V026Migration().up(conn)
        await conn.execute(
            text(
                "INSERT INTO projection_entity_stitches "
                "(company_id, stitch_id, src_source_id_a, src_table_a, "
                " src_column_a, src_source_id_b, src_table_b, src_column_b, "
                " upstream_semantic_type_id, entity_kind, confidence, "
                " strategy, reasoning, evidence, state, "
                " state_changed_at, state_changed_by) "
                "VALUES ('co1', 's-null', 'src-a', 'tbl-a', 'col-a', "
                "'src-b', 'tbl-b', 'col-b', NULL, 'person', 0.78, "
                "'name_match', 'r', '{}', "
                "'proposed', '2026-06-07T00:00:00Z', NULL)"
            )
        )
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT upstream_semantic_type_id, state_changed_by "
                    "FROM projection_entity_stitches "
                    "WHERE stitch_id = 's-null'"
                )
            )
        ).first()
    assert row is not None
    assert row[0] is None  # upstream_semantic_type_id
    assert row[1] is None  # state_changed_by


# ---------------------------------------------------------------------------
# Registration / monotonicity
# ---------------------------------------------------------------------------


def test_v026_registered_in_canonical_migrations() -> None:
    """v026 lives in MIGRATIONS, monotonic and gap-free after v025."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"out of order: {versions}"
    assert 26 in versions, f"expected v26 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )


def test_v026_description_documents_projection_entity_stitches() -> None:
    """Migration description names the table + key invariants for log scan."""
    m = V026Migration()
    assert "projection_entity_stitches" in m.description
    assert "L8" in m.description or "stitch" in m.description


def test_v026_forward_only_no_down_method() -> None:
    """Forward-only doctrine — no ``down`` method on Migration."""
    assert not hasattr(V026Migration(), "down")


# ---------------------------------------------------------------------------
# Postgres path — env-gated (mirrors v019..v025)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v026_applies_cleanly_on_postgres() -> None:
    """v026 applies on Postgres when WORMBASE_INTEGRATION_DB=1.

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
            await V026Migration().up(conn)
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
