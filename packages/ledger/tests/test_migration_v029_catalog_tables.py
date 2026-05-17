"""v029 migration — projection_catalog_tables.

Catalog-mirror Wave 2 Sub-wave A (2026-06-09 follow-on). Per-table
column-metadata mirror folded from the ``catalog_table_imported``
ledger kind — substrate that unblocks L2 TableSet + L8 SchemaShape
strategies. Schema mirrors the v029 migration; the dialect-aware DDL
pattern follows v014/v016/v021/v022/v023/v024/v025/v026/v027/v028
(SQLite-portable + Postgres-friendly).

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
from wormbase_ledger.projections.migrations.v029_projection_catalog_tables import (
    Migration as V029Migration,
    _TABLE_NAME,
)


_EXPECTED_COLUMNS = {
    "company_id",
    "source_id",
    "table_id",
    "snapshot_hash",
    "columns",
    "ts",
}


# ---------------------------------------------------------------------------
# SQLite path — always exercised
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v029_creates_projection_catalog_tables_idempotent() -> None:
    """First apply creates the table; second apply is a no-op (checkfirst)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V029Migration().up(conn)
    async with engine.begin() as conn:
        # Second apply — must not raise; checkfirst short-circuits.
        await V029Migration().up(conn)
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
async def test_v029_has_composite_primary_key() -> None:
    """Primary key spans (company_id, source_id, table_id, snapshot_hash)
    — the snapshot_hash leg lets multiple snapshots of the same
    (source, table) coexist as distinct rows so L2 TableSet can diff
    them."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V029Migration().up(conn)
    async with engine.connect() as conn:
        pk = await conn.run_sync(
            lambda sc: inspect(sc).get_pk_constraint(_TABLE_NAME)
        )
    # Order doesn't matter for the constraint contract; compare as sets.
    assert set(pk["constrained_columns"]) == {
        "company_id",
        "source_id",
        "table_id",
        "snapshot_hash",
    }


@pytest.mark.asyncio
async def test_v029_creates_expected_indexes() -> None:
    """Two secondary indexes:

    * ``ix_catalog_tables_source`` for "all tables for this source
      across snapshots" (L2 TableSet baseline/current fetch).
    * ``ix_catalog_tables_snapshot`` for "all tables in this snapshot"
      (L8 SchemaShape per-snapshot column lookup).
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V029Migration().up(conn)
    async with engine.connect() as conn:
        idxs = await conn.run_sync(
            lambda sc: {i["name"] for i in inspect(sc).get_indexes(_TABLE_NAME)}
        )
    assert "ix_catalog_tables_source" in idxs
    assert "ix_catalog_tables_snapshot" in idxs


@pytest.mark.asyncio
async def test_v029_columns_field_is_json() -> None:
    """``columns`` is JSON-typed so the per-column list round-trips
    byte-identically across both dialects."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V029Migration().up(conn)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {
                c["name"]: c["type"].__class__.__name__
                for c in inspect(sc).get_columns(_TABLE_NAME)
            }
        )
    # SQLAlchemy reports JSON columns as 'JSON'.
    assert cols["columns"] == "JSON", (
        f"columns column should be JSON, got {cols['columns']}"
    )


@pytest.mark.asyncio
async def test_v029_composite_pk_rejects_duplicate_same_snapshot() -> None:
    """Within one tenant and snapshot, the same (source, table) can
    only be inserted once — composite PK enforces dedup at the
    projection layer for same-snapshot re-emission."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V029Migration().up(conn)
        await conn.execute(
            text(
                "INSERT INTO projection_catalog_tables "
                "(company_id, source_id, table_id, snapshot_hash, "
                " \"columns\", ts) "
                "VALUES ('co1', 'src-1', 't1', 'h-shared', "
                "'[]', '2026-06-09T00:00:00Z')"
            )
        )
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_catalog_tables "
                    "(company_id, source_id, table_id, snapshot_hash, "
                    " \"columns\", ts) "
                    "VALUES ('co1', 'src-1', 't1', 'h-shared', "
                    "'[{\"name\":\"c2\"}]', '2026-06-09T01:00:00Z')"
                )
            )


