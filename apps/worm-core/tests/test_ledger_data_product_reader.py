"""Tests for ``LedgerDataProductReader`` — v1.2 Task 2 Item #3.

The reader walks raw ledger entries with
``payload->>'tool' IN (emit_data_product_proposed,
emit_data_product_generated, emit_data_product_archived)`` and folds
them into one row per ``data_product_id``. Mirrors the
projection-builder semantics in
``packages/ledger/src/wormbase_ledger/projections/builder.py`` lines
827-896.

These tests drive the reader with ``InMemoryLedger`` to stay
deployment-free; the same code path runs against Postgres in
production because the ledger surface is identical (both return
entries ordered seq-ASC with the same row shape).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from wormbase_core.agent_gateway_readers import LedgerDataProductReader
from wormbase_ledger import InMemoryLedger

# Stable tenant id so the test suite is reproducible.
TEST_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000abc")


def _verify_pass(_e: dict[str, Any]) -> dict[str, Any]:
    return {"checks": [], "passed": True}


def _resolve_keep(_v: dict[str, Any]) -> dict[str, Any]:
    return {"outcome": "keep", "rationale": "ok"}


async def _emit_proposed(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    data_product_id: UUID,
    name: str,
    kind: str = "report",
    requested_by_person_id: UUID | None = None,
    domain_id: UUID | None = None,
) -> None:
    args: dict[str, Any] = {
        "data_product_id": str(data_product_id),
        "name": name,
        "kind": kind,
        "requested_by_person_id": str(requested_by_person_id or uuid4()),
        "sources_required": [],
        "parameters": {},
    }
    if domain_id is not None:
        args["domain_id"] = str(domain_id)

    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "data_product_proposed",
            "ref_id": str(data_product_id),
            "reason": f"propose data product {name!r}",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_data_product_proposed",
            "args": args,
            "result_ref": str(data_product_id),
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_generated(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    data_product_id: UUID,
    contents_uri: str = "file:///tmp/dp.html",
    content_hash: str = "sha256:abc",
    kind: str = "report",
) -> None:
    args: dict[str, Any] = {
        "data_product_id": str(data_product_id),
        "contents_uri": contents_uri,
        "content_hash": content_hash,
        "kind": kind,
        "source_hashes": [],
        "generated_by": "worm",
        "duration_ms": 12,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "data_product_generated",
            "ref_id": str(data_product_id),
            "reason": f"generate data product {data_product_id}",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_data_product_generated",
            "args": args,
            "result_ref": str(data_product_id),
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_archived(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    data_product_id: UUID,
) -> None:
    args: dict[str, Any] = {
        "data_product_id": str(data_product_id),
        "archived_by_person_id": str(uuid4()),
        "reason": "test archive",
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "data_product_archived",
            "ref_id": str(data_product_id),
            "reason": "archive data product",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_data_product_archived",
            "args": args,
            "result_ref": str(data_product_id),
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


@pytest.mark.asyncio
async def test_list_data_products_returns_proposed_rows() -> None:
    """An emit_data_product_proposed entry produces a row with status='proposed'."""
    ledger = InMemoryLedger()
    dp_id = uuid4()
    await _emit_proposed(
        ledger,
        company_id=TEST_COMPANY_ID,
        data_product_id=dp_id,
        name="Q1 Revenue Report",
    )

    reader = LedgerDataProductReader(ledger=ledger)
    rows = await reader.list_data_products(
        company_id=TEST_COMPANY_ID, domain_id=None, status=None, limit=50,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["data_product_id"] == str(dp_id)
    assert row["name"] == "Q1 Revenue Report"
    assert row["status"] == "proposed"
    assert row["generated_at"] is None
    assert row["content_hash"] is None
    assert row["entry_hash"]


@pytest.mark.asyncio
async def test_proposed_then_generated_folds_to_generated_status() -> None:
    """The reader folds the lifecycle sequence into the latest state."""
    ledger = InMemoryLedger()
    dp_id = uuid4()
    await _emit_proposed(
        ledger,
        company_id=TEST_COMPANY_ID,
        data_product_id=dp_id,
        name="Folded DP",
    )
    await _emit_generated(
        ledger,
        company_id=TEST_COMPANY_ID,
        data_product_id=dp_id,
        contents_uri="file:///tmp/folded.html",
        content_hash="sha256:zzz",
    )

    reader = LedgerDataProductReader(ledger=ledger)
    row = await reader.get_data_product(
        company_id=TEST_COMPANY_ID,
        data_product_id=str(dp_id),
    )
    assert row is not None
    assert row["status"] == "generated"
    assert row["content_hash"] == "sha256:zzz"
    assert row["contents_uri"] == "file:///tmp/folded.html"
    assert row["generated_at"] is not None


@pytest.mark.asyncio
async def test_archived_overrides_generated_status() -> None:
    """emit_data_product_archived flips status to 'archived'."""
    ledger = InMemoryLedger()
    dp_id = uuid4()
    await _emit_proposed(
        ledger, company_id=TEST_COMPANY_ID,
        data_product_id=dp_id, name="Doomed DP",
    )
    await _emit_generated(
        ledger, company_id=TEST_COMPANY_ID, data_product_id=dp_id,
    )
    await _emit_archived(
        ledger, company_id=TEST_COMPANY_ID, data_product_id=dp_id,
    )

    reader = LedgerDataProductReader(ledger=ledger)
    rows = await reader.list_data_products(
        company_id=TEST_COMPANY_ID, domain_id=None, status=None, limit=50,
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "archived"


@pytest.mark.asyncio
async def test_list_data_products_filters_by_domain_id() -> None:
    """``domain_id`` filter narrows results; untagged rows excluded."""
    ledger = InMemoryLedger()
    finance_domain = uuid4()
    finance_dp = uuid4()
    untagged_dp = uuid4()

    await _emit_proposed(
        ledger, company_id=TEST_COMPANY_ID,
        data_product_id=finance_dp,
        name="Finance dashboard",
        domain_id=finance_domain,
    )
    await _emit_proposed(
        ledger, company_id=TEST_COMPANY_ID,
        data_product_id=untagged_dp,
        name="Untagged side analysis",
    )

    reader = LedgerDataProductReader(ledger=ledger)
    finance_only = await reader.list_data_products(
        company_id=TEST_COMPANY_ID,
        domain_id=str(finance_domain),
        status=None,
        limit=50,
    )
    assert len(finance_only) == 1
    assert finance_only[0]["data_product_id"] == str(finance_dp)


@pytest.mark.asyncio
async def test_list_data_products_filters_by_status() -> None:
    """``status`` filter narrows to rows with that status."""
    ledger = InMemoryLedger()
    proposed_dp = uuid4()
    generated_dp = uuid4()

    await _emit_proposed(
        ledger, company_id=TEST_COMPANY_ID,
        data_product_id=proposed_dp, name="Proposed only",
    )
    await _emit_proposed(
        ledger, company_id=TEST_COMPANY_ID,
        data_product_id=generated_dp, name="Generated DP",
    )
    await _emit_generated(
        ledger, company_id=TEST_COMPANY_ID,
        data_product_id=generated_dp,
    )

    reader = LedgerDataProductReader(ledger=ledger)
    proposed_only = await reader.list_data_products(
        company_id=TEST_COMPANY_ID, domain_id=None,
        status="proposed", limit=50,
    )
    assert len(proposed_only) == 1
    assert proposed_only[0]["data_product_id"] == str(proposed_dp)


@pytest.mark.asyncio
async def test_list_data_products_respects_limit() -> None:
    ledger = InMemoryLedger()
    for i in range(5):
        await _emit_proposed(
            ledger, company_id=TEST_COMPANY_ID,
            data_product_id=uuid4(), name=f"DP #{i}",
        )

    reader = LedgerDataProductReader(ledger=ledger)
    rows = await reader.list_data_products(
        company_id=TEST_COMPANY_ID, domain_id=None, status=None, limit=3,
    )
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_list_data_products_is_tenant_scoped() -> None:
    """Rows from company A must not leak into company B's results."""
    ledger = InMemoryLedger()
    other_company = UUID("00000000-0000-0000-0000-000000000def")
    our_dp = uuid4()
    other_dp = uuid4()

    await _emit_proposed(
        ledger, company_id=TEST_COMPANY_ID,
        data_product_id=our_dp, name="ours",
    )
    await _emit_proposed(
        ledger, company_id=other_company,
        data_product_id=other_dp, name="theirs",
    )

    reader = LedgerDataProductReader(ledger=ledger)
    ours = await reader.list_data_products(
        company_id=TEST_COMPANY_ID, domain_id=None, status=None, limit=50,
    )
    assert len(ours) == 1
    assert ours[0]["data_product_id"] == str(our_dp)

    theirs = await reader.list_data_products(
        company_id=other_company, domain_id=None, status=None, limit=50,
    )
    assert len(theirs) == 1
    assert theirs[0]["data_product_id"] == str(other_dp)


@pytest.mark.asyncio
async def test_get_data_product_returns_none_for_unknown() -> None:
    ledger = InMemoryLedger()
    reader = LedgerDataProductReader(ledger=ledger)
    row = await reader.get_data_product(
        company_id=TEST_COMPANY_ID,
        data_product_id=str(uuid4()),
    )
    assert row is None
