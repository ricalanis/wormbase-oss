"""Catalog-mirror Wave 2 Sub-wave B — LedgerCatalogReader columns fold tests.

Pins the Sub-wave B reader extension: ``_make_catalog_table`` now folds
per-table ``catalog_table_imported`` entries to populate
``CatalogTable.columns``. Pre-Wave-2 snapshots (no per-table entries)
continue to read ``columns=()``.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.lineage_catalog_reader import LedgerCatalogReader


_COMPANY = UUID("00000000-0000-0000-0000-0000000c0001")
_COMPANY_OTHER = UUID("00000000-0000-0000-0000-0000000c0002")


# ---------------------------------------------------------------------------
# Test fixtures: emit helpers (one PEVR per call, InMemoryLedger.write).
# ---------------------------------------------------------------------------


async def _emit_external_catalog(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    source_id: str,
    source_kind: str,
) -> None:
    args: dict[str, Any] = {
        "source_kind": source_kind,
        "source_id": source_id,
        "domain_id": "general",
        "snapshot_hash": "snap-hash",
        "table_count": 0,
        "edge_count": 0,
        "metric_count": 0,
        "import_mode": "initial",
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "external_catalog_imported",
            "ref_id": source_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_external_catalog_imported",
            "args": args,
            "result_ref": source_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )


async def _emit_external_lineage(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    source_id: str,
    edges: list[tuple[str, str]],
) -> None:
    args: dict[str, Any] = {
        "source_id": source_id,
        "edges": list(edges),
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "external_lineage_imported",
            "ref_id": source_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_external_lineage_imported",
            "args": args,
            "result_ref": source_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )


async def _emit_catalog_table(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    source_id: str,
    snapshot_hash: str,
    table_id: str,
    columns: list[dict[str, Any]],
) -> None:
    args: dict[str, Any] = {
        "source_id": source_id,
        "snapshot_hash": snapshot_hash,
        "table_id": table_id,
        "columns": columns,
    }
    ref_id = f"{source_id}|{snapshot_hash}|{table_id}"
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "catalog_table_imported",
            "ref_id": ref_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_catalog_table_imported",
            "args": args,
            "result_ref": ref_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )


# ---------------------------------------------------------------------------
# list_tables_for_source — fold + back-compat
# ---------------------------------------------------------------------------


async def test_lineage_only_source_returns_empty_columns() -> None:
    """Pre-Wave-2 (lineage only, no catalog_table_imported) → columns=()."""
    ledger = InMemoryLedger()
    await _emit_external_catalog(
        ledger, company_id=_COMPANY, source_id="src-x", source_kind="dbt",
    )
    await _emit_external_lineage(
        ledger,
        company_id=_COMPANY,
        source_id="src-x",
        edges=[("raw.events", "stg.events")],
    )

    reader = LedgerCatalogReader(ledger=ledger)
    tables = await reader.list_tables_for_source(
        company_id=_COMPANY, source_id="src-x",
    )
    assert {t.table_id for t in tables} == {"raw.events", "stg.events"}
    # No per-table entries → columns stay empty (back-compat).
    assert all(t.columns == () for t in tables)


async def test_per_table_entries_populate_columns() -> None:
    """``catalog_table_imported`` → CatalogTable.columns has column names."""
    ledger = InMemoryLedger()
    await _emit_external_catalog(
        ledger, company_id=_COMPANY, source_id="src-x", source_kind="dbt",
    )
    await _emit_external_lineage(
        ledger,
        company_id=_COMPANY,
        source_id="src-x",
        edges=[("raw.events", "stg.events")],
    )
    await _emit_catalog_table(
        ledger,
        company_id=_COMPANY,
        source_id="src-x",
        snapshot_hash="snap-hash",
        table_id="raw.events",
        columns=[
            {"name": "id", "type": "bigint"},
            {"name": "ts", "type": "timestamp"},
        ],
    )
    await _emit_catalog_table(
        ledger,
        company_id=_COMPANY,
        source_id="src-x",
        snapshot_hash="snap-hash",
        table_id="stg.events",
        columns=[
            {"name": "id", "type": "bigint"},
            {"name": "event_name", "type": "text"},
        ],
    )

    reader = LedgerCatalogReader(ledger=ledger)
    tables = await reader.list_tables_for_source(
        company_id=_COMPANY, source_id="src-x",
    )
    by_id = {t.table_id: t for t in tables}
    assert by_id["raw.events"].columns == ("id", "ts")
    assert by_id["stg.events"].columns == ("id", "event_name")


async def test_per_table_entries_without_lineage_still_returned() -> None:
    """A table with a per-table entry but no lineage edge still appears.

    csv_local: a single-table source with no lineage. The per-table
    entry must be sufficient to materialize the CatalogTable.
    """
    ledger = InMemoryLedger()
    await _emit_catalog_table(
        ledger,
        company_id=_COMPANY,
        source_id="csv-src",
        snapshot_hash="snap-hash",
        table_id="/path/to/cursed.csv",
        columns=[
            {"name": "customer_email", "type": None},
            {"name": "amount", "type": None},
        ],
    )

    reader = LedgerCatalogReader(ledger=ledger)
    tables = await reader.list_tables_for_source(
        company_id=_COMPANY, source_id="csv-src",
    )
    assert len(tables) == 1
    assert tables[0].table_id == "/path/to/cursed.csv"
    assert tables[0].columns == ("customer_email", "amount")


async def test_per_table_entry_with_empty_columns_yields_empty_tuple() -> None:
    """Per-table entry with ``columns=[]`` → CatalogTable.columns=()."""
    ledger = InMemoryLedger()
    await _emit_external_catalog(
        ledger, company_id=_COMPANY, source_id="src-x", source_kind="snowflake",
    )
    await _emit_catalog_table(
        ledger,
        company_id=_COMPANY,
        source_id="src-x",
        snapshot_hash="snap-hash",
        table_id="empty.table",
        columns=[],
    )

    reader = LedgerCatalogReader(ledger=ledger)
    tables = await reader.list_tables_for_source(
        company_id=_COMPANY, source_id="src-x",
    )
    assert tables[0].columns == ()


async def test_per_table_entry_skips_malformed_column_specs() -> None:
    """Malformed column specs are skipped, valid ones survive."""
    ledger = InMemoryLedger()
    await _emit_external_catalog(
        ledger, company_id=_COMPANY, source_id="src-x", source_kind="dbt",
    )
    await _emit_catalog_table(
        ledger,
        company_id=_COMPANY,
        source_id="src-x",
        snapshot_hash="snap-hash",
        table_id="t",
        columns=[
            {"name": "ok_a", "type": None},
            {"name": ""},  # empty name → skipped
            "not_a_dict",  # type: ignore[list-item]
            {"name": "ok_b", "type": "int"},
        ],
    )

    reader = LedgerCatalogReader(ledger=ledger)
    tables = await reader.list_tables_for_source(
        company_id=_COMPANY, source_id="src-x",
    )
    assert tables[0].columns == ("ok_a", "ok_b")


async def test_per_table_entries_for_other_source_are_excluded() -> None:
    """source_id filter — per-table entries for other sources don't bleed."""
    ledger = InMemoryLedger()
    await _emit_external_catalog(
        ledger, company_id=_COMPANY, source_id="src-x", source_kind="dbt",
    )
    await _emit_external_lineage(
        ledger,
        company_id=_COMPANY,
        source_id="src-x",
        edges=[("a", "b")],
    )
    # Per-table entry for a DIFFERENT source.
    await _emit_catalog_table(
        ledger,
        company_id=_COMPANY,
        source_id="src-OTHER",
        snapshot_hash="snap-other",
        table_id="a",  # same table_id, different source
        columns=[{"name": "should_not_appear", "type": None}],
    )

    reader = LedgerCatalogReader(ledger=ledger)
    tables = await reader.list_tables_for_source(
        company_id=_COMPANY, source_id="src-x",
    )
    by_id = {t.table_id: t for t in tables}
    # src-x's "a" table reads columns=() — the src-OTHER entry must not
    # leak into src-x's view.
    assert by_id["a"].columns == ()


