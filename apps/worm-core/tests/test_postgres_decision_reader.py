"""Tests for ``LedgerDecisionReader`` (a.k.a. ``PostgresDecisionReader``) —
v1.1 Task 5 (Hole #3 production wire-up for the ``decisions.*`` MCP tools).

Mirrors ``test_postgres_process_map_reader.py`` for the decision family.

The reader queries raw ledger entries matching ``payload->>'tool' ==
'emit_decision_recorded'`` (mirrors the ``decision-chain.ts`` pattern
in the dashboard for /decisions). Unlike process maps, decisions are
not de-duped — each emit is a distinct artifact.

The implementation accepts any object exposing the ``Ledger.fetch``
surface — ``Ledger`` (Postgres-backed) or ``InMemoryLedger``. These
tests drive it with ``InMemoryLedger`` to keep the suite deployment-
free; the same code path runs against Postgres in production because
the ledger surface is identical (both return entries ordered seq-ASC
with the same row shape).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.agent_gateway_readers import (
    LedgerDecisionReader,
    PostgresDecisionReader,
)

# Stable tenant id so the test suite is reproducible.
TEST_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000abc")


# ---------------------------------------------------------------------------
# Helper — drive an ``emit_decision_recorded`` PEVR cycle into the ledger.
# Inline rather than calling ``write_actions.record_decision`` so the test
# is decoupled from the orchestrator's payload class; the reader treats
# the raw ledger row as the canonical surface — that's the whole point.
# ---------------------------------------------------------------------------


def _verify_pass(_e: dict[str, Any]) -> dict[str, Any]:
    return {"checks": [], "passed": True}


def _resolve_keep(_v: dict[str, Any]) -> dict[str, Any]:
    return {"outcome": "keep", "rationale": "ok"}


async def _emit_decision(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    decision_id: UUID,
    decision_text: str,
    channel_id: str = "C-CHAN",
    decided_by_persons: list[UUID] | None = None,
    evidence_message_ids: list[str] | None = None,
    confidence: float = 0.93,
    domain_id: UUID | None = None,
    decision_at: str | None = None,
) -> None:
    args: dict[str, Any] = {
        "decision_id": str(decision_id),
        "decision_text": decision_text,
        "decision_at": decision_at or "2026-05-11T12:00:00+00:00",
        "channel_id": channel_id,
        "decided_by_persons": [str(p) for p in (decided_by_persons or [])],
        "evidence_message_ids": list(evidence_message_ids or []),
        "confidence": confidence,
    }
    if domain_id is not None:
        args["domain_id"] = str(domain_id)

    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "decision_recorded",
            "ref_id": str(decision_id),
            "reason": f"record decision {decision_text[:32]!r}",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_decision_recorded",
            "args": args,
            "result_ref": str(decision_id),
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


# ---------------------------------------------------------------------------
# list_decisions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_decisions_returns_recent_first() -> None:
    """Three decisions seeded; reader returns them newest-first.

    Append order is insert order, so the *most recently emitted* decision
    is at the end of the ledger. The reader reverses the fetch result to
    surface newest-first, mirroring the dashboard's ``ORDER BY ts DESC``.
    """
    ledger = InMemoryLedger()
    d1, d2, d3 = uuid4(), uuid4(), uuid4()
    await _emit_decision(
        ledger, company_id=TEST_COMPANY_ID, decision_id=d1,
        decision_text="Ship Q1 revenue dashboard",
    )
    await _emit_decision(
        ledger, company_id=TEST_COMPANY_ID, decision_id=d2,
        decision_text="Adopt OKR cadence",
    )
    await _emit_decision(
        ledger, company_id=TEST_COMPANY_ID, decision_id=d3,
        decision_text="Defer churn report v2",
    )

    reader = LedgerDecisionReader(ledger=ledger)
    rows = await reader.list_decisions(
        company_id=TEST_COMPANY_ID, domain_id=None, limit=50,
    )

    assert len(rows) == 3
    # Newest-first
    assert rows[0]["decision_id"] == str(d3)
    assert rows[1]["decision_id"] == str(d2)
    assert rows[2]["decision_id"] == str(d1)
    # entry_hash threaded through (dashboard audit chip)
    assert all(r.get("entry_hash") for r in rows)


@pytest.mark.asyncio
async def test_list_decisions_filters_by_domain() -> None:
    """``domain_id`` filter narrows the result set; un-tagged rows excluded."""
    ledger = InMemoryLedger()
    finance_domain = uuid4()
    product_domain = uuid4()

    finance_decision = uuid4()
    product_decision = uuid4()
    untagged_decision = uuid4()

    await _emit_decision(
        ledger, company_id=TEST_COMPANY_ID,
        decision_id=finance_decision,
        decision_text="Cut finance forecast scope",
        domain_id=finance_domain,
    )
    await _emit_decision(
        ledger, company_id=TEST_COMPANY_ID,
        decision_id=product_decision,
        decision_text="Land waitlist by EOQ",
        domain_id=product_domain,
    )
    await _emit_decision(
        ledger, company_id=TEST_COMPANY_ID,
        decision_id=untagged_decision,
        decision_text="Untagged side decision",
    )

    reader = LedgerDecisionReader(ledger=ledger)
    finance_only = await reader.list_decisions(
        company_id=TEST_COMPANY_ID,
        domain_id=str(finance_domain),
        limit=50,
    )
    assert len(finance_only) == 1
    assert finance_only[0]["decision_id"] == str(finance_decision)
    assert finance_only[0]["domain_id"] == str(finance_domain)


@pytest.mark.asyncio
async def test_list_decisions_respects_limit() -> None:
    ledger = InMemoryLedger()
    for i in range(5):
        await _emit_decision(
            ledger, company_id=TEST_COMPANY_ID,
            decision_id=uuid4(),
            decision_text=f"Decision #{i}",
        )

    reader = LedgerDecisionReader(ledger=ledger)
    rows = await reader.list_decisions(
        company_id=TEST_COMPANY_ID, domain_id=None, limit=3,
    )
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_list_decisions_is_tenant_scoped() -> None:
    """Decisions for company A must not leak into company B's results."""
    ledger = InMemoryLedger()
    other_company = UUID("00000000-0000-0000-0000-000000000def")
    our_decision = uuid4()
    other_decision = uuid4()

    await _emit_decision(
        ledger, company_id=TEST_COMPANY_ID,
        decision_id=our_decision,
        decision_text="Our decision",
    )
    await _emit_decision(
        ledger, company_id=other_company,
        decision_id=other_decision,
        decision_text="Other-tenant decision",
    )

    reader = LedgerDecisionReader(ledger=ledger)
    ours = await reader.list_decisions(
        company_id=TEST_COMPANY_ID, domain_id=None, limit=50,
    )
    assert {r["decision_id"] for r in ours} == {str(our_decision)}


