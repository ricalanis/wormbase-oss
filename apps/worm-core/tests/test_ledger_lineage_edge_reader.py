"""L4 Sub-wave C — LedgerLineageEdgeReader cross-axis read tests.

Pins the first lake-side cross-axis Protocol impl: L4 reading L3's
confirmed lineage edges. Verifies:

  * Empty ledger → empty list.
  * Proposed-but-not-confirmed edges are filtered out (state contract).
  * Confirmed edges are returned with all minimum-coupling fields
    populated.
  * Rejected edges are filtered out.
  * src_column filter is exact-match; whole-table (None) edges skipped.
  * Tenant isolation rides company_id.
  * Deterministic ordering for replay stability.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.schema_impact_lineage_reader import LedgerLineageEdgeReader

_COMPANY_A = UUID("00000000-0000-0000-0000-0000000d0010")
_COMPANY_B = UUID("00000000-0000-0000-0000-0000000d0011")


async def _emit_proposed_edge(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    edge_id: str,
    src_table_id: str,
    src_column: str | None,
    tgt_table_id: str,
    tgt_column: str | None,
    confidence: float = 0.95,
    strategy: str = "dbt_manifest",
) -> None:
    """Emit a ``lineage_edge_proposed`` execute entry."""
    args: dict[str, Any] = {
        "edge_id": edge_id,
        "src_table_id": src_table_id,
        "src_column": src_column,
        "tgt_table_id": tgt_table_id,
        "tgt_column": tgt_column,
        "confidence": confidence,
        "strategy": strategy,
        "reasoning": "seed",
        "evidence": {},
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "lineage_edge_proposed",
            "ref_id": edge_id,
            "reason": "seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_lineage_edge_proposed",
            "args": args,
            "result_ref": edge_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


async def _emit_confirmed_edge(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    edge_id: str,
) -> None:
    """Emit a ``lineage_edge_confirmed`` execute entry."""
    args: dict[str, Any] = {
        "edge_id": edge_id,
        "confirmed_by_person_id": "test-admin",
        "notes": None,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "lineage_edge_confirmed",
            "ref_id": edge_id,
            "reason": "confirm",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_lineage_edge_confirmed",
            "args": args,
            "result_ref": edge_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


async def _emit_rejected_edge(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    edge_id: str,
    reason: str = "false_positive",
) -> None:
    """Emit a ``lineage_edge_rejected`` execute entry."""
    args: dict[str, Any] = {
        "edge_id": edge_id,
        "rejected_by_person_id": "test-admin",
        "reason": reason,
        "notes": None,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "lineage_edge_rejected",
            "ref_id": edge_id,
            "reason": "reject",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_lineage_edge_rejected",
            "args": args,
            "result_ref": edge_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


@pytest.mark.asyncio
async def test_empty_ledger_returns_empty() -> None:
    ledger = InMemoryLedger()
    reader = LedgerLineageEdgeReader(ledger=ledger)
    edges = await reader.list_confirmed_edges_for_source_column(
        source_id="stripe_src",
        src_column="customer_id",
        company_id=_COMPANY_A,
    )
    assert edges == []


@pytest.mark.asyncio
async def test_only_proposed_edges_filtered_out() -> None:
    """A proposed-but-not-confirmed edge MUST NOT be returned."""
    ledger = InMemoryLedger()
    await _emit_proposed_edge(
        ledger,
        company_id=_COMPANY_A,
        edge_id="edge-1",
        src_table_id="stripe_src.public.customers",
        src_column="customer_id",
        tgt_table_id="warehouse.dim_customer",
        tgt_column="customer_id",
    )
    reader = LedgerLineageEdgeReader(ledger=ledger)
    edges = await reader.list_confirmed_edges_for_source_column(
        source_id="stripe_src",
        src_column="customer_id",
        company_id=_COMPANY_A,
    )
    assert edges == []


@pytest.mark.asyncio
async def test_confirmed_edge_is_returned() -> None:
    """A confirmed edge IS returned with all coupling fields populated."""
    ledger = InMemoryLedger()
    await _emit_proposed_edge(
        ledger,
        company_id=_COMPANY_A,
        edge_id="edge-confirm-1",
        src_table_id="stripe_src.public.customers",
        src_column="customer_id",
        tgt_table_id="warehouse.dim_customer",
        tgt_column="customer_id",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    await _emit_confirmed_edge(
        ledger,
        company_id=_COMPANY_A,
        edge_id="edge-confirm-1",
    )

    reader = LedgerLineageEdgeReader(ledger=ledger)
    edges = await reader.list_confirmed_edges_for_source_column(
        source_id="stripe_src",
        src_column="customer_id",
        company_id=_COMPANY_A,
    )
    assert len(edges) == 1
    e = edges[0]
    assert e.edge_id == "edge-confirm-1"
    assert e.src_table_id == "stripe_src.public.customers"
    assert e.src_column == "customer_id"
    assert e.tgt_table_id == "warehouse.dim_customer"
    assert e.tgt_column == "customer_id"
    assert e.confidence == pytest.approx(0.99)
    assert e.strategy == "dbt_manifest"


@pytest.mark.asyncio
async def test_rejected_edge_filtered_out() -> None:
    """Proposed → confirmed → rejected stays out (final state wins)."""
    ledger = InMemoryLedger()
    await _emit_proposed_edge(
        ledger,
        company_id=_COMPANY_A,
        edge_id="edge-reject-1",
        src_table_id="stripe_src.public.customers",
        src_column="customer_id",
        tgt_table_id="warehouse.dim_customer",
        tgt_column="customer_id",
    )
    await _emit_confirmed_edge(
        ledger,
        company_id=_COMPANY_A,
        edge_id="edge-reject-1",
    )
    await _emit_rejected_edge(
        ledger,
        company_id=_COMPANY_A,
        edge_id="edge-reject-1",
    )
    reader = LedgerLineageEdgeReader(ledger=ledger)
    edges = await reader.list_confirmed_edges_for_source_column(
        source_id="stripe_src",
        src_column="customer_id",
        company_id=_COMPANY_A,
    )
    assert edges == []


@pytest.mark.asyncio
async def test_src_column_filter_exact_match() -> None:
    """Only the requested src_column propagates; other columns skipped."""
    ledger = InMemoryLedger()
    await _emit_proposed_edge(
        ledger,
        company_id=_COMPANY_A,
        edge_id="edge-c1",
        src_table_id="stripe_src.public.customers",
        src_column="customer_id",
        tgt_table_id="wh.t1",
        tgt_column="customer_id",
    )
    await _emit_confirmed_edge(ledger, company_id=_COMPANY_A, edge_id="edge-c1")

    await _emit_proposed_edge(
        ledger,
        company_id=_COMPANY_A,
        edge_id="edge-c2",
        src_table_id="stripe_src.public.customers",
        src_column="email",
        tgt_table_id="wh.t1",
        tgt_column="email",
    )
    await _emit_confirmed_edge(ledger, company_id=_COMPANY_A, edge_id="edge-c2")

    reader = LedgerLineageEdgeReader(ledger=ledger)
    edges = await reader.list_confirmed_edges_for_source_column(
        source_id="stripe_src",
        src_column="customer_id",
        company_id=_COMPANY_A,
    )
    assert len(edges) == 1
    assert edges[0].edge_id == "edge-c1"


@pytest.mark.asyncio
async def test_whole_table_edges_skipped() -> None:
    """Edges with src_column=None (whole-table dbt-manifest) are skipped.

    L4 only reasons over column-grain propagation; whole-table edges
    cannot be matched against a specific changed column.
    """
    ledger = InMemoryLedger()
    await _emit_proposed_edge(
        ledger,
        company_id=_COMPANY_A,
        edge_id="edge-whole",
        src_table_id="stripe_src.public.customers",
        src_column=None,  # whole-table ref
        tgt_table_id="warehouse.dim_customer",
        tgt_column=None,
    )
    await _emit_confirmed_edge(
        ledger,
        company_id=_COMPANY_A,
        edge_id="edge-whole",
    )

    reader = LedgerLineageEdgeReader(ledger=ledger)
    edges = await reader.list_confirmed_edges_for_source_column(
        source_id="stripe_src",
        src_column="customer_id",
        company_id=_COMPANY_A,
    )
    assert edges == []


@pytest.mark.asyncio
async def test_tenant_isolation() -> None:
    """Tenant A's confirmed edges are NOT visible to tenant B."""
    ledger = InMemoryLedger()
    await _emit_proposed_edge(
        ledger,
        company_id=_COMPANY_A,
        edge_id="edge-tenant-a",
        src_table_id="stripe_src.public.customers",
        src_column="customer_id",
        tgt_table_id="wh.t1",
        tgt_column="customer_id",
    )
    await _emit_confirmed_edge(
        ledger,
        company_id=_COMPANY_A,
        edge_id="edge-tenant-a",
    )

    reader = LedgerLineageEdgeReader(ledger=ledger)
    edges_b = await reader.list_confirmed_edges_for_source_column(
        source_id="stripe_src",
        src_column="customer_id",
        company_id=_COMPANY_B,
    )
    assert edges_b == []

    edges_a = await reader.list_confirmed_edges_for_source_column(
        source_id="stripe_src",
        src_column="customer_id",
        company_id=_COMPANY_A,
    )
    assert len(edges_a) == 1


