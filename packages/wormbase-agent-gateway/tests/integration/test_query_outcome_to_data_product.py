"""W3.2 Hole #8 — QueryOutcomeToDataProductReactivity end-to-end.

Verifies the §2 Stage 8 + Seam #4 pin from the journey revision:

  * High-quality outcome (used=True AND useful=True AND
    quality_score >= 0.9) → exactly one ``data_product_proposed``
    PEVR cycle.
  * Below quality threshold → no promotion.
  * used=False → no promotion (the outcome was discarded).
  * useful=False → no promotion (the outcome was used but wrong).
  * Promoted entry chains back to the originating ``agent_query`` via
    ``parameters.source_audit_trail_id``.
  * Per-outcome idempotency: re-dispatching on the same outcome does
    NOT emit a duplicate ``data_product_proposed`` row.

Uses the real ``ReactivityRegistry`` + ``ReactivityRunner`` +
``InMemoryLedger`` so this is a true integration test — no mocks.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.registry import ReactivityRegistry
from wormbase_reactivities.runner import ReactivityRunner

from wormbase_agent_gateway.reactivities import (
    QueryOutcomeToDataProductReactivity,
    make_agent_gateway_reactivities,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000abc")


async def _write_outcome(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    nl_question: str,
    quality_score: str = "0.95",
    used: bool = True,
    useful: bool = True,
    domain_id: str | None = None,
    agent_query_id: str | None = None,
) -> dict:
    """Drive the canonical-PEVR ledger.write that
    ``lake.query.record_outcome`` emits (W2 Task 7 + W3 Task 0).
    Returns the execute entry as a dict.
    """
    aqi = agent_query_id or str(uuid4())
    spec: dict = {"metric": "revenue_q3", "filter": {"region": "EMEA"}}
    if domain_id is not None:
        spec["domain_id"] = domain_id
    outcome_dict: dict = {
        "agent_query_id": aqi,
        "nl_question": nl_question,
        "final_query_spec": spec,
        "result_summary": {"row_count": 1},
        "used": used,
        "useful": useful,
        "user_correction": None,
        "quality_score": quality_score,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "query_outcome_recorded",
            "ref_id": aqi,
            "reason": f"test outcome aqi={aqi}",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_query_outcome_recorded",
            "args": outcome_dict,
            "result_ref": aqi,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "outcome_recorded", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "outcome_recorded",
        },
        quadrant="active_deterministic",
    )
    rows = await ledger.fetch(company_id)
    executes = [
        r for r in rows
        if r["kind"] == "execute"
        and (r["payload"] or {}).get("tool") == "emit_query_outcome_recorded"
        and ((r["payload"] or {}).get("args") or {}).get("agent_query_id")
            == aqi
    ]
    return executes[-1]


def _fetch_data_product_proposeds(rows: list[dict]) -> list[dict]:
    """Return the execute rows for ``emit_data_product_proposed`` entries."""
    return [
        r for r in rows
        if r["kind"] == "execute"
        and (r["payload"] or {}).get("tool") == "emit_data_product_proposed"
    ]


@pytest.mark.asyncio
async def test_high_quality_outcome_promotes_to_data_product() -> None:
    """used=True + useful=True + quality_score>=0.9 → one
    data_product_proposed entry, chained via source_audit_trail_id."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    for r in make_agent_gateway_reactivities():
        registry.register(r)
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="What was Q3 EMEA revenue?",
        quality_score="0.95",
        agent_query_id="audit-trail-xyz",
    )

    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_data_product_proposeds(rows)
    assert len(proposed) == 1, (
        f"expected exactly 1 data_product_proposed, got "
        f"{len(proposed)}: {[p['payload'] for p in proposed]}"
    )
    args = (proposed[0]["payload"] or {}).get("args") or {}
    parameters = args.get("parameters") or {}
    assert parameters.get("source_audit_trail_id") == "audit-trail-xyz"
    assert parameters.get("proposed_by") == "agent_gateway.compounding_loop"
    assert parameters.get("status") == "proposed"
    # Description carries the NL question — pin one substring.
    desc_carrier = parameters.get("nl_question") or ""
    assert "Q3 EMEA revenue" in desc_carrier
    assert args.get("kind") == "table"


@pytest.mark.asyncio
async def test_low_quality_outcome_does_not_promote() -> None:
    """quality_score=0.5 → no promotion."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    for r in make_agent_gateway_reactivities():
        registry.register(r)
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="What was Q3 EMEA revenue?",
        quality_score="0.5",
    )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_data_product_proposeds(rows) == [], (
        "quality_score < 0.9 must not promote to data_product_proposed"
    )


@pytest.mark.asyncio
async def test_unused_outcome_does_not_promote() -> None:
    """used=False → no promotion (outcome was discarded by the agent)."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    for r in make_agent_gateway_reactivities():
        registry.register(r)
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="What was Q3 EMEA revenue?",
        quality_score="0.99",
        used=False,
        useful=True,
    )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_data_product_proposeds(rows) == [], (
        "used=False must not promote even at high quality_score"
    )


