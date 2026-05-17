"""v2.B Phase 2 Axis 3 — QueryFailureToBadPattern integration tests.

Pins the Phase 2 contract for the bad-pattern compounding axis:

  * source predicate: ``query_outcome_recorded``;
  * quality_filter: ``used=True AND useful=False`` OR
    ``quality_score < 0.3``;
  * gather_fn: 14-day look-back of execute outcomes;
  * cluster_fn: same canonical NL intent + resolved domain;
  * promotion_threshold: ``len(cluster) >= 2``;
  * promotion_action: emit ``bad_pattern_proposed`` PEVR cycle;
  * idempotency_filter: skip if a bad_pattern_proposed already exists
    for the same ``(domain, canonical_intent)``.

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
    make_agent_gateway_reactivities,
    make_query_failure_to_bad_pattern_reactivity,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000a0001")


async def _write_outcome(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    nl_question: str,
    quality_score: str = "0.25",
    used: bool = True,
    useful: bool = False,
    domain_id: str | None = None,
    agent_query_id: str | None = None,
) -> dict:
    """Drive the canonical PEVR shape ``lake.query.record_outcome`` emits."""
    aqi = agent_query_id or str(uuid4())
    spec: dict = {"metric": "revenue_q3", "filter": {"region": "EMEA"}}
    if domain_id is not None:
        spec["domain_id"] = domain_id
    outcome_dict: dict = {
        "agent_query_id": aqi,
        "nl_question": nl_question,
        "final_query_spec": spec,
        "result_summary": {"row_count": 0},
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


def _fetch_bad_pattern_proposeds(rows: list[dict]) -> list[dict]:
    """Return propose rows targeting ``bad_pattern_proposed``."""
    return [
        r for r in rows
        if r["kind"] == "propose"
        and (r.get("payload") or {}).get("target_kind") == "bad_pattern_proposed"
    ]


def _fetch_bad_pattern_executes(rows: list[dict]) -> list[dict]:
    """Return execute rows for the ``bad_pattern_proposed`` cycle's
    payload contents (the actual BadPatternProposedPayload fields)."""
    return [
        r for r in rows
        if r["kind"] == "execute"
        and "canonical_intent" in (r.get("payload") or {})
        and "failed_outcome_ids" in (r.get("payload") or {})
    ]


@pytest.mark.asyncio
async def test_two_bad_outcomes_promote_to_bad_pattern() -> None:
    """2 failed outcomes (``used=True AND useful=False``) on the same
    canonical NL intent → one ``bad_pattern_proposed`` PEVR cycle."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_query_failure_to_bad_pattern_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    o1 = await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="What was Q3 EMEA revenue?",
        used=True, useful=False, quality_score="0.91",
        domain_id="dom-finance",
    )
    o2 = await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="what was Q3 EMEA revenue?",  # canonical match
        used=True, useful=False, quality_score="0.95",
        domain_id="dom-finance",
    )

    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_bad_pattern_proposeds(rows)
    assert len(proposed) == 1, (
        f"expected exactly 1 bad_pattern_proposed, got {len(proposed)}: "
        f"{[p['payload'] for p in proposed]}"
    )
    payload = proposed[0]["payload"]
    assert payload["canonical_intent"] == "what was q3 emea revenue?"
    assert payload["domain_id"] == "dom-finance"
    assert payload["proposed_by"] == "agent_gateway.compounding_loop"

    executes = _fetch_bad_pattern_executes(rows)
    assert len(executes) == 1
    ex_payload = executes[0]["payload"]
    assert ex_payload["canonical_intent"] == "what was q3 emea revenue?"
    assert ex_payload["failure_count"] == 2
    assert ex_payload["domain_id"] == "dom-finance"
    src_ids = set(ex_payload["failed_outcome_ids"])
    assert src_ids == {str(o1["entry_id"]), str(o2["entry_id"])}
    # Suggested-avoidance prose is non-empty + mentions canonical_intent.
    assert "what was q3 emea revenue?" in ex_payload["suggested_avoidance"]


