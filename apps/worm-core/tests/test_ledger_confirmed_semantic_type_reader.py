"""L6 Sub-wave C — LedgerConfirmedSemanticTypeReader cross-axis read tests.

Pins the second lake-side cross-axis Protocol impl: L6 reading L5's
confirmed semantic types. Verifies:

  * Empty ledger → empty list.
  * Proposed-but-not-confirmed types are filtered out (state contract).
  * Confirmed types are returned with all minimum-coupling fields
    populated.
  * Rejected types are filtered out.
  * table_id + column filter is exact-match.
  * Tenant isolation rides company_id.
  * Deterministic ordering for replay stability.

Mirrors the L4 :class:`LedgerLineageEdgeReader` test shape — same
cross-axis-read template applied to L5's confirmed semantic types.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.column_classification_semantic_reader import (
    LedgerConfirmedSemanticTypeReader,
)

_COMPANY_A = UUID("00000000-0000-0000-0000-0000000d0020")
_COMPANY_B = UUID("00000000-0000-0000-0000-0000000d0021")


async def _emit_proposed_type(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    type_id: str,
    table_id: str,
    column: str,
    semantic_type: str = "email",
    confidence: float = 0.9,
    strategy: str = "column_name",
) -> None:
    """Emit a ``semantic_type_proposed`` execute entry."""
    args: dict[str, Any] = {
        "type_id": type_id,
        "table_id": table_id,
        "column": column,
        "semantic_type": semantic_type,
        "confidence": confidence,
        "strategy": strategy,
        "reasoning": "seed",
        "evidence": {},
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "semantic_type_proposed",
            "ref_id": type_id,
            "reason": "seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_semantic_type_proposed",
            "args": args,
            "result_ref": type_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


async def _emit_confirmed_type(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    type_id: str,
) -> None:
    """Emit a ``semantic_type_confirmed`` execute entry."""
    args: dict[str, Any] = {
        "type_id": type_id,
        "confirmed_by_person_id": "test-admin",
        "notes": None,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "semantic_type_confirmed",
            "ref_id": type_id,
            "reason": "confirm",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_semantic_type_confirmed",
            "args": args,
            "result_ref": type_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


async def _emit_rejected_type(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    type_id: str,
    reason: str = "false_positive",
) -> None:
    """Emit a ``semantic_type_rejected`` execute entry."""
    args: dict[str, Any] = {
        "type_id": type_id,
        "rejected_by_person_id": "test-admin",
        "reason": reason,
        "notes": None,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "semantic_type_rejected",
            "ref_id": type_id,
            "reason": "reject",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_semantic_type_rejected",
            "args": args,
            "result_ref": type_id,
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
    reader = LedgerConfirmedSemanticTypeReader(ledger=ledger)
    types = await reader.list_confirmed_types_for_table_column(
        table_id="warehouse.dim_customer",
        column="email",
        company_id=_COMPANY_A,
    )
    assert types == []


@pytest.mark.asyncio
async def test_only_proposed_types_filtered_out() -> None:
    """A proposed-but-not-confirmed type MUST NOT be returned."""
    ledger = InMemoryLedger()
    await _emit_proposed_type(
        ledger,
        company_id=_COMPANY_A,
        type_id="type-1",
        table_id="warehouse.dim_customer",
        column="email",
    )
    reader = LedgerConfirmedSemanticTypeReader(ledger=ledger)
    types = await reader.list_confirmed_types_for_table_column(
        table_id="warehouse.dim_customer",
        column="email",
        company_id=_COMPANY_A,
    )
    assert types == []


@pytest.mark.asyncio
async def test_confirmed_type_is_returned() -> None:
    """A confirmed type IS returned with all coupling fields populated."""
    ledger = InMemoryLedger()
    await _emit_proposed_type(
        ledger,
        company_id=_COMPANY_A,
        type_id="type-confirm-1",
        table_id="warehouse.dim_customer",
        column="email",
        semantic_type="email",
        confidence=0.92,
        strategy="value_pattern",
    )
    await _emit_confirmed_type(
        ledger, company_id=_COMPANY_A, type_id="type-confirm-1",
    )

    reader = LedgerConfirmedSemanticTypeReader(ledger=ledger)
    types = await reader.list_confirmed_types_for_table_column(
        table_id="warehouse.dim_customer",
        column="email",
        company_id=_COMPANY_A,
    )
    assert len(types) == 1
    t = types[0]
    assert t.type_id == "type-confirm-1"
    assert t.semantic_type == "email"
    assert t.confidence == pytest.approx(0.92)
    assert t.strategy == "value_pattern"


@pytest.mark.asyncio
async def test_rejected_type_filtered_out() -> None:
    """Proposed → confirmed → rejected stays out (final state wins)."""
    ledger = InMemoryLedger()
    await _emit_proposed_type(
        ledger,
        company_id=_COMPANY_A,
        type_id="type-reject-1",
        table_id="warehouse.dim_customer",
        column="email",
    )
    await _emit_confirmed_type(
        ledger, company_id=_COMPANY_A, type_id="type-reject-1",
    )
    await _emit_rejected_type(
        ledger, company_id=_COMPANY_A, type_id="type-reject-1",
    )
    reader = LedgerConfirmedSemanticTypeReader(ledger=ledger)
    types = await reader.list_confirmed_types_for_table_column(
        table_id="warehouse.dim_customer",
        column="email",
        company_id=_COMPANY_A,
    )
    assert types == []


@pytest.mark.asyncio
async def test_table_column_filter_exact_match() -> None:
    """Only the requested (table_id, column) match propagates; others skipped."""
    ledger = InMemoryLedger()
    await _emit_proposed_type(
        ledger,
        company_id=_COMPANY_A,
        type_id="type-email",
        table_id="warehouse.dim_customer",
        column="email",
        semantic_type="email",
    )
    await _emit_confirmed_type(
        ledger, company_id=_COMPANY_A, type_id="type-email",
    )

    await _emit_proposed_type(
        ledger,
        company_id=_COMPANY_A,
        type_id="type-phone",
        table_id="warehouse.dim_customer",
        column="phone",
        semantic_type="phone_e164",
    )
    await _emit_confirmed_type(
        ledger, company_id=_COMPANY_A, type_id="type-phone",
    )

    # Same column, different table:
    await _emit_proposed_type(
        ledger,
        company_id=_COMPANY_A,
        type_id="type-other-table-email",
        table_id="warehouse.other_table",
        column="email",
        semantic_type="email",
    )
    await _emit_confirmed_type(
        ledger,
        company_id=_COMPANY_A,
        type_id="type-other-table-email",
    )

    reader = LedgerConfirmedSemanticTypeReader(ledger=ledger)
    types = await reader.list_confirmed_types_for_table_column(
        table_id="warehouse.dim_customer",
        column="email",
        company_id=_COMPANY_A,
    )
    assert len(types) == 1
    assert types[0].type_id == "type-email"


@pytest.mark.asyncio
async def test_tenant_isolation() -> None:
    """Tenant A's confirmed types are NOT visible to tenant B."""
    ledger = InMemoryLedger()
    await _emit_proposed_type(
        ledger,
        company_id=_COMPANY_A,
        type_id="type-tenant-a",
        table_id="warehouse.dim_customer",
        column="email",
    )
    await _emit_confirmed_type(
        ledger, company_id=_COMPANY_A, type_id="type-tenant-a",
    )

    reader = LedgerConfirmedSemanticTypeReader(ledger=ledger)
    types_b = await reader.list_confirmed_types_for_table_column(
        table_id="warehouse.dim_customer",
        column="email",
        company_id=_COMPANY_B,
    )
    assert types_b == []

    types_a = await reader.list_confirmed_types_for_table_column(
        table_id="warehouse.dim_customer",
        column="email",
        company_id=_COMPANY_A,
    )
    assert len(types_a) == 1


@pytest.mark.asyncio
async def test_multiple_confirmed_types_on_same_column_sorted() -> None:
    """Multiple confirmed types on (table, column) are returned sorted by type_id."""
    ledger = InMemoryLedger()
    # Insert in non-sorted order; reader must return them sorted by type_id.
    for tid, sem in [
        ("type-z-email", "email"),
        ("type-a-pii", "pii_name"),
        ("type-m-phone", "phone_e164"),
    ]:
        await _emit_proposed_type(
            ledger,
            company_id=_COMPANY_A,
            type_id=tid,
            table_id="warehouse.dim_customer",
            column="contact",
            semantic_type=sem,
        )
        await _emit_confirmed_type(
            ledger, company_id=_COMPANY_A, type_id=tid,
        )

    reader = LedgerConfirmedSemanticTypeReader(ledger=ledger)
    types = await reader.list_confirmed_types_for_table_column(
        table_id="warehouse.dim_customer",
        column="contact",
        company_id=_COMPANY_A,
    )
    assert [t.type_id for t in types] == [
        "type-a-pii",
        "type-m-phone",
        "type-z-email",
    ]
