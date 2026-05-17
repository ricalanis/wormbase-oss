"""Integration: OutcomeToTemplatePromotion W5a Reactivity end-to-end.

Verifies the §4.5 compounding-loop pin:

  * 3 same-domain + same-canonical-NL ``query_outcome_recorded``
    propose entries with ``quality_score >= 0.9`` produce one
    ``query_template_promoted`` PEVR cycle.
  * Below threshold (2 outcomes) → no promotion.
  * Promotion records its source outcome entry_ids in
    ``promoted_from_outcome_ids``.
  * Repeat-dispatch is idempotent: a second qualifying outcome that
    matches an already-promoted (domain, intent) does NOT emit a
    duplicate ``query_template_promoted``.

Uses the real ``ReactivityRegistry`` + ``ReactivityRunner`` +
``InMemoryLedger`` so this is a true integration test — no mocks.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.registry import ReactivityRegistry
from wormbase_reactivities.runner import ReactivityRunner

from wormbase_agent_gateway.reactivities import (
    OutcomeToTemplatePromotionReactivity,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000abc")


async def _write_outcome(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    domain_id: str,
    nl_question: str,
    quality_score: str = "1.0",
    agent_query_id: str | None = None,
    timestamp: datetime | None = None,
) -> dict:
    """Drive the same canonical-PEVR ledger.write shape that
    ``lake.query.record_outcome`` emits (Wave 2 Task 7, Wave 3 Task 0
    target_kind+EntryKind cleanup). Propose carries
    ``target_kind="query_outcome_recorded"``; execute carries
    ``tool="emit_query_outcome_recorded"`` + ``args=outcome_dict``.
    Returns the execute entry as a dict so the test can reference its
    ``entry_id`` (which is what ``promoted_from_outcome_ids`` records).
    """
    aqi = agent_query_id or str(uuid4())
    outcome_dict: dict = {
        "agent_query_id": aqi,
        "nl_question": nl_question,
        "final_query_spec": {"domain_id": domain_id, "metric": "revenue"},
        "result_summary": {"row_count": 1},
        "used": True,
        "useful": True,
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
        timestamp=timestamp,
        quadrant="active_deterministic",
    )
    rows = await ledger.fetch(company_id)
    # The most recent execute entry with this nl_question + agent_query_id
    executes = [
        r for r in rows
        if r["kind"] == "execute"
        and (r["payload"] or {}).get("tool") == "emit_query_outcome_recorded"
        and ((r["payload"] or {}).get("args") or {}).get("nl_question")
            == nl_question
        and ((r["payload"] or {}).get("args") or {}).get("agent_query_id")
            == aqi
    ]
    return executes[-1]


def _fetch_promotions(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if r["kind"] == "propose"
        and "nl_intent" in (r.get("payload") or {})
        and "promoted_from_outcome_ids" in (r.get("payload") or {})
    ]


@pytest.mark.asyncio
async def test_three_high_quality_outcomes_produce_one_promotion() -> None:
    """3 outcomes with quality_score >= 0.9, same domain + same canonical
    NL intent → one query_template_promoted entry."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(OutcomeToTemplatePromotionReactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    o1 = await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        domain_id="dom-finance",
        nl_question="What is revenue this quarter?",
        quality_score="0.95",
    )
    o2 = await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        domain_id="dom-finance",
        nl_question="what is revenue THIS quarter?",   # canonical match
        quality_score="0.95",
    )
    o3 = await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        domain_id="dom-finance",
        nl_question="What is revenue this quarter?",
        quality_score="1.0",
    )

    fired = await runner.run_once()
    assert fired >= 1, "Reactivity should have fired at least once"

    rows = await ledger.fetch(_COMPANY_ID)
    promotions = _fetch_promotions(rows)
    assert len(promotions) == 1, (
        f"expected exactly 1 promotion, got {len(promotions)}: "
        f"{[p['payload'] for p in promotions]}"
    )

    p = promotions[0]["payload"]
    assert p["domain_id"] == "dom-finance"
    # canonical_intent is lowercase + whitespace-normalised
    assert p["nl_intent"] == "what is revenue this quarter?"
    # query_spec sourced from the best (highest-quality) outcome
    assert p["query_spec"]["metric"] == "revenue"
    # promoted_from_outcome_ids carries the three source entry_ids
    src_ids = list(p["promoted_from_outcome_ids"])
    assert set(src_ids) == {
        str(o1["entry_id"]),
        str(o2["entry_id"]),
        str(o3["entry_id"]),
    }
    # mean quality is in [0.9, 1.0]; quantized to NUMERIC(6,4) shape
    mean = Decimal(p["quality_score"])
    assert Decimal("0.9") <= mean <= Decimal("1.0")