@pytest.mark.asyncio
async def test_v029_same_source_table_different_snapshots_isolate() -> None:
    """The same (source, table) across DIFFERENT snapshots produces
    DISTINCT rows. This is the property L2 TableSet needs to diff
    baseline vs current snapshots from the ledger alone."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V029Migration().up(conn)
        # Two snapshots of the same logical table.
        for snap in ("snap-v1", "snap-v2"):
            await conn.execute(
                text(
                    "INSERT INTO projection_catalog_tables "
                    "(company_id, source_id, table_id, snapshot_hash, "
                    " \"columns\", ts) "
                    f"VALUES ('co1', 'src-1', 't1', '{snap}', "
                    f"'[]', '2026-06-09T00:00:00Z')"
                )
            )
    async with engine.connect() as conn:
        count = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM projection_catalog_tables "
                    "WHERE company_id = 'co1' AND source_id = 'src-1' "
                    "AND table_id = 't1'"
                )
            )
        ).scalar()
    assert count == 2


@pytest.mark.asyncio
async def test_v029_same_pk_isolated_across_tenants() -> None:
    """Different tenants can hold the same logical row (tenant
    isolation via the composite PK's company_id leg)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V029Migration().up(conn)
        for company in ("co-a", "co-b"):
            await conn.execute(
                text(
                    "INSERT INTO projection_catalog_tables "
                    "(company_id, source_id, table_id, snapshot_hash, "
                    " \"columns\", ts) "
                    f"VALUES ('{company}', 'src-shared', 't-shared', "
                    f"'h-shared', '[]', '2026-06-09T00:00:00Z')"
                )
            )
    async with engine.connect() as conn:
        count = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM projection_catalog_tables "
                    "WHERE source_id = 'src-shared' AND table_id = 't-shared'"
                )
            )
        ).scalar()
    assert count == 2


@pytest.mark.asyncio
async def test_v029_columns_jsonb_stores_list_of_dicts() -> None:
    """``columns`` round-trips a list of {"name", "type"} dicts
    (serialized ``CatalogColumnSpec`` payloads). The fold writes
    JSON-encoded text; the SELECT path returns the parsed structure."""
    import json
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V029Migration().up(conn)
        await conn.execute(
            text(
                "INSERT INTO projection_catalog_tables "
                "(company_id, source_id, table_id, snapshot_hash, "
                " \"columns\", ts) "
                f"VALUES ('co1', 'src-1', 't1', 'h-1', "
                f"'{json.dumps([{'name': 'id', 'type': 'int'}, {'name': 'name', 'type': 'varchar'}])}', "
                "'2026-06-09T00:00:00Z')"
            )
        )
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT \"columns\" FROM projection_catalog_tables "
                    "WHERE company_id = 'co1' AND table_id = 't1'"
                )
            )
        ).first()
    assert row is not None
    parsed = row[0] if not isinstance(row[0], str) else json.loads(row[0])
    assert parsed == [
        {"name": "id", "type": "int"},
        {"name": "name", "type": "varchar"},
    ]


# ---------------------------------------------------------------------------
# Registration / monotonicity
# ---------------------------------------------------------------------------


def test_v029_registered_in_canonical_migrations() -> None:
    """v029 lives in MIGRATIONS, monotonic and gap-free after v028."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"out of order: {versions}"
    assert 29 in versions, f"expected v29 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )


def test_v029_description_documents_projection_catalog_tables() -> None:
    """Migration description names the table + key invariants for log scan."""
    m = V029Migration()
    assert "projection_catalog_tables" in m.description
    assert "L2" in m.description or "L8" in m.description or "catalog" in m.description


def test_v029_forward_only_no_down_method() -> None:
    """Forward-only doctrine — no ``down`` method on Migration."""
    assert not hasattr(V029Migration(), "down")


# ---------------------------------------------------------------------------
# Postgres path — env-gated (mirrors v019..v028)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v029_applies_cleanly_on_postgres() -> None:
    """v029 applies on Postgres when WORMBASE_INTEGRATION_DB=1.

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
            await V029Migration().up(conn)
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