@pytest.mark.asyncio
async def test_not_useful_outcome_does_not_promote() -> None:
    """useful=False → no promotion (the outcome was used but the user
    flagged it as wrong)."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    for r in make_agent_gateway_reactivities():
        registry.register(r)
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="What was Q3 EMEA revenue?",
        quality_score="0.99",
        used=True,
        useful=False,
    )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_data_product_proposeds(rows) == [], (
        "useful=False must not promote even at high quality_score"
    )


@pytest.mark.asyncio
async def test_promoted_entry_chains_to_source_via_audit_trail_id() -> None:
    """The promoted entry's parameters.source_audit_trail_id equals the
    originating agent_query_id for full SOC-2 provenance."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    for r in make_agent_gateway_reactivities():
        registry.register(r)
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    aqi = "audit-trail-chain-pinned-12345"
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="What was Q3 EMEA revenue?",
        quality_score="0.92",
        agent_query_id=aqi,
    )

    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_data_product_proposeds(rows)
    assert len(proposed) == 1
    args = (proposed[0]["payload"] or {}).get("args") or {}
    parameters = args.get("parameters") or {}
    assert parameters.get("source_audit_trail_id") == aqi
    # ``query_spec`` carried through as evidence for the admin reviewer.
    assert parameters.get("query_spec") == {
        "metric": "revenue_q3",
        "filter": {"region": "EMEA"},
    }
    # propose row also carries source_audit_trail_id as a top-level
    # reason hint (visible in /trace).
    proposes = [
        r for r in rows
        if r["kind"] == "propose"
        and (r.get("payload") or {}).get("target_kind") == "data_product_proposed"
        and (r.get("payload") or {}).get("source_audit_trail_id") == aqi
    ]
    assert len(proposes) == 1


@pytest.mark.asyncio
async def test_per_outcome_idempotency_no_duplicate_promotion() -> None:
    """Re-dispatching after the same outcome has been promoted does NOT
    emit a duplicate ``data_product_proposed`` entry."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    for r in make_agent_gateway_reactivities():
        registry.register(r)
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    aqi = "audit-trail-idempotent"
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="What was Q3 EMEA revenue?",
        quality_score="0.95",
        agent_query_id=aqi,
    )
    await runner.run_once()
    first_pass = _fetch_data_product_proposeds(await ledger.fetch(_COMPANY_ID))
    assert len(first_pass) == 1

    # Spin up a fresh registry pointed at the same ledger — bypasses the
    # per-Reactivity NotRecentlyFired debounce so we exercise the
    # ledger-scan idempotency path inside ``fire`` directly.
    fresh_registry = ReactivityRegistry(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    fresh_registry.register(QueryOutcomeToDataProductReactivity())
    fresh_runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=fresh_registry,
        poll_interval_s=0.01,
    )
    await fresh_runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_data_product_proposeds(rows)
    assert len(proposed) == 1, (
        f"per-outcome idempotency failed: expected 1 promotion after "
        f"re-dispatch, got {len(proposed)}"
    )


@pytest.mark.asyncio
async def test_existing_outcome_to_template_reactivity_still_fires() -> None:
    """Regression: the sibling OutcomeToTemplatePromotion Reactivity
    still fires when its 3-outcome-cluster threshold is hit, even with
    the new Reactivity registered alongside it."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    for r in make_agent_gateway_reactivities():
        registry.register(r)
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    # Three same-canonical-NL outcomes in the same domain → triggers the
    # template-promotion clustering rule.
    for _ in range(3):
        await _write_outcome(
            ledger, company_id=_COMPANY_ID,
            nl_question="What was Q3 EMEA revenue?",
            quality_score="0.95",
            domain_id="dom-finance",
        )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    # query_template_promoted entries land as propose rows carrying
    # nl_intent + promoted_from_outcome_ids.
    templates = [
        r for r in rows
        if r["kind"] == "propose"
        and "nl_intent" in (r.get("payload") or {})
        and "promoted_from_outcome_ids" in (r.get("payload") or {})
    ]
    assert len(templates) == 1, (
        f"sibling OutcomeToTemplatePromotion regression: expected 1 "
        f"template, got {len(templates)}"
    )
    # And our new Reactivity also fired — 3 high-quality outcomes → 3
    # data_product_proposed rows (per-outcome behaviour).
    proposed = _fetch_data_product_proposeds(rows)
    assert len(proposed) == 3, (
        f"expected 3 per-outcome data_product_proposed rows, got "
        f"{len(proposed)}"
    )