@pytest.mark.asyncio
async def test_two_outcomes_below_threshold_no_promotion() -> None:
    """2 outcomes is below the 3-outcome cluster threshold → no
    query_template_promoted entry."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(OutcomeToTemplatePromotionReactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        domain_id="dom-product",
        nl_question="How many active users today?",
        quality_score="1.0",
    )
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        domain_id="dom-product",
        nl_question="how many active users today?",
        quality_score="1.0",
    )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    promotions = _fetch_promotions(rows)
    assert promotions == [], (
        f"2 outcomes (below threshold=3) must not promote; got "
        f"{len(promotions)} promotions"
    )


@pytest.mark.asyncio
async def test_low_quality_outcomes_do_not_promote() -> None:
    """3 outcomes but each with quality_score < 0.9 → no promotion."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(OutcomeToTemplatePromotionReactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    for _ in range(3):
        await _write_outcome(
            ledger, company_id=_COMPANY_ID,
            domain_id="dom-sales",
            nl_question="Pipeline coverage by region?",
            quality_score="0.5",
        )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_promotions(rows) == []


@pytest.mark.asyncio
async def test_repeat_dispatch_is_idempotent() -> None:
    """A second qualifying outcome on an already-promoted cluster does
    NOT emit a duplicate query_template_promoted entry."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(OutcomeToTemplatePromotionReactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    for _ in range(3):
        await _write_outcome(
            ledger, company_id=_COMPANY_ID,
            domain_id="dom-ops",
            nl_question="Latency P95 this week?",
            quality_score="0.95",
        )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    first_pass = _fetch_promotions(rows)
    assert len(first_pass) == 1

    # Land a 4th qualifying outcome on the same canonical (domain, intent)
    # and dispatch again. The per-cluster idempotency check inside
    # ``fire`` should prevent a second promotion.
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        domain_id="dom-ops",
        nl_question="Latency P95 this week?",
        quality_score="0.97",
    )
    # The NotRecentlyFired condition with a 1h window will block a
    # second dispatch on the existing reactivity instance — to assert
    # the in-fire idempotency check independent of the condition, we
    # spin up a fresh registry pointed at the same ledger.
    fresh_registry = ReactivityRegistry(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    fresh_registry.register(OutcomeToTemplatePromotionReactivity())
    fresh_runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=fresh_registry,
        poll_interval_s=0.01,
    )
    await fresh_runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    promotions = _fetch_promotions(rows)
    assert len(promotions) == 1, (
        f"per-cluster idempotency check failed: expected 1 promotion "
        f"after re-dispatch, got {len(promotions)}"
    )


@pytest.mark.asyncio
async def test_outcomes_outside_lookback_window_excluded() -> None:
    """Outcomes older than the 30-day lookback are not part of the
    cluster; recent count must reach threshold on its own."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(OutcomeToTemplatePromotionReactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    old_ts = datetime.now(UTC) - timedelta(days=45)
    # 2 old outcomes — should be ignored
    for _ in range(2):
        await _write_outcome(
            ledger, company_id=_COMPANY_ID,
            domain_id="dom-marketing",
            nl_question="Conversion rate by channel?",
            quality_score="1.0",
            timestamp=old_ts,
        )
    # 2 fresh outcomes — total recent count below threshold
    for _ in range(2):
        await _write_outcome(
            ledger, company_id=_COMPANY_ID,
            domain_id="dom-marketing",
            nl_question="Conversion rate by channel?",
            quality_score="1.0",
        )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_promotions(rows) == [], (
        "outcomes outside the lookback window must not contribute to "
        "the cluster count"
    )
