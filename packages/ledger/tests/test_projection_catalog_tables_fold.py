"""Projection-fold tests for catalog-mirror Wave 2 Sub-wave A
``catalog_table_imported`` entries.

The ``projection_catalog_tables`` view is the substrate that L2
TableSet + L8 SchemaShape strategies fold to compute real diffs over
catalog snapshots. One row per ``(company_id, source_id, table_id,
snapshot_hash)`` tuple folded from the single
``catalog_table_imported`` ledger kind.

These tests pin:

* Empty ledger → empty projection (no rows materialized when no
  ``catalog_table_imported`` entries exist).
* A single emit lands one row with all per-column metadata preserved
  (the per-column ``CatalogColumnSpec`` list survives round-trip via
  the JSON column).
* Multiple snapshots of the same (source, table) produce distinct
  rows because ``snapshot_hash`` is part of the composite PK — the
  property L2 TableSet needs to diff baseline vs current snapshots
  from the ledger alone.
* Multiple tables in the same snapshot land as distinct rows.
* Re-emission of the same row (same composite PK) collapses onto
  the same projection entry (replay-stable).
* Empty ``columns`` tuple is preserved verbatim (valid state for
  connectors that lack column-type introspection).
* Tenant isolation: rows scoped to ``company_id``; tenant A's
  per-table catalog does not leak into tenant B's fold.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.projections import build_projections
from wormbase_ledger.write_primitive import write_primitive


def _verify_pass(_r):  # type: ignore[no-untyped-def]
    return {"checks": [], "passed": True}


def _resolve_keep(_v):  # type: ignore[no-untyped-def]
    return {"outcome": "keep", "rationale": "ok"}


async def _emit_catalog_table_imported(
    session,
    *,
    company_id,
    source_id: str = "src-stripe-1",
    snapshot_hash: str = "snap-h-1",
    table_id: str = "customers",
    columns: list[dict] | None = None,
) -> None:
    """Emit a canonical ``catalog_table_imported`` PEVR cycle.

    ``columns`` is a list of ``{"name", "type"}`` dicts — the
    on-wire shape of the ``CatalogColumnSpec`` payload after
    ``model_dump`` flattens the tuple.
    """
    if columns is None:
        columns = [
            {"name": "id", "type": "int"},
            {"name": "email", "type": "varchar"},
        ]
    args = {
        "source_id": source_id,
        "snapshot_hash": snapshot_hash,
        "table_id": table_id,
        "columns": columns,
    }
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "catalog_table_imported",
            "ref_id": str(uuid4()),
            "reason": "connector discovered table during snapshot import",
            "proposed_by": "agent-catalog-mirror",
        },
        execute_fn=lambda: {
            "tool": "emit_catalog_table_imported",
            "args": args,
            "result_ref": f"{source_id}|{snapshot_hash}|{table_id}",
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


# ---------------------------------------------------------------------------
# Empty + single-entry folds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_ledger_yields_empty_catalog_tables(
    test_database_url: str,
) -> None:
    """No ``catalog_table_imported`` entries → no rows materialized."""
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert proj.catalog_tables == []


@pytest.mark.asyncio
async def test_single_catalog_table_imported_creates_one_row(
    test_database_url: str,
) -> None:
    """One emission → one projection row with all column metadata
    preserved verbatim."""
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        await _emit_catalog_table_imported(
            session,
            company_id=company_id,
            source_id="src-stripe-1",
            snapshot_hash="snap-h-1",
            table_id="customers",
            columns=[
                {"name": "id", "type": "int"},
                {"name": "email", "type": "varchar"},
                {"name": "created_at", "type": "timestamp"},
            ],
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.catalog_tables) == 1
    row = proj.catalog_tables[0]
    assert row["company_id"] == str(company_id)
    assert row["source_id"] == "src-stripe-1"
    assert row["snapshot_hash"] == "snap-h-1"
    assert row["table_id"] == "customers"
    assert row["columns"] == [
        {"name": "id", "type": "int"},
        {"name": "email", "type": "varchar"},
        {"name": "created_at", "type": "timestamp"},
    ]
    assert row["ts"].tzinfo is not None


@pytest.mark.asyncio
async def test_empty_columns_tuple_is_preserved(
    test_database_url: str,
) -> None:
    """A connector with no column-type introspection capability emits
    ``columns=[]``. The fold preserves the empty list — the L-axis
    strategies treat it as 'table exists, no column data available'."""
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        await _emit_catalog_table_imported(
            session,
            company_id=company_id,
            source_id="src-1",
            snapshot_hash="h-1",
            table_id="opaque_table",
            columns=[],
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.catalog_tables) == 1
    assert proj.catalog_tables[0]["columns"] == []


@pytest.mark.asyncio
async def test_nullable_column_type_round_trips(
    test_database_url: str,
) -> None:
    """``CatalogColumnSpec.type`` is nullable — connectors that lack
    column-type introspection (raw CSV headers) emit ``type=None``."""
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        await _emit_catalog_table_imported(
            session,
            company_id=company_id,
            source_id="src-csv",
            snapshot_hash="h-csv",
            table_id="opaque.csv",
            columns=[
                {"name": "header1", "type": None},
                {"name": "header2", "type": None},
            ],
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.catalog_tables) == 1
    row = proj.catalog_tables[0]
    assert row["columns"] == [
        {"name": "header1", "type": None},
        {"name": "header2", "type": None},
    ]


# ---------------------------------------------------------------------------
# Multi-snapshot + multi-table semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_snapshot_same_table_yields_multiple_rows(
    test_database_url: str,
) -> None:
    """Two snapshots of the SAME logical (source, table) → TWO rows
    because ``snapshot_hash`` is part of the composite PK. This is
    the property L2 TableSet needs to diff baseline vs current
    snapshots from the ledger alone."""
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        # First snapshot — original column set.
        await _emit_catalog_table_imported(
            session,
            company_id=company_id,
            source_id="src-1",
            snapshot_hash="snap-v1",
            table_id="orders",
            columns=[
                {"name": "id", "type": "int"},
                {"name": "amount", "type": "numeric"},
            ],
        )
        # Second snapshot — same table, NEW column added upstream.
        await _emit_catalog_table_imported(
            session,
            company_id=company_id,
            source_id="src-1",
            snapshot_hash="snap-v2",
            table_id="orders",
            columns=[
                {"name": "id", "type": "int"},
                {"name": "amount", "type": "numeric"},
                {"name": "currency", "type": "varchar"},
            ],
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.catalog_tables) == 2
    # Rows sort deterministically by (company, source, table, snapshot).
    v1_rows = [r for r in proj.catalog_tables if r["snapshot_hash"] == "snap-v1"]
    v2_rows = [r for r in proj.catalog_tables if r["snapshot_hash"] == "snap-v2"]
    assert len(v1_rows) == 1
    assert len(v2_rows) == 1
    assert len(v1_rows[0]["columns"]) == 2
    assert len(v2_rows[0]["columns"]) == 3


@pytest.mark.asyncio
async def test_multiple_tables_in_same_snapshot_yield_distinct_rows(
    test_database_url: str,
) -> None:
    """Several tables discovered in the SAME snapshot land as
    distinct rows — one per table per snapshot."""
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        for table_id in ("customers", "orders", "products"):
            await _emit_catalog_table_imported(
                session,
                company_id=company_id,
                source_id="src-1",
                snapshot_hash="snap-h-1",
                table_id=table_id,
                columns=[{"name": "id", "type": "int"}],
            )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.catalog_tables) == 3
    seen_tables = {r["table_id"] for r in proj.catalog_tables}
    assert seen_tables == {"customers", "orders", "products"}


@pytest.mark.asyncio
async def test_reemission_same_pk_collapses_to_single_row(
    test_database_url: str,
) -> None:
    """Re-emission of the same composite PK collapses onto the same
    projection row (replay-stable). The later emit's columns win
    (forward-only update)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        await _emit_catalog_table_imported(
            session,
            company_id=company_id,
            source_id="src-1",
            snapshot_hash="snap-h",
            table_id="t1",
            columns=[{"name": "v1_col", "type": "int"}],
        )
        # Re-emit — same composite PK, refined column list.
        await _emit_catalog_table_imported(
            session,
            company_id=company_id,
            source_id="src-1",
            snapshot_hash="snap-h",
            table_id="t1",
            columns=[
                {"name": "v1_col", "type": "int"},
                {"name": "v2_col", "type": "varchar"},
            ],
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # One row regardless of two emissions (composite PK collapses them).
    assert len(proj.catalog_tables) == 1
    # The LATER emission's columns win.
    assert len(proj.catalog_tables[0]["columns"]) == 2


# ---------------------------------------------------------------------------
# Determinism — replay yields byte-identical projection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_is_deterministic(
    test_database_url: str,
) -> None:
    """Two folds over the same ledger stream produce byte-identical
    projection rows — composite PK + sorted output guarantee replay
    stability."""
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        for snap in ("snap-a", "snap-b"):
            for table in ("t1", "t2"):
                await _emit_catalog_table_imported(
                    session,
                    company_id=company_id,
                    source_id="src-1",
                    snapshot_hash=snap,
                    table_id=table,
                    columns=[{"name": "c1", "type": "int"}],
                )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, company_id)
    async with session_scope(engine) as session:
        proj_b = await build_projections(session, company_id)

    assert proj_a.catalog_tables == proj_b.catalog_tables
    assert len(proj_a.catalog_tables) == 4  # 2 snapshots × 2 tables


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_catalog_tables_are_tenant_scoped(
    test_database_url: str,
) -> None:
    """Tenant A's per-table catalog does not leak into tenant B's fold.

    Both tenants emit the same logical (source, table, snapshot)
    — tenant isolation comes from the company_id leg of the composite
    PK."""
    engine = get_engine(test_database_url)
    company_a = uuid4()
    company_b = uuid4()

    async with session_scope(engine) as session:
        await _emit_catalog_table_imported(
            session,
            company_id=company_a,
            source_id="src-shared",
            snapshot_hash="snap-shared",
            table_id="t-shared",
            columns=[{"name": "tenant_a_col", "type": "int"}],
        )
        await _emit_catalog_table_imported(
            session,
            company_id=company_b,
            source_id="src-shared",
            snapshot_hash="snap-shared",
            table_id="t-shared",
            columns=[{"name": "tenant_b_col", "type": "varchar"}],
        )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, company_a)
        proj_b = await build_projections(session, company_b)

    assert len(proj_a.catalog_tables) == 1
    assert proj_a.catalog_tables[0]["company_id"] == str(company_a)
    assert proj_a.catalog_tables[0]["columns"] == [
        {"name": "tenant_a_col", "type": "int"},
    ]

    assert len(proj_b.catalog_tables) == 1
    assert proj_b.catalog_tables[0]["company_id"] == str(company_b)
    assert proj_b.catalog_tables[0]["columns"] == [
        {"name": "tenant_b_col", "type": "varchar"},
    ]


# ---------------------------------------------------------------------------
# Defensive folds: empty key fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_source_id_is_skipped(
    test_database_url: str,
    caplog,
) -> None:
    """An emission with empty ``source_id`` is logged + skipped —
    the fold doesn't materialize a row from incomplete signal."""
    import logging
    engine = get_engine(test_database_url)
    company_id = uuid4()

    # The payload validator rejects empty source_id at write time, but
    # the fold guards defensively in case a stale/malformed entry
    # reaches the fold path. We construct the bad entry by bypassing
    # the high-level helper.
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "catalog_table_imported",
                "ref_id": str(uuid4()),
                "reason": "malformed-emit-guard-test",
                "proposed_by": "test",
            },
            execute_fn=lambda: {
                "tool": "emit_catalog_table_imported",
                # Empty source_id triggers the defensive guard.
                "args": {
                    "source_id": "",
                    "snapshot_hash": "h",
                    "table_id": "t",
                    "columns": [],
                },
                "result_ref": "guard",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    assert proj.catalog_tables == []
    # The fold logs a warning about the malformed entry.
    assert any(
        "catalog_table_imported" in r.message and "empty key" in r.message
        for r in caplog.records
    )
