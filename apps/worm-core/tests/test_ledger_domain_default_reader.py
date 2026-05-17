"""L6 Sub-wave C — LedgerDomainDefaultReader governance-read tests.

Pins the consumer-owned domain-default reader impl: L6's
DomainDefaultClassificationStrategy reads existing onboarding
governance state. Verifies:

  * Empty ledger → None.
  * No domain_pack_selected → None (graceful no-op).
  * Pack selected but no domains registered → None.
  * Pack selected + domains with non-canonical defaults → None.
  * Pack selected + valid domain → (level, domain_id) tuple,
    deterministically picking the alphabetically-first domain_id.
  * Tenant isolation via company_id.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.column_classification_domain_reader import (
    LedgerDomainDefaultReader,
)

_COMPANY_A = UUID("00000000-0000-0000-0000-0000000d0030")
_COMPANY_B = UUID("00000000-0000-0000-0000-0000000d0031")


async def _emit_domain_pack_selected(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    pack_id: str = "saas",
) -> None:
    """Emit a ``domain_pack_selected`` execute entry."""
    args: dict[str, Any] = {
        "pack_id": pack_id,
        "pack_version": "1.0",
        "selected_by_person_id": "test-admin",
        "notes": None,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "domain_pack_selected",
            "ref_id": pack_id,
            "reason": "seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_domain_pack_selected",
            "args": args,
            "result_ref": pack_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )


async def _emit_domain_registered(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    domain_id: str,
    default_classification: str,
) -> None:
    """Emit an ``emit_domain_registered`` execute entry."""
    args: dict[str, Any] = {
        "id": domain_id,
        "name": f"domain {domain_id}",
        "default_classification": default_classification,
        "description": None,
        "owner_person_id": None,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "memory_written",
            "ref_id": domain_id,
            "reason": "seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_domain_registered",
            "args": args,
            "result_ref": domain_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )


@pytest.mark.asyncio
async def test_empty_ledger_returns_none() -> None:
    """Empty ledger → no pack selected → None."""
    ledger = InMemoryLedger()
    reader = LedgerDomainDefaultReader(ledger=ledger)
    result = await reader.get_classification_default_for_table(
        table_id="warehouse.dim_customer",
        company_id=_COMPANY_A,
    )
    assert result is None


@pytest.mark.asyncio
async def test_no_pack_selected_returns_none() -> None:
    """Domains registered but no pack selection → None (graceful no-op)."""
    ledger = InMemoryLedger()
    await _emit_domain_registered(
        ledger,
        company_id=_COMPANY_A,
        domain_id="domain_finance",
        default_classification="confidential",
    )
    reader = LedgerDomainDefaultReader(ledger=ledger)
    result = await reader.get_classification_default_for_table(
        table_id="warehouse.dim_customer",
        company_id=_COMPANY_A,
    )
    assert result is None


@pytest.mark.asyncio
async def test_pack_selected_no_domains_returns_none() -> None:
    """Pack selected but no domains registered → None."""
    ledger = InMemoryLedger()
    await _emit_domain_pack_selected(ledger, company_id=_COMPANY_A)
    reader = LedgerDomainDefaultReader(ledger=ledger)
    result = await reader.get_classification_default_for_table(
        table_id="warehouse.dim_customer",
        company_id=_COMPANY_A,
    )
    assert result is None


@pytest.mark.asyncio
async def test_non_canonical_classification_skipped() -> None:
    """Domain with a non-5-level default is skipped; no other match → None."""
    ledger = InMemoryLedger()
    await _emit_domain_pack_selected(ledger, company_id=_COMPANY_A)
    await _emit_domain_registered(
        ledger,
        company_id=_COMPANY_A,
        domain_id="domain_legacy",
        default_classification="operational",  # drift — not in 5-value enum
    )
    reader = LedgerDomainDefaultReader(ledger=ledger)
    result = await reader.get_classification_default_for_table(
        table_id="warehouse.dim_customer",
        company_id=_COMPANY_A,
    )
    assert result is None


@pytest.mark.asyncio
async def test_returns_first_domain_alphabetically() -> None:
    """Multiple valid domains → alphabetically-first domain_id wins (replay-stable)."""
    ledger = InMemoryLedger()
    await _emit_domain_pack_selected(ledger, company_id=_COMPANY_A)
    # Insert in non-alphabetical order so we know the reader sorts:
    await _emit_domain_registered(
        ledger,
        company_id=_COMPANY_A,
        domain_id="domain_zeta",
        default_classification="public",
    )
    await _emit_domain_registered(
        ledger,
        company_id=_COMPANY_A,
        domain_id="domain_alpha",
        default_classification="confidential",
    )
    await _emit_domain_registered(
        ledger,
        company_id=_COMPANY_A,
        domain_id="domain_mid",
        default_classification="internal",
    )

    reader = LedgerDomainDefaultReader(ledger=ledger)
    result = await reader.get_classification_default_for_table(
        table_id="warehouse.dim_customer",
        company_id=_COMPANY_A,
    )
    assert result is not None
    level, domain_id = result
    assert domain_id == "domain_alpha"
    assert level == "confidential"


@pytest.mark.asyncio
async def test_tenant_isolation() -> None:
    """Tenant A's domain pack state is NOT visible to tenant B."""
    ledger = InMemoryLedger()
    await _emit_domain_pack_selected(ledger, company_id=_COMPANY_A)
    await _emit_domain_registered(
        ledger,
        company_id=_COMPANY_A,
        domain_id="domain_finance",
        default_classification="regulated",
    )

    reader = LedgerDomainDefaultReader(ledger=ledger)
    result_b = await reader.get_classification_default_for_table(
        table_id="warehouse.dim_customer",
        company_id=_COMPANY_B,
    )
    assert result_b is None

    result_a = await reader.get_classification_default_for_table(
        table_id="warehouse.dim_customer",
        company_id=_COMPANY_A,
    )
    assert result_a == ("regulated", "domain_finance")


@pytest.mark.asyncio
async def test_empty_table_id_returns_none() -> None:
    """Empty table_id always returns None (defensive guard)."""
    ledger = InMemoryLedger()
    await _emit_domain_pack_selected(ledger, company_id=_COMPANY_A)
    await _emit_domain_registered(
        ledger,
        company_id=_COMPANY_A,
        domain_id="domain_finance",
        default_classification="regulated",
    )
    reader = LedgerDomainDefaultReader(ledger=ledger)
    result = await reader.get_classification_default_for_table(
        table_id="",
        company_id=_COMPANY_A,
    )
    assert result is None
