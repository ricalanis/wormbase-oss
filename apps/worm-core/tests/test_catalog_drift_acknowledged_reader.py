"""L4↦L2 Sub-wave chain — LedgerAcknowledgedDriftReader cross-axis read tests.

Pins the **7th cross-axis Protocol** impl: L4 reading L2's acknowledged
catalog drifts. This is the **first BIDIRECTIONAL chain** (L4 elevates
impacts on L2 acks forward; L2 dashboard surfaces downstream impact
counts in reverse — the latter is dashboard-only).

Mirrors the L4 :class:`LedgerLineageEdgeReader` and L6
:class:`LedgerConfirmedClassificationReader` test shapes. Verifies:

  * Empty ledger → empty list.
  * Proposed-but-not-acknowledged drifts filtered out (state contract).
  * Acknowledged drifts returned with all minimum-coupling fields
    populated (including acknowledged_at + acknowledged_by_person_id
    from the acknowledgement entry).
  * Rejected drifts filtered out (final state wins).
  * Source/column filter is exact-match on (source_id, column).
  * Null column = table-level drift filter.
  * Tenant isolation rides company_id.
  * Multiple drifts on the same column → all surfaced.
  * Deterministic ordering by drift_id for replay stability.
  * Re-state cycles: proposed → acknowledged → rejected → re-proposed
    → re-acknowledged yields the latest acknowledged state.
  * Acknowledgement of unknown drift_id is silently ignored.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.catalog_drift_acknowledged_reader import (
    LedgerAcknowledgedDriftReader,
)

_COMPANY_A = UUID("00000000-0000-0000-0000-0000000d6050")
_COMPANY_B = UUID("00000000-0000-0000-0000-0000000d6051")


async def _emit_proposed(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    drift_id: str,
    source_id: str = "warehouse",
    table_id: str = "warehouse.dim_customer",
    column: str | None = "email",
    drift_kind: str = "column_type_changed",
    before: dict | None = None,
    after: dict | None = None,
    strategy: str = "column_type",
    confidence: float = 0.85,
) -> None:
    """Emit a ``catalog_drift_proposed`` execute entry.

    Defaults sensible per-kind: column_type_changed carries before+after.
    """
    if drift_kind == "column_type_changed":
        before = before if before is not None else {"type": "varchar"}
        after = after if after is not None else {"type": "text"}
    elif drift_kind in ("column_added", "table_added"):
        before = None
    elif drift_kind in ("column_removed", "table_removed"):
        after = None
    args: dict[str, Any] = {
        "drift_id": drift_id,
        "source_id": source_id,
        "table_id": table_id,
        "column": column,
        "drift_kind": drift_kind,
        "before": before,
        "after": after,
        "strategy": strategy,
        "reasoning": "seed",
        "confidence": confidence,
        "evidence": {},
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "catalog_drift_proposed",
            "ref_id": drift_id,
            "reason": "seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_catalog_drift_proposed",
            "args": args,
            "result_ref": drift_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


async def _emit_acknowledged(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    drift_id: str,
    acknowledged_by_person_id: str = "alice-admin",
    notes: str | None = None,
) -> None:
    """Emit a ``catalog_drift_acknowledged`` execute entry."""
    args: dict[str, Any] = {
        "drift_id": drift_id,
        "acknowledged_by_person_id": acknowledged_by_person_id,
        "notes": notes,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "catalog_drift_acknowledged",
            "ref_id": drift_id,
            "reason": "ack",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_catalog_drift_acknowledged",
            "args": args,
            "result_ref": drift_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


async def _emit_rejected(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    drift_id: str,
    reason: str = "false_positive",
) -> None:
    """Emit a ``catalog_drift_rejected`` execute entry."""
    args: dict[str, Any] = {
        "drift_id": drift_id,
        "rejected_by_person_id": "alice-admin",
        "reason": reason,
        "notes": None,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "catalog_drift_rejected",
            "ref_id": drift_id,
            "reason": "reject",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_catalog_drift_rejected",
            "args": args,
            "result_ref": drift_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


# ---------------------------------------------------------------------------
# Empty / proposed-only / rejected-only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_ledger_returns_empty() -> None:
    ledger = InMemoryLedger()
    reader = LedgerAcknowledgedDriftReader(ledger=ledger)
    records = await reader.list_acknowledged_drifts(company_id=_COMPANY_A)
    assert records == []
    by_source = await reader.list_acknowledged_drifts_for_source_column(
        "warehouse", "email", company_id=_COMPANY_A,
    )
    assert by_source == []


@pytest.mark.asyncio
async def test_only_proposed_filtered_out() -> None:
    """Proposed-but-not-acknowledged drifts MUST NOT be returned."""
    ledger = InMemoryLedger()
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        drift_id="drift-pending-1",
    )
    reader = LedgerAcknowledgedDriftReader(ledger=ledger)
    records = await reader.list_acknowledged_drifts(company_id=_COMPANY_A)
    assert records == []


@pytest.mark.asyncio
async def test_proposed_then_acknowledged_is_returned() -> None:
    """proposed → acknowledged → 1 record carrying fields from BOTH entries."""
    ledger = InMemoryLedger()
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        drift_id="drift-1",
        source_id="warehouse",
        table_id="warehouse.dim_customer",
        column="email",
        drift_kind="column_type_changed",
    )
    await _emit_acknowledged(
        ledger,
        company_id=_COMPANY_A,
        drift_id="drift-1",
        acknowledged_by_person_id="alice-admin",
    )
    reader = LedgerAcknowledgedDriftReader(ledger=ledger)
    records = await reader.list_acknowledged_drifts(company_id=_COMPANY_A)
    assert len(records) == 1
    r = records[0]
    # From proposal payload
    assert r.drift_id == "drift-1"
    assert r.source_id == "warehouse"
    assert r.table_id == "warehouse.dim_customer"
    assert r.column == "email"
    assert r.drift_kind == "column_type_changed"
    assert r.before == {"type": "varchar"}
    assert r.after == {"type": "text"}
    # From acknowledgement payload
    assert r.acknowledged_by_person_id == "alice-admin"
    assert r.acknowledged_at is not None


@pytest.mark.asyncio
async def test_acknowledged_then_rejected_filtered_out() -> None:
    """proposed → acknowledged → rejected → [] (rejection wins)."""
    ledger = InMemoryLedger()
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        drift_id="drift-rejected",
    )
    await _emit_acknowledged(
        ledger,
        company_id=_COMPANY_A,
        drift_id="drift-rejected",
    )
    await _emit_rejected(
        ledger,
        company_id=_COMPANY_A,
        drift_id="drift-rejected",
    )
    reader = LedgerAcknowledgedDriftReader(ledger=ledger)
    records = await reader.list_acknowledged_drifts(company_id=_COMPANY_A)
    assert records == []


@pytest.mark.asyncio
async def test_acknowledgement_of_unknown_drift_ignored() -> None:
    """A bare acknowledgement (no prior proposal) is silently ignored."""
    ledger = InMemoryLedger()
    await _emit_acknowledged(
        ledger,
        company_id=_COMPANY_A,
        drift_id="orphan-drift",
    )
    reader = LedgerAcknowledgedDriftReader(ledger=ledger)
    records = await reader.list_acknowledged_drifts(company_id=_COMPANY_A)
    assert records == []


# ---------------------------------------------------------------------------
# Multi-tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_isolation() -> None:
    """Different company_ids see only their own acknowledged drifts."""
    ledger = InMemoryLedger()
    await _emit_proposed(
        ledger, company_id=_COMPANY_A, drift_id="drift-a", source_id="a-warehouse",
    )
    await _emit_acknowledged(
        ledger, company_id=_COMPANY_A, drift_id="drift-a",
    )
    await _emit_proposed(
        ledger, company_id=_COMPANY_B, drift_id="drift-b", source_id="b-warehouse",
    )
    await _emit_acknowledged(
        ledger, company_id=_COMPANY_B, drift_id="drift-b",
    )

    reader = LedgerAcknowledgedDriftReader(ledger=ledger)
    a_records = await reader.list_acknowledged_drifts(company_id=_COMPANY_A)
    assert len(a_records) == 1
    assert a_records[0].drift_id == "drift-a"

    b_records = await reader.list_acknowledged_drifts(company_id=_COMPANY_B)
    assert len(b_records) == 1
    assert b_records[0].drift_id == "drift-b"


# ---------------------------------------------------------------------------
# Source/column filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_column_filter_match() -> None:
    """list_acknowledged_drifts_for_source_column returns only matching drifts."""
    ledger = InMemoryLedger()
    await _emit_proposed(
        ledger, company_id=_COMPANY_A, drift_id="d-email",
        source_id="warehouse", column="email",
    )
    await _emit_acknowledged(ledger, company_id=_COMPANY_A, drift_id="d-email")
    await _emit_proposed(
        ledger, company_id=_COMPANY_A, drift_id="d-phone",
        source_id="warehouse", column="phone",
    )
    await _emit_acknowledged(ledger, company_id=_COMPANY_A, drift_id="d-phone")
    await _emit_proposed(
        ledger, company_id=_COMPANY_A, drift_id="d-other-source",
        source_id="other_warehouse", column="email",
    )
    await _emit_acknowledged(ledger, company_id=_COMPANY_A, drift_id="d-other-source")

    reader = LedgerAcknowledgedDriftReader(ledger=ledger)
    records = await reader.list_acknowledged_drifts_for_source_column(
        "warehouse", "email", company_id=_COMPANY_A,
    )
    assert len(records) == 1
    assert records[0].drift_id == "d-email"


@pytest.mark.asyncio
async def test_source_column_filter_none_returns_table_drifts() -> None:
    """src_column=None returns ONLY table-level drifts (drift.column is None)."""
    ledger = InMemoryLedger()
    await _emit_proposed(
        ledger, company_id=_COMPANY_A, drift_id="d-table-add",
        source_id="warehouse", table_id="warehouse.new_table",
        column=None, drift_kind="table_added",
    )
    await _emit_acknowledged(ledger, company_id=_COMPANY_A, drift_id="d-table-add")
    await _emit_proposed(
        ledger, company_id=_COMPANY_A, drift_id="d-col-add",
        source_id="warehouse", column="email", drift_kind="column_added",
    )
    await _emit_acknowledged(ledger, company_id=_COMPANY_A, drift_id="d-col-add")

    reader = LedgerAcknowledgedDriftReader(ledger=ledger)
    table_only = await reader.list_acknowledged_drifts_for_source_column(
        "warehouse", None, company_id=_COMPANY_A,
    )
    assert len(table_only) == 1
    assert table_only[0].drift_id == "d-table-add"
    assert table_only[0].column is None


@pytest.mark.asyncio
async def test_source_column_filter_empty_source_id() -> None:
    """Empty source_id → empty list (defensive)."""
    ledger = InMemoryLedger()
    await _emit_proposed(ledger, company_id=_COMPANY_A, drift_id="d-1")
    await _emit_acknowledged(ledger, company_id=_COMPANY_A, drift_id="d-1")
    reader = LedgerAcknowledgedDriftReader(ledger=ledger)
    records = await reader.list_acknowledged_drifts_for_source_column(
        "", "email", company_id=_COMPANY_A,
    )
    assert records == []


# ---------------------------------------------------------------------------
# Replay stability + multi-drift
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deterministic_ordering_by_drift_id() -> None:
    """Multiple acknowledged drifts are returned sorted by drift_id ascending."""
    ledger = InMemoryLedger()
    # Emit in non-sorted order
    for drift_id in ("d-c", "d-a", "d-b"):
        await _emit_proposed(
            ledger, company_id=_COMPANY_A, drift_id=drift_id,
            column=drift_id,
        )
        await _emit_acknowledged(
            ledger, company_id=_COMPANY_A, drift_id=drift_id,
        )

    reader = LedgerAcknowledgedDriftReader(ledger=ledger)
    records = await reader.list_acknowledged_drifts(company_id=_COMPANY_A)
    assert [r.drift_id for r in records] == ["d-a", "d-b", "d-c"]


@pytest.mark.asyncio
async def test_multiple_drifts_same_column_all_returned() -> None:
    """Multiple acknowledged drifts on the same column are ALL surfaced."""
    ledger = InMemoryLedger()
    for drift_id, drift_kind in (
        ("d-add-email", "column_added"),
        ("d-type-email", "column_type_changed"),
    ):
        await _emit_proposed(
            ledger, company_id=_COMPANY_A, drift_id=drift_id,
            column="email", drift_kind=drift_kind,
        )
        await _emit_acknowledged(
            ledger, company_id=_COMPANY_A, drift_id=drift_id,
        )

    reader = LedgerAcknowledgedDriftReader(ledger=ledger)
    records = await reader.list_acknowledged_drifts_for_source_column(
        "warehouse", "email", company_id=_COMPANY_A,
    )
    assert len(records) == 2
    drift_ids = {r.drift_id for r in records}
    assert drift_ids == {"d-add-email", "d-type-email"}


@pytest.mark.asyncio
async def test_re_state_cycle_yields_latest_state() -> None:
    """proposed → ack → rejected → re-proposed → re-ack → record visible.

    Verifies last-write-wins per L2 projection-fold semantics. A
    drift that's been through a full cycle and re-acknowledged at the
    end IS surfaced.
    """
    ledger = InMemoryLedger()
    drift_id = "d-cycle-1"
    # First cycle: proposed → acknowledged → rejected
    await _emit_proposed(
        ledger, company_id=_COMPANY_A, drift_id=drift_id, column="email",
    )
    await _emit_acknowledged(
        ledger, company_id=_COMPANY_A, drift_id=drift_id,
    )
    await _emit_rejected(
        ledger, company_id=_COMPANY_A, drift_id=drift_id,
    )
    # Second cycle: re-proposed → re-acknowledged
    await _emit_proposed(
        ledger, company_id=_COMPANY_A, drift_id=drift_id, column="email",
    )
    await _emit_acknowledged(
        ledger, company_id=_COMPANY_A, drift_id=drift_id,
        acknowledged_by_person_id="bob-admin",
    )

    reader = LedgerAcknowledgedDriftReader(ledger=ledger)
    records = await reader.list_acknowledged_drifts(company_id=_COMPANY_A)
    assert len(records) == 1
    r = records[0]
    assert r.drift_id == drift_id
    # Latest acknowledgement metadata (bob, not the first alice).
    assert r.acknowledged_by_person_id == "bob-admin"


@pytest.mark.asyncio
async def test_column_type_changed_carries_before_and_after() -> None:
    """column_type_changed records carry both before+after type dicts."""
    ledger = InMemoryLedger()
    await _emit_proposed(
        ledger, company_id=_COMPANY_A, drift_id="d-type",
        drift_kind="column_type_changed",
        before={"type": "int"}, after={"type": "varchar"},
    )
    await _emit_acknowledged(ledger, company_id=_COMPANY_A, drift_id="d-type")
    reader = LedgerAcknowledgedDriftReader(ledger=ledger)
    records = await reader.list_acknowledged_drifts(company_id=_COMPANY_A)
    assert len(records) == 1
    assert records[0].before == {"type": "int"}
    assert records[0].after == {"type": "varchar"}