async def test_per_table_entries_tenant_isolated() -> None:
    """Tenant A's per-table entries don't leak into tenant B's reader."""
    ledger = InMemoryLedger()
    await _emit_catalog_table(
        ledger,
        company_id=_COMPANY,
        source_id="src-x",
        snapshot_hash="snap-a",
        table_id="t",
        columns=[{"name": "tenant_a_col", "type": None}],
    )
    await _emit_catalog_table(
        ledger,
        company_id=_COMPANY_OTHER,
        source_id="src-x",
        snapshot_hash="snap-b",
        table_id="t",
        columns=[{"name": "tenant_b_col", "type": None}],
    )

    reader = LedgerCatalogReader(ledger=ledger)
    a_tables = await reader.list_tables_for_source(
        company_id=_COMPANY, source_id="src-x",
    )
    b_tables = await reader.list_tables_for_source(
        company_id=_COMPANY_OTHER, source_id="src-x",
    )
    assert a_tables[0].columns == ("tenant_a_col",)
    assert b_tables[0].columns == ("tenant_b_col",)


async def test_per_table_latest_emit_wins() -> None:
    """Re-emitting the same table_id → most-recent columns win."""
    ledger = InMemoryLedger()
    await _emit_catalog_table(
        ledger,
        company_id=_COMPANY,
        source_id="src-x",
        snapshot_hash="snap-old",
        table_id="t",
        columns=[{"name": "old_col", "type": None}],
    )
    await _emit_catalog_table(
        ledger,
        company_id=_COMPANY,
        source_id="src-x",
        snapshot_hash="snap-new",
        table_id="t",
        columns=[
            {"name": "new_col_1", "type": None},
            {"name": "new_col_2", "type": None},
        ],
    )

    reader = LedgerCatalogReader(ledger=ledger)
    tables = await reader.list_tables_for_source(
        company_id=_COMPANY, source_id="src-x",
    )
    assert tables[0].columns == ("new_col_1", "new_col_2")


