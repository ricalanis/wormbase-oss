"""Catalog-mirror Wave 2 Sub-wave B — emit_catalog_table_imported PEVR tests.

Pins the per-table ``catalog_table_imported`` write helper landed in
write_actions.py: it writes the canonical 4-entry PEVR cycle, the
ref_id is the composite ``(source_id, snapshot_hash, table_id)``, and
re-emitting the same row yields the same ref_id (replay-stable).
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import CatalogColumnSpec

from wormbase_core import write_actions
from wormbase_core.write_actions import (
    emit_catalog_table_imported,
    emit_catalog_table_imported_for_resource,
)


_COMPANY = UUID("00000000-0000-0000-0000-0000000c0001")


async def test_emit_catalog_table_imported_writes_pevr_cycle() -> None:
    """Happy path: full 4-entry PEVR + the right ledger projection rows."""
    ledger = InMemoryLedger()
    sid = uuid4()
    result = await emit_catalog_table_imported(
        ledger=ledger,
        company_id=_COMPANY,
        source_id=sid,
        snapshot_hash="abc123" * 6 + "abc1",  # 40 chars
        table_id="schema.events",
        columns=[
            CatalogColumnSpec(name="id", type="bigint"),
            CatalogColumnSpec(name="ts", type="timestamp"),
        ],
    )
    assert len(result.entry_ids) == 4
    rows = await ledger.fetch(_COMPANY)
    kinds = [r["kind"] for r in rows]
    assert kinds == ["propose", "execute", "verify", "resolve"]


async def test_emit_catalog_table_imported_carries_canonical_payload() -> None:
    """execute payload matches CatalogTableImportedPayload field shape."""
    ledger = InMemoryLedger()
    sid = uuid4()
    snapshot_hash = "deadbeef" * 8
    await emit_catalog_table_imported(
        ledger=ledger,
        company_id=_COMPANY,
        source_id=sid,
        snapshot_hash=snapshot_hash,
        table_id="public.users",
        columns=[CatalogColumnSpec(name="email", type="text")],
    )
    rows = await ledger.fetch(_COMPANY)
    execute_row = next(r for r in rows if r["kind"] == "execute")
    args = execute_row["payload"]["args"]
    assert args["source_id"] == str(sid)
    assert args["snapshot_hash"] == snapshot_hash
    assert args["table_id"] == "public.users"
    assert args["columns"] == [{"name": "email", "type": "text"}]


async def test_emit_catalog_table_imported_tool_name_matches_kind() -> None:
    """``payload.tool`` must equal ``emit_catalog_table_imported``."""
    ledger = InMemoryLedger()
    sid = uuid4()
    await emit_catalog_table_imported(
        ledger=ledger,
        company_id=_COMPANY,
        source_id=sid,
        snapshot_hash="h" * 16,
        table_id="t",
        columns=(),
    )
    rows = await ledger.fetch(_COMPANY)
    execute_row = next(r for r in rows if r["kind"] == "execute")
    assert execute_row["payload"]["tool"] == "emit_catalog_table_imported"


async def test_emit_catalog_table_imported_empty_columns_is_valid() -> None:
    """Empty columns tuple is accepted (honest-empty-upstream)."""
    ledger = InMemoryLedger()
    sid = uuid4()
    result = await emit_catalog_table_imported(
        ledger=ledger,
        company_id=_COMPANY,
        source_id=sid,
        snapshot_hash="h" * 16,
        table_id="empty_table",
        columns=(),
    )
    assert len(result.entry_ids) == 4
    rows = await ledger.fetch(_COMPANY)
    args = next(r for r in rows if r["kind"] == "execute")["payload"]["args"]
    assert args["columns"] == []


async def test_emit_catalog_table_imported_ref_id_composite_format() -> None:
    """``ref_id`` is ``"{sid}|{snapshot_hash}|{table_id}"``."""
    ledger = InMemoryLedger()
    sid = uuid4()
    snap = "h" * 16
    await emit_catalog_table_imported(
        ledger=ledger,
        company_id=_COMPANY,
        source_id=sid,
        snapshot_hash=snap,
        table_id="my_table",
        columns=(),
    )
    rows = await ledger.fetch(_COMPANY)
    propose_row = next(r for r in rows if r["kind"] == "propose")
    expected = f"{sid}|{snap}|my_table"
    assert propose_row["payload"]["ref_id"] == expected


async def test_emit_catalog_table_imported_re_emit_idempotent_ref() -> None:
    """Same logical row → same ref_id, twice (replay-stable)."""
    ledger = InMemoryLedger()
    sid = uuid4()
    snap = "h" * 16
    for _ in range(2):
        await emit_catalog_table_imported(
            ledger=ledger,
            company_id=_COMPANY,
            source_id=sid,
            snapshot_hash=snap,
            table_id="orders",
            columns=(CatalogColumnSpec(name="id", type="bigint"),),
        )
    rows = await ledger.fetch(_COMPANY)
    propose_rows = [r for r in rows if r["kind"] == "propose"]
    assert len(propose_rows) == 2
    expected = f"{sid}|{snap}|orders"
    assert all(r["payload"]["ref_id"] == expected for r in propose_rows)


async def test_emit_catalog_table_imported_distinct_tables_distinct_refs() -> None:
    """Different table_ids → distinct ref_ids within the same snapshot."""
    ledger = InMemoryLedger()
    sid = uuid4()
    snap = "h" * 16
    for tid in ("t_a", "t_b", "t_c"):
        await emit_catalog_table_imported(
            ledger=ledger,
            company_id=_COMPANY,
            source_id=sid,
            snapshot_hash=snap,
            table_id=tid,
            columns=(),
        )
    rows = await ledger.fetch(_COMPANY)
    propose_rows = [r for r in rows if r["kind"] == "propose"]
    refs = [r["payload"]["ref_id"] for r in propose_rows]
    assert refs == [f"{sid}|{snap}|{t}" for t in ("t_a", "t_b", "t_c")]


async def test_emit_catalog_table_imported_accepts_string_source_id() -> None:
    """``source_id`` may be a str (e.g. composite key) or UUID."""
    ledger = InMemoryLedger()
    await emit_catalog_table_imported(
        ledger=ledger,
        company_id=_COMPANY,
        source_id="csv-local-source-id-string",
        snapshot_hash="h" * 16,
        table_id="t",
        columns=(),
    )
    rows = await ledger.fetch(_COMPANY)
    args = next(r for r in rows if r["kind"] == "execute")["payload"]["args"]
    assert args["source_id"] == "csv-local-source-id-string"


async def test_emit_catalog_table_imported_proposed_by_propagates() -> None:
    """``proposed_by`` rides through to the propose entry."""
    ledger = InMemoryLedger()
    await emit_catalog_table_imported(
        ledger=ledger,
        company_id=_COMPANY,
        source_id=uuid4(),
        snapshot_hash="h" * 16,
        table_id="t",
        columns=(),
        proposed_by="default_local_cascade",
    )
    rows = await ledger.fetch(_COMPANY)
    propose_row = next(r for r in rows if r["kind"] == "propose")
    assert propose_row["payload"]["proposed_by"] == "default_local_cascade"


async def test_emit_catalog_table_imported_validation_fires_on_empty_table_id() -> None:
    """Empty table_id raises (CatalogTableImportedPayload validator)."""
    ledger = InMemoryLedger()
    with pytest.raises(Exception):
        await emit_catalog_table_imported(
            ledger=ledger,
            company_id=_COMPANY,
            source_id=uuid4(),
            snapshot_hash="h" * 16,
            table_id="",
            columns=(),
        )


async def test_emit_catalog_table_imported_validation_fires_on_empty_snapshot_hash() -> None:
    """Empty snapshot_hash raises (CatalogTableImportedPayload validator)."""
    ledger = InMemoryLedger()
    with pytest.raises(Exception):
        await emit_catalog_table_imported(
            ledger=ledger,
            company_id=_COMPANY,
            source_id=uuid4(),
            snapshot_hash="",
            table_id="t",
            columns=(),
        )


# ---------------------------------------------------------------------------
# emit_catalog_table_imported_for_resource — extractor dispatch wrapper
# ---------------------------------------------------------------------------


async def test_emit_catalog_table_imported_for_resource_uses_extractor(
    tmp_path: Path,
) -> None:
    """csv_local extractor populates ``columns`` automatically."""
    csv_path = tmp_path / "fixture.csv"
    csv_path.write_text(
        "customer_id,email,amount\n1,a@x.com,10\n",
        encoding="utf-8",
    )

    ledger = InMemoryLedger()
    sid = uuid4()
    result = await emit_catalog_table_imported_for_resource(
        ledger=ledger,
        company_id=_COMPANY,
        source_id=sid,
        snapshot_hash="h" * 16,
        table_id=str(csv_path),
        connector_kind="csv_local",
        resource_id=str(csv_path),
    )
    assert len(result.entry_ids) == 4
    rows = await ledger.fetch(_COMPANY)
    args = next(r for r in rows if r["kind"] == "execute")["payload"]["args"]
    assert [c["name"] for c in args["columns"]] == [
        "customer_id", "email", "amount",
    ]
    assert all(c["type"] is None for c in args["columns"])


async def test_emit_catalog_table_imported_for_resource_unknown_kind_empty(
) -> None:
    """Unknown connector_kind → entry emits with ``columns=[]``."""
    ledger = InMemoryLedger()
    sid = uuid4()
    await emit_catalog_table_imported_for_resource(
        ledger=ledger,
        company_id=_COMPANY,
        source_id=sid,
        snapshot_hash="h" * 16,
        table_id="t",
        connector_kind="not-a-real-kind",
        resource_id="placeholder",
    )
    rows = await ledger.fetch(_COMPANY)
    args = next(r for r in rows if r["kind"] == "execute")["payload"]["args"]
    assert args["columns"] == []


async def test_emit_catalog_table_imported_for_resource_resource_id_defaults_to_table_id(
    tmp_path: Path,
) -> None:
    """``resource_id`` defaults to ``table_id`` when omitted."""
    csv_path = tmp_path / "implicit.csv"
    csv_path.write_text("h1,h2\n1,2\n", encoding="utf-8")

    ledger = InMemoryLedger()
    sid = uuid4()
    await emit_catalog_table_imported_for_resource(
        ledger=ledger,
        company_id=_COMPANY,
        source_id=sid,
        snapshot_hash="h" * 16,
        table_id=str(csv_path),  # resource_id intentionally omitted
        connector_kind="csv_local",
    )
    rows = await ledger.fetch(_COMPANY)
    args = next(r for r in rows if r["kind"] == "execute")["payload"]["args"]
    assert [c["name"] for c in args["columns"]] == ["h1", "h2"]


async def test_emit_catalog_table_imported_for_resource_propagates_proposed_by(
    tmp_path: Path,
) -> None:
    """proposed_by rides through to the propose entry."""
    csv_path = tmp_path / "p.csv"
    csv_path.write_text("a\n1\n", encoding="utf-8")
    ledger = InMemoryLedger()
    await emit_catalog_table_imported_for_resource(
        ledger=ledger,
        company_id=_COMPANY,
        source_id=uuid4(),
        snapshot_hash="h" * 16,
        table_id=str(csv_path),
        connector_kind="csv_local",
        proposed_by="my_custom_actor",
    )
    rows = await ledger.fetch(_COMPANY)
    propose_row = next(r for r in rows if r["kind"] == "propose")
    assert propose_row["payload"]["proposed_by"] == "my_custom_actor"


async def test_helpers_exported_from_write_actions_module() -> None:
    """Both helpers are exported on the module surface for HTTP callers."""
    assert hasattr(write_actions, "emit_catalog_table_imported")
    assert hasattr(write_actions, "emit_catalog_table_imported_for_resource")
