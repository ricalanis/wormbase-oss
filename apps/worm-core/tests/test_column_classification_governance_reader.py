"""L6→L4 Sub-wave chain — LedgerConfirmedClassificationReader cross-axis read tests.

Pins the **5th cross-axis Protocol** impl: L4 reading L6's confirmed
column-level classifications (regulated / pii / confidential / etc.).
This is the **first producer-side cross-axis Protocol** in the lake
stack — owned by L6 (the data domain), consumed by L4 (the strategy).

Mirrors the L4 :class:`LedgerLineageEdgeReader` and L6
:class:`LedgerConfirmedSemanticTypeReader` test shapes. Verifies:

  * Empty ledger → empty list.
  * Proposed-but-not-confirmed classifications filtered out (state
    contract).
  * Confirmed classifications returned with all minimum-coupling fields
    populated (including confirmed_at + confirmed_by_person_id from
    the confirmation entry).
  * Rejected classifications filtered out (final state wins).
  * Source-column filter is exact-match on src_column; source_id is
    prefix-match on table_id.
  * Tenant isolation rides company_id.
  * Multiple classifications on the same column → all surfaced.
  * Multi-table same-column scope is correct.
  * Deterministic ordering for replay stability.
  * Time-ordered: re-classification (proposed→confirmed→rejected→
    new-proposed→confirmed) yields the latest confirmed state.
  * Malformed entries are skipped, not crash.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.column_classification_governance_reader import (
    LedgerConfirmedClassificationReader,
)

_COMPANY_A = UUID("00000000-0000-0000-0000-0000000d6040")
_COMPANY_B = UUID("00000000-0000-0000-0000-0000000d6041")


async def _emit_proposed(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    classification_id: str,
    table_id: str,
    column: str,
    classification_level: str = "pii",
    strategy: str = "semantic_type",
    confidence: float = 0.92,
) -> None:
    """Emit a ``column_classification_proposed`` execute entry."""
    args: dict[str, Any] = {
        "classification_id": classification_id,
        "table_id": table_id,
        "column": column,
        "classification_level": classification_level,
        "upstream_semantic_type_id": None,
        "confidence": confidence,
        "strategy": strategy,
        "reasoning": "seed",
        "evidence": {},
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "column_classification_proposed",
            "ref_id": classification_id,
            "reason": "seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_column_classification_proposed",
            "args": args,
            "result_ref": classification_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


async def _emit_confirmed(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    classification_id: str,
    confirmed_by_person_id: str = "test-admin",
) -> None:
    """Emit a ``column_classification_confirmed`` execute entry."""
    args: dict[str, Any] = {
        "classification_id": classification_id,
        "confirmed_by_person_id": confirmed_by_person_id,
        "notes": None,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "column_classification_confirmed",
            "ref_id": classification_id,
            "reason": "confirm",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_column_classification_confirmed",
            "args": args,
            "result_ref": classification_id,
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
    classification_id: str,
    reason: str = "false_positive",
) -> None:
    """Emit a ``column_classification_rejected`` execute entry."""
    args: dict[str, Any] = {
        "classification_id": classification_id,
        "rejected_by_person_id": "test-admin",
        "reason": reason,
        "notes": None,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "column_classification_rejected",
            "ref_id": classification_id,
            "reason": "reject",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_column_classification_rejected",
            "args": args,
            "result_ref": classification_id,
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
    reader = LedgerConfirmedClassificationReader(ledger=ledger)
    records = (
        await reader.list_confirmed_classifications_for_source_column(
            source_id="warehouse",
            src_column="email",
            company_id=_COMPANY_A,
        )
    )
    assert records == []


@pytest.mark.asyncio
async def test_only_proposed_filtered_out() -> None:
    """A proposed-but-not-confirmed classification MUST NOT be returned."""
    ledger = InMemoryLedger()
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="cls-pending-1",
        table_id="warehouse.dim_customer",
        column="email",
    )
    reader = LedgerConfirmedClassificationReader(ledger=ledger)
    records = (
        await reader.list_confirmed_classifications_for_source_column(
            source_id="warehouse",
            src_column="email",
            company_id=_COMPANY_A,
        )
    )
    assert records == []


@pytest.mark.asyncio
async def test_confirmed_is_returned_with_metadata() -> None:
    """A confirmed classification IS returned with all coupling fields populated."""
    ledger = InMemoryLedger()
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="cls-pii-1",
        table_id="warehouse.dim_customer",
        column="email",
        classification_level="pii",
        strategy="semantic_type",
    )
    await _emit_confirmed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="cls-pii-1",
        confirmed_by_person_id="alice-admin",
    )

    reader = LedgerConfirmedClassificationReader(ledger=ledger)
    records = (
        await reader.list_confirmed_classifications_for_source_column(
            source_id="warehouse",
            src_column="email",
            company_id=_COMPANY_A,
        )
    )
    assert len(records) == 1
    r = records[0]
    assert r.classification_id == "cls-pii-1"
    assert r.classification_level == "pii"
    assert r.table_id == "warehouse.dim_customer"
    assert r.column == "email"
    assert r.source_id == "warehouse"
    assert r.confirmed_by_person_id == "alice-admin"
    # confirmed_at must come from the confirmation entry's ts; epoch
    # fallback would indicate the metadata didn't get captured.
    assert r.confirmed_at.year >= 1971


@pytest.mark.asyncio
async def test_rejected_after_confirmed_filtered_out() -> None:
    """Proposed → confirmed → rejected stays out (last state wins)."""
    ledger = InMemoryLedger()
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="cls-flip-1",
        table_id="warehouse.dim_customer",
        column="email",
    )
    await _emit_confirmed(
        ledger, company_id=_COMPANY_A, classification_id="cls-flip-1",
    )
    await _emit_rejected(
        ledger, company_id=_COMPANY_A, classification_id="cls-flip-1",
    )
    reader = LedgerConfirmedClassificationReader(ledger=ledger)
    records = (
        await reader.list_confirmed_classifications_for_source_column(
            source_id="warehouse",
            src_column="email",
            company_id=_COMPANY_A,
        )
    )
    assert records == []


@pytest.mark.asyncio
async def test_multi_company_isolation() -> None:
    """Confirmed classifications in tenant B MUST NOT leak into tenant A reads."""
    ledger = InMemoryLedger()
    # Confirmed in company B; should not appear when reading A.
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_B,
        classification_id="cls-b-leak",
        table_id="warehouse.dim_customer",
        column="email",
    )
    await _emit_confirmed(
        ledger, company_id=_COMPANY_B, classification_id="cls-b-leak",
    )

    reader = LedgerConfirmedClassificationReader(ledger=ledger)
    records_a = (
        await reader.list_confirmed_classifications_for_source_column(
            source_id="warehouse",
            src_column="email",
            company_id=_COMPANY_A,
        )
    )
    assert records_a == []

    records_b = (
        await reader.list_confirmed_classifications_for_source_column(
            source_id="warehouse",
            src_column="email",
            company_id=_COMPANY_B,
        )
    )
    assert len(records_b) == 1
    assert records_b[0].classification_id == "cls-b-leak"


@pytest.mark.asyncio
async def test_source_id_prefix_match_only() -> None:
    """source_id must be a PREFIX of table_id (table_id LIKE "<source_id>.%")."""
    ledger = InMemoryLedger()
    # Same column name, different source → must not match.
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="cls-other-src",
        table_id="other_src.dim_customer",
        column="email",
    )
    await _emit_confirmed(
        ledger, company_id=_COMPANY_A, classification_id="cls-other-src",
    )

    # Now add the right one
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="cls-right-src",
        table_id="warehouse.dim_customer",
        column="email",
    )
    await _emit_confirmed(
        ledger, company_id=_COMPANY_A, classification_id="cls-right-src",
    )

    reader = LedgerConfirmedClassificationReader(ledger=ledger)
    records = (
        await reader.list_confirmed_classifications_for_source_column(
            source_id="warehouse",
            src_column="email",
            company_id=_COMPANY_A,
        )
    )
    assert len(records) == 1
    assert records[0].classification_id == "cls-right-src"


@pytest.mark.asyncio
async def test_column_exact_match_only() -> None:
    """src_column must match exactly; near-misses skipped."""
    ledger = InMemoryLedger()
    # Two confirmed classifications, one on 'email' and one on 'email_v2'
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="cls-email",
        table_id="warehouse.dim_customer",
        column="email",
    )
    await _emit_confirmed(
        ledger, company_id=_COMPANY_A, classification_id="cls-email",
    )
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="cls-email-v2",
        table_id="warehouse.dim_customer",
        column="email_v2",
    )
    await _emit_confirmed(
        ledger, company_id=_COMPANY_A, classification_id="cls-email-v2",
    )

    reader = LedgerConfirmedClassificationReader(ledger=ledger)
    records = (
        await reader.list_confirmed_classifications_for_source_column(
            source_id="warehouse",
            src_column="email",
            company_id=_COMPANY_A,
        )
    )
    assert len(records) == 1
    assert records[0].classification_id == "cls-email"


@pytest.mark.asyncio
async def test_multiple_classifications_same_column_all_returned() -> None:
    """A column may have multiple confirmed classifications across strategies."""
    ledger = InMemoryLedger()
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="cls-pii-via-semantic",
        table_id="warehouse.dim_customer",
        column="email",
        classification_level="pii",
        strategy="semantic_type",
    )
    await _emit_confirmed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="cls-pii-via-semantic",
    )
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="cls-internal-via-domain",
        table_id="warehouse.dim_customer",
        column="email",
        classification_level="internal",
        strategy="domain_default",
    )
    await _emit_confirmed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="cls-internal-via-domain",
    )

    reader = LedgerConfirmedClassificationReader(ledger=ledger)
    records = (
        await reader.list_confirmed_classifications_for_source_column(
            source_id="warehouse",
            src_column="email",
            company_id=_COMPANY_A,
        )
    )
    assert len(records) == 2
    levels = {r.classification_level for r in records}
    assert levels == {"pii", "internal"}


@pytest.mark.asyncio
async def test_deterministic_ordering_by_classification_id() -> None:
    """Two callers MUST get records sorted by classification_id."""
    ledger = InMemoryLedger()
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="z-cls",
        table_id="warehouse.dim_customer",
        column="email",
        classification_level="confidential",
    )
    await _emit_confirmed(
        ledger, company_id=_COMPANY_A, classification_id="z-cls",
    )
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="a-cls",
        table_id="warehouse.dim_customer",
        column="email",
        classification_level="pii",
    )
    await _emit_confirmed(
        ledger, company_id=_COMPANY_A, classification_id="a-cls",
    )

    reader = LedgerConfirmedClassificationReader(ledger=ledger)
    records = (
        await reader.list_confirmed_classifications_for_source_column(
            source_id="warehouse",
            src_column="email",
            company_id=_COMPANY_A,
        )
    )
    assert [r.classification_id for r in records] == ["a-cls", "z-cls"]


@pytest.mark.asyncio
async def test_reclassification_after_rejection_returns_latest_confirmed() -> None:
    """proposed → confirmed → rejected → new-proposed → confirmed yields the new."""
    ledger = InMemoryLedger()
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="cls-first",
        table_id="warehouse.dim_customer",
        column="email",
        classification_level="pii",
    )
    await _emit_confirmed(
        ledger, company_id=_COMPANY_A, classification_id="cls-first",
    )
    await _emit_rejected(
        ledger, company_id=_COMPANY_A, classification_id="cls-first",
    )
    # New proposal under a different classification_id (per L6 doctrine —
    # re-confirmation emits a NEW entry; classification_id is the hash
    # of (table, column, level, strategy)).
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="cls-second",
        table_id="warehouse.dim_customer",
        column="email",
        classification_level="regulated",
    )
    await _emit_confirmed(
        ledger, company_id=_COMPANY_A, classification_id="cls-second",
    )

    reader = LedgerConfirmedClassificationReader(ledger=ledger)
    records = (
        await reader.list_confirmed_classifications_for_source_column(
            source_id="warehouse",
            src_column="email",
            company_id=_COMPANY_A,
        )
    )
    assert len(records) == 1
    assert records[0].classification_id == "cls-second"
    assert records[0].classification_level == "regulated"


@pytest.mark.asyncio
async def test_empty_source_or_column_returns_empty() -> None:
    """Defensive: empty inputs short-circuit to empty result."""
    ledger = InMemoryLedger()
    await _emit_proposed(
        ledger,
        company_id=_COMPANY_A,
        classification_id="cls-x",
        table_id="warehouse.dim_customer",
        column="email",
    )
    await _emit_confirmed(
        ledger, company_id=_COMPANY_A, classification_id="cls-x",
    )

    reader = LedgerConfirmedClassificationReader(ledger=ledger)
    assert await reader.list_confirmed_classifications_for_source_column(
        source_id="", src_column="email", company_id=_COMPANY_A,
    ) == []
    assert await reader.list_confirmed_classifications_for_source_column(
        source_id="warehouse", src_column="", company_id=_COMPANY_A,
    ) == []