async def test_source_kind_still_propagates_with_per_table_entries() -> None:
    """``source_kind`` from external_catalog_imported flows through."""
    ledger = InMemoryLedger()
    await _emit_external_catalog(
        ledger, company_id=_COMPANY, source_id="src-x", source_kind="snowflake",
    )
    await _emit_catalog_table(
        ledger,
        company_id=_COMPANY,
        source_id="src-x",
        snapshot_hash="snap",
        table_id="t",
        columns=[{"name": "c", "type": "varchar(64)"}],
    )

    reader = LedgerCatalogReader(ledger=ledger)
    tables = await reader.list_tables_for_source(
        company_id=_COMPANY, source_id="src-x",
    )
    assert tables[0].source_kind == "snowflake"
    assert tables[0].columns == ("c",)


# ---------------------------------------------------------------------------
# list_candidate_targets — fold + back-compat
# ---------------------------------------------------------------------------


async def test_list_candidate_targets_populates_columns_from_other_source() -> None:
    """Candidates carry the columns from THEIR owning source's per-table entries."""
    ledger = InMemoryLedger()
    # Triggering source
    await _emit_external_catalog(
        ledger, company_id=_COMPANY, source_id="src-a", source_kind="snowflake",
    )
    await _emit_external_lineage(
        ledger,
        company_id=_COMPANY,
        source_id="src-a",
        edges=[("a.in", "a.out")],
    )
    # Candidate source
    await _emit_external_catalog(
        ledger, company_id=_COMPANY, source_id="src-b", source_kind="dbt",
    )
    await _emit_external_lineage(
        ledger,
        company_id=_COMPANY,
        source_id="src-b",
        edges=[("b.tbl1", "b.tbl2")],
    )
    await _emit_catalog_table(
        ledger,
        company_id=_COMPANY,
        source_id="src-b",
        snapshot_hash="snap-b",
        table_id="b.tbl1",
        columns=[{"name": "k", "type": "bigint"}],
    )

    reader = LedgerCatalogReader(ledger=ledger)
    cands = await reader.list_candidate_targets(
        company_id=_COMPANY, source_id="src-a",
    )
    by_id = {t.table_id: t for t in cands}
    assert by_id["b.tbl1"].columns == ("k",)
    # Table with no per-table entry stays empty.
    assert by_id["b.tbl2"].columns == ()


async def test_list_candidate_targets_excludes_triggering_source_per_table() -> None:
    """Per-table entries belonging to the triggering source are excluded."""
    ledger = InMemoryLedger()
    # Triggering source emits a per-table entry of its own.
    await _emit_external_catalog(
        ledger, company_id=_COMPANY, source_id="src-a", source_kind="snowflake",
    )
    await _emit_catalog_table(
        ledger,
        company_id=_COMPANY,
        source_id="src-a",
        snapshot_hash="snap",
        table_id="a_only",
        columns=[{"name": "x", "type": "int"}],
    )
    # Candidate source.
    await _emit_external_catalog(
        ledger, company_id=_COMPANY, source_id="src-b", source_kind="dbt",
    )
    await _emit_catalog_table(
        ledger,
        company_id=_COMPANY,
        source_id="src-b",
        snapshot_hash="snap",
        table_id="b_only",
        columns=[{"name": "y", "type": "int"}],
    )

    reader = LedgerCatalogReader(ledger=ledger)
    cands = await reader.list_candidate_targets(
        company_id=_COMPANY, source_id="src-a",
    )
    ids = {t.table_id for t in cands}
    assert "a_only" not in ids
    assert "b_only" in ids


async def test_make_catalog_table_static_columns_payload_none() -> None:
    """_make_catalog_table with ``columns_payload=None`` → empty tuple."""
    table = LedgerCatalogReader._make_catalog_table(
        "some_id", source_kind="dbt", columns_payload=None,
    )
    assert table.table_id == "some_id"
    assert table.source_kind == "dbt"
    assert table.columns == ()
    assert table.metadata == {}


async def test_make_catalog_table_static_columns_payload_populated() -> None:
    """_make_catalog_table with populated columns_payload → column names."""
    table = LedgerCatalogReader._make_catalog_table(
        "t",
        source_kind="snowflake",
        columns_payload=(
            {"name": "id", "type": "bigint"},
            {"name": "ts", "type": "timestamp"},
        ),
    )
    assert table.columns == ("id", "ts")


async def test_make_catalog_table_static_skips_empty_and_malformed() -> None:
    """_make_catalog_table defensively skips empty + non-dict entries."""
    table = LedgerCatalogReader._make_catalog_table(
        "t",
        source_kind="dbt",
        columns_payload=(
            {"name": "ok", "type": None},
            {"name": "", "type": "x"},
            "not_a_dict",  # type: ignore[arg-type]
            {"type": "no_name"},  # missing name
        ),
    )
    assert table.columns == ("ok",)