@pytest.mark.asyncio
async def test_list_decisions_skips_non_decision_entries() -> None:
    """Non-decision execute entries must be ignored by the reader."""
    ledger = InMemoryLedger()
    target_id = uuid4()
    await _emit_decision(
        ledger, company_id=TEST_COMPANY_ID,
        decision_id=target_id,
        decision_text="A real decision",
    )
    # Drive a non-decision execute entry through the ledger.
    await ledger.write(
        company_id=TEST_COMPANY_ID,
        propose={
            "target_kind": "source_proposed",
            "ref_id": str(uuid4()),
            "reason": "side",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_proposed",
            "args": {"source_id": str(uuid4()), "source_kind": "file",
                     "uri": "file:///tmp/x.csv",
                     "added_via_flow": "drop_and_profile"},
            "result_ref": "ok",
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )

    reader = LedgerDecisionReader(ledger=ledger)
    rows = await reader.list_decisions(
        company_id=TEST_COMPANY_ID, domain_id=None, limit=50,
    )
    assert len(rows) == 1
    assert rows[0]["decision_id"] == str(target_id)


# ---------------------------------------------------------------------------
# get_decision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_decision_returns_existing() -> None:
    ledger = InMemoryLedger()
    target_id = uuid4()
    await _emit_decision(
        ledger, company_id=TEST_COMPANY_ID,
        decision_id=target_id,
        decision_text="The findable decision",
        channel_id="C-TARGET",
        confidence=0.81,
    )

    reader = LedgerDecisionReader(ledger=ledger)
    row = await reader.get_decision(
        company_id=TEST_COMPANY_ID, decision_id=str(target_id),
    )
    assert row is not None
    assert row["decision_id"] == str(target_id)
    assert row["decision_text"] == "The findable decision"
    assert row["channel_id"] == "C-TARGET"
    assert row["confidence"] == pytest.approx(0.81)


@pytest.mark.asyncio
async def test_get_decision_returns_none_for_missing() -> None:
    ledger = InMemoryLedger()
    reader = LedgerDecisionReader(ledger=ledger)
    row = await reader.get_decision(
        company_id=TEST_COMPANY_ID, decision_id=str(uuid4()),
    )
    assert row is None


# ---------------------------------------------------------------------------
# search_decisions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_substring_match_case_insensitive() -> None:
    ledger = InMemoryLedger()
    revenue_id = uuid4()
    other_id = uuid4()
    await _emit_decision(
        ledger, company_id=TEST_COMPANY_ID,
        decision_id=revenue_id,
        decision_text="Forecast Q3 revenue by region",
    )
    await _emit_decision(
        ledger, company_id=TEST_COMPANY_ID,
        decision_id=other_id,
        decision_text="Ship onboarding refresh",
    )

    reader = LedgerDecisionReader(ledger=ledger)
    matches = await reader.search_decisions(
        company_id=TEST_COMPANY_ID, nl_question="q3 revenue", limit=10,
    )
    assert len(matches) == 1
    assert matches[0]["decision_id"] == str(revenue_id)


@pytest.mark.asyncio
async def test_search_respects_limit() -> None:
    ledger = InMemoryLedger()
    for i in range(5):
        await _emit_decision(
            ledger, company_id=TEST_COMPANY_ID,
            decision_id=uuid4(),
            decision_text=f"adopt change #{i}",
        )

    reader = LedgerDecisionReader(ledger=ledger)
    matches = await reader.search_decisions(
        company_id=TEST_COMPANY_ID, nl_question="adopt", limit=2,
    )
    assert len(matches) == 2


@pytest.mark.asyncio
async def test_search_returns_empty_on_no_match() -> None:
    ledger = InMemoryLedger()
    await _emit_decision(
        ledger, company_id=TEST_COMPANY_ID,
        decision_id=uuid4(),
        decision_text="Adopt monorepo",
    )
    reader = LedgerDecisionReader(ledger=ledger)
    matches = await reader.search_decisions(
        company_id=TEST_COMPANY_ID,
        nl_question="nonexistent topic",
        limit=10,
    )
    assert matches == []


@pytest.mark.asyncio
async def test_search_empty_question_returns_empty() -> None:
    """An empty / whitespace nl_question short-circuits to ``[]`` rather
    than matching every decision (a substring containment against an empty
    string would otherwise be vacuously true)."""
    ledger = InMemoryLedger()
    await _emit_decision(
        ledger, company_id=TEST_COMPANY_ID,
        decision_id=uuid4(),
        decision_text="A real decision",
    )
    reader = LedgerDecisionReader(ledger=ledger)
    assert await reader.search_decisions(
        company_id=TEST_COMPANY_ID, nl_question="", limit=10,
    ) == []


# ---------------------------------------------------------------------------
# Empty-ledger path (honest empty state, never a stub fallback)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_empty_when_no_decisions() -> None:
    """Empty ledger → all three methods return honest empty / None."""
    ledger = InMemoryLedger()
    reader = LedgerDecisionReader(ledger=ledger)
    assert await reader.list_decisions(
        company_id=TEST_COMPANY_ID, domain_id=None, limit=50,
    ) == []
    assert await reader.get_decision(
        company_id=TEST_COMPANY_ID, decision_id=str(uuid4()),
    ) is None
    assert await reader.search_decisions(
        company_id=TEST_COMPANY_ID, nl_question="anything", limit=10,
    ) == []


# ---------------------------------------------------------------------------
# Postgres alias — ensure the brief's vocabulary works at the import site.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_alias_is_same_class() -> None:
    """``PostgresDecisionReader`` is an alias for ``LedgerDecisionReader``.

    The Postgres-flavored name is preserved for the v1.1 plan + production
    wiring sites that want the storage-flavored hint. Both names construct
    the same reader and satisfy the gateway's ``DecisionReader`` Protocol.
    """
    assert PostgresDecisionReader is LedgerDecisionReader

    ledger = InMemoryLedger()
    did = uuid4()
    await _emit_decision(
        ledger, company_id=TEST_COMPANY_ID,
        decision_id=did,
        decision_text="alias smoke test",
    )

    reader = PostgresDecisionReader(ledger=ledger)
    rows = await reader.list_decisions(
        company_id=TEST_COMPANY_ID, domain_id=None, limit=10,
    )
    assert len(rows) == 1
    assert rows[0]["decision_id"] == str(did)