@pytest.mark.asyncio
async def test_source_prefix_filter() -> None:
    """Only edges sourced from the requested source_id are returned."""
    ledger = InMemoryLedger()
    await _emit_proposed_edge(
        ledger,
        company_id=_COMPANY_A,
        edge_id="edge-stripe",
        src_table_id="stripe_src.public.customers",
        src_column="customer_id",
        tgt_table_id="wh.t1",
        tgt_column="customer_id",
    )
    await _emit_confirmed_edge(
        ledger, company_id=_COMPANY_A, edge_id="edge-stripe",
    )
    await _emit_proposed_edge(
        ledger,
        company_id=_COMPANY_A,
        edge_id="edge-pg",
        src_table_id="postgres_src.public.customers",
        src_column="customer_id",
        tgt_table_id="wh.t1",
        tgt_column="customer_id",
    )
    await _emit_confirmed_edge(
        ledger, company_id=_COMPANY_A, edge_id="edge-pg",
    )

    reader = LedgerLineageEdgeReader(ledger=ledger)
    edges = await reader.list_confirmed_edges_for_source_column(
        source_id="stripe_src",
        src_column="customer_id",
        company_id=_COMPANY_A,
    )
    assert len(edges) == 1
    assert edges[0].edge_id == "edge-stripe"
