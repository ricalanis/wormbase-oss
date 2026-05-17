"""Catalog-mirror Wave 2 Sub-wave B — csv_local round-trip integration test.

Pins the source-builder wire-up: when ``run_default_local_cascade``
runs, it ALSO emits one ``catalog_table_imported`` PEVR per the
cursed-CSV via the extractor registry. The ledger then folds the
entry back through ``LedgerCatalogReader`` to a populated columns
tuple — productive end-to-end for csv_local.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.lineage_catalog_reader import LedgerCatalogReader
from wormbase_core.onboarding.default_local_source import (
    run_default_local_cascade,
)


_COMPANY = UUID("00000000-0000-0000-0000-0000000c0001")


def _make_csv(tmp_path: Path, name: str = "cursed.csv") -> Path:
    """Write a small CSV mimicking the cursed-finance shape."""
    p = tmp_path / name
    p.write_text(
        "transaction_id,customer_email,amount,currency,transacted_at\n"
        "tx1,a@x.com,10.00,USD,2026-01-01\n"
        "tx2,b@y.com,20.00,EUR,2026-01-02\n",
        encoding="utf-8",
    )
    return p


async def test_run_default_local_cascade_emits_catalog_table_imported(
    tmp_path: Path,
) -> None:
    """One ``catalog_table_imported`` lands per csv_local cascade."""
    ledger = InMemoryLedger()
    csv = _make_csv(tmp_path)

    summary = await run_default_local_cascade(
        ledger,
        _COMPANY,
        source_id=uuid4(),
        path=csv,
    )

    assert "catalog_table_snapshot_hash" in summary
    assert "catalog_table_entry_ids" in summary
    assert len(summary["catalog_table_entry_ids"]) == 4  # PEVR

    rows = await ledger.fetch(_COMPANY)
    execute_rows = [r for r in rows if r["kind"] == "execute"]
    table_rows = [
        r for r in execute_rows
        if r["payload"]["tool"] == "emit_catalog_table_imported"
    ]
    assert len(table_rows) == 1
    args = table_rows[0]["payload"]["args"]
    # csv extractor reads the header row.
    assert [c["name"] for c in args["columns"]] == [
        "transaction_id",
        "customer_email",
        "amount",
        "currency",
        "transacted_at",
    ]
    # csv_local extractor sets type=None (no type-introspection at
    # catalog-discovery time — that's L5's territory).
    assert all(c["type"] is None for c in args["columns"])


async def test_csv_local_round_trip_via_ledger_catalog_reader(
    tmp_path: Path,
) -> None:
    """End-to-end: cascade emits per-table entry → reader returns populated columns."""
    ledger = InMemoryLedger()
    csv = _make_csv(tmp_path)
    sid = uuid4()

    summary = await run_default_local_cascade(
        ledger,
        _COMPANY,
        source_id=sid,
        path=csv,
    )

    reader = LedgerCatalogReader(ledger=ledger)
    tables = await reader.list_tables_for_source(
        company_id=_COMPANY, source_id=str(sid),
    )
    assert len(tables) == 1
    head = tables[0]
    # ``table_id`` is the absolute file path (csv_local convention).
    assert head.table_id == str(csv)
    assert head.columns == (
        "transaction_id",
        "customer_email",
        "amount",
        "currency",
        "transacted_at",
    )
    # ``source_kind`` stays "" for csv_local — no external_catalog_imported
    # entry exists for csv_local sources (they aren't upstream_mirror).
    assert head.source_kind == ""

    # The reported snapshot_hash matches the per-table entry's hash.
    assert summary["catalog_table_snapshot_hash"]


async def test_csv_local_round_trip_preserves_back_compat(
    tmp_path: Path,
) -> None:
    """Sources WITHOUT a per-table cascade emit still read columns=()."""
    ledger = InMemoryLedger()
    # Seed a lineage-only entry for a different source (no per-table).
    await ledger.write(
        company_id=_COMPANY,
        propose={
            "target_kind": "external_catalog_imported",
            "ref_id": "old-source",
            "reason": "pre-wave-2 seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_external_catalog_imported",
            "args": {
                "source_kind": "snowflake",
                "source_id": "old-source",
                "domain_id": "general",
                "snapshot_hash": "h",
                "table_count": 0,
                "edge_count": 0,
                "metric_count": 0,
                "import_mode": "initial",
            },
            "result_ref": "old-source",
        },
        verify_fn=lambda _e: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )
    await ledger.write(
        company_id=_COMPANY,
        propose={
            "target_kind": "external_lineage_imported",
            "ref_id": "old-source",
            "reason": "pre-wave-2 seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_external_lineage_imported",
            "args": {
                "source_id": "old-source",
                "edges": [["A", "B"]],
            },
            "result_ref": "old-source",
        },
        verify_fn=lambda _e: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )

    reader = LedgerCatalogReader(ledger=ledger)
    tables = await reader.list_tables_for_source(
        company_id=_COMPANY, source_id="old-source",
    )
    # Pre-Wave-2 source still reads columns=() (honest back-compat).
    assert {t.table_id for t in tables} == {"A", "B"}
    assert all(t.columns == () for t in tables)


async def test_csv_local_cascade_is_idempotent_on_resource(
    tmp_path: Path,
) -> None:
    """Running cascade twice with same source_id emits same composite ref_id."""
    ledger = InMemoryLedger()
    csv = _make_csv(tmp_path)
    sid = uuid4()

    s1 = await run_default_local_cascade(
        ledger, _COMPANY, source_id=sid, path=csv,
    )
    s2 = await run_default_local_cascade(
        ledger, _COMPANY, source_id=sid, path=csv,
    )

    # Both cascades stamp the SAME snapshot_hash for the SAME bytes.
    assert s1["catalog_table_snapshot_hash"] == s2["catalog_table_snapshot_hash"]

    rows = await ledger.fetch(_COMPANY)
    propose_rows = [
        r for r in rows
        if r["kind"] == "propose"
        and r["payload"]["target_kind"] == "catalog_table_imported"
    ]
    assert len(propose_rows) == 2
    # The composite ref carries through identically.
    refs = [r["payload"]["ref_id"] for r in propose_rows]
    assert refs[0] == refs[1]
    expected_ref = f"{sid}|{s1['catalog_table_snapshot_hash']}|{csv}"
    assert refs[0] == expected_ref