@pytest.mark.asyncio
async def test_low_quality_score_also_qualifies_as_bad_outcome() -> None:
    """``quality_score < 0.3`` qualifies even with ``useful=True``."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_query_failure_to_bad_pattern_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    for _ in range(2):
        await _write_outcome(
            ledger, company_id=_COMPANY_ID,
            nl_question="Pipeline coverage by region?",
            # used + useful both true, but score is below 0.3 cutoff
            used=True, useful=True, quality_score="0.15",
            domain_id="dom-sales",
        )

    await runner.run_once()
    proposed = _fetch_bad_pattern_proposeds(await ledger.fetch(_COMPANY_ID))
    assert len(proposed) == 1


@pytest.mark.asyncio
async def test_high_quality_useful_outcome_not_promoted() -> None:
    """``used=True AND useful=True AND quality_score >= 0.9`` → no
    bad-pattern promotion (this is a *good* outcome)."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_query_failure_to_bad_pattern_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    for _ in range(3):
        await _write_outcome(
            ledger, company_id=_COMPANY_ID,
            nl_question="What was Q3 EMEA revenue?",
            used=True, useful=True, quality_score="0.95",
            domain_id="dom-finance",
        )

    await runner.run_once()
    proposed = _fetch_bad_pattern_proposeds(await ledger.fetch(_COMPANY_ID))
    assert proposed == [], (
        "good outcomes must not promote to bad_pattern_proposed; got "
        f"{len(proposed)} promotions"
    )


@pytest.mark.asyncio
async def test_single_bad_outcome_below_threshold_does_not_promote() -> None:
    """1 bad outcome is below the threshold (2) → no promotion."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_query_failure_to_bad_pattern_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="What was Q3 EMEA revenue?",
        used=True, useful=False, quality_score="0.85",
        domain_id="dom-finance",
    )

    await runner.run_once()
    assert _fetch_bad_pattern_proposeds(await ledger.fetch(_COMPANY_ID)) == []


@pytest.mark.asyncio
async def test_idempotency_filter_suppresses_duplicate_bad_pattern() -> None:
    """Re-dispatching after a cluster has already been promoted does NOT
    emit a duplicate ``bad_pattern_proposed`` entry — the first-class
    ``idempotency_filter`` short-circuits the action."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_query_failure_to_bad_pattern_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    for _ in range(2):
        await _write_outcome(
            ledger, company_id=_COMPANY_ID,
            nl_question="Latency P95 this week?",
            used=True, useful=False, quality_score="0.5",
            domain_id="dom-ops",
        )

    await runner.run_once()
    first = _fetch_bad_pattern_proposeds(await ledger.fetch(_COMPANY_ID))
    assert len(first) == 1

    # Land more bad outcomes on the same cluster + spin a fresh registry
    # (bypasses NotRecentlyFired debounce) so we exercise the
    # idempotency_filter path inside `fire` directly.
    for _ in range(2):
        await _write_outcome(
            ledger, company_id=_COMPANY_ID,
            nl_question="latency P95 this week?",   # canonical match
            used=True, useful=False, quality_score="0.3",
            domain_id="dom-ops",
        )

    fresh_registry = ReactivityRegistry(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    fresh_registry.register(make_query_failure_to_bad_pattern_reactivity())
    fresh_runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=fresh_registry,
        poll_interval_s=0.01,
    )
    await fresh_runner.run_once()

    second = _fetch_bad_pattern_proposeds(await ledger.fetch(_COMPANY_ID))
    assert len(second) == 1, (
        f"idempotency_filter failed: expected 1 bad_pattern_proposed "
        f"after re-dispatch, got {len(second)}"
    )


@pytest.mark.asyncio
async def test_bad_pattern_clusters_separated_by_domain() -> None:
    """Bad outcomes on the same NL intent but DIFFERENT domains → two
    distinct bad_pattern_proposed entries."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_query_failure_to_bad_pattern_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    for _ in range(2):
        await _write_outcome(
            ledger, company_id=_COMPANY_ID,
            nl_question="What is conversion rate?",
            used=True, useful=False, quality_score="0.25",
            domain_id="dom-sales",
        )
    for _ in range(2):
        await _write_outcome(
            ledger, company_id=_COMPANY_ID,
            nl_question="What is conversion rate?",
            used=True, useful=False, quality_score="0.25",
            domain_id="dom-product",
        )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_bad_pattern_proposeds(rows)
    assert len(proposed) == 2, (
        f"expected 2 bad_pattern_proposed entries (one per domain); got "
        f"{len(proposed)}: {[(p['payload'].get('domain_id'),) for p in proposed]}"
    )
    domains = {p["payload"]["domain_id"] for p in proposed}
    assert domains == {"dom-sales", "dom-product"}


@pytest.mark.asyncio
async def test_all_five_reactivities_in_factory() -> None:
    """``make_agent_gateway_reactivities()`` returns 5 Reactivities
    (2 Phase 1 + 3 v2.B Phase 2)."""
    rs = make_agent_gateway_reactivities()
    assert len(rs) == 5
    ids = {r.id for r in rs}
    assert ids == {
        "agent_gateway.outcome_to_template",
        "agent_gateway.outcome_to_data_product",
        "agent_gateway.failure_to_bad_pattern",
        "agent_gateway.gap_to_escalation",
        "agent_gateway.consumption_to_recommendation",
    }
