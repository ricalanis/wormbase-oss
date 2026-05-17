"""v2.B Phase 2 Axis 5 — DataProductConsumptionToRecommendation tests.

Pins the Phase 2 contract for the consumption-recommendation
compounding axis:

  * source predicate: ``data_product_consumed``;
  * quality_filter: ``surface ∈ {mcp, agent, api}`` — agent/automation
    consumers only;
  * gather_fn: 7-day look-back of execute consumption rows;
  * cluster_fn: by ``data_product_id``;
  * promotion_threshold: ``>= 3 DISTINCT consumer ids in-window``;
  * promotion_action: emit ``data_product_recommended`` PEVR cycle;
  * idempotency_filter: skip if a ``data_product_recommended`` already
    exists for the same product id.

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
    make_data_product_consumption_to_recommendation_reactivity,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000a0003")


async def _write_consumed(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    data_product_id: UUID,
    consumed_by_agent_id: str | None = None,
    consumed_by_person_id: UUID | None = None,
    surface: str = "mcp",
) -> dict:
    """Drive the canonical PEVR shape ``data_products.consume`` emits.

    ``consumed_by_person_id`` defaults to a synthetic UUID (the
    1:1 Person id stand-in v1 uses for agents); ``consumed_by_agent_id``
    is the AgentID string when set.
    """
    person_id = consumed_by_person_id or uuid4()
    args: dict = {
        "data_product_id": str(data_product_id),
        "consumed_by_person_id": str(person_id),
        "consumed_by_agent_id": consumed_by_agent_id,
        "surface": surface,
        "channel": None,
    }
    consumption_id = str(uuid4())
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "data_product_consumed",
            "ref_id": str(data_product_id),
            "reason": (
                f"test consumption surface={surface} "
                f"agent={consumed_by_agent_id}"
            ),
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_data_product_consumed",
            "args": args,
            "result_ref": consumption_id,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "data_product_consumed", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "data_product_consumed",
        },
        quadrant="active_deterministic",
    )
    rows = await ledger.fetch(company_id)
    matching = [
        r for r in rows
        if r["kind"] == "execute"
        and (r["payload"] or {}).get("tool") == "emit_data_product_consumed"
        and ((r["payload"] or {}).get("args") or {}).get("data_product_id")
            == str(data_product_id)
    ]
    return matching[-1]


def _fetch_recommendations(rows: list[dict]) -> list[dict]:
    """Return propose rows targeting ``data_product_recommended``."""
    return [
        r for r in rows
        if r["kind"] == "propose"
        and (r.get("payload") or {}).get("target_kind") == "data_product_recommended"
    ]


def _fetch_recommendation_executes(rows: list[dict]) -> list[dict]:
    """Return execute rows for the ``data_product_recommended`` cycle."""
    return [
        r for r in rows
        if r["kind"] == "execute"
        and "recommendation_score" in (r.get("payload") or {})
        and "consumer_agent_ids" in (r.get("payload") or {})
    ]


@pytest.mark.asyncio
async def test_three_distinct_agent_consumers_promote_to_recommended() -> None:
    """3 distinct agent consumers on the same data product within 7d →
    one ``data_product_recommended`` PEVR cycle."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_data_product_consumption_to_recommendation_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    dp_id = uuid4()
    for agent in ("agent-claude", "agent-kimi", "agent-openai"):
        await _write_consumed(
            ledger, company_id=_COMPANY_ID,
            data_product_id=dp_id,
            consumed_by_agent_id=agent,
            surface="mcp",
        )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    recommended = _fetch_recommendations(rows)
    assert len(recommended) == 1, (
        f"expected exactly 1 data_product_recommended, got "
        f"{len(recommended)}: {[r['payload'] for r in recommended]}"
    )
    payload = recommended[0]["payload"]
    assert payload["data_product_id"] == str(dp_id)
    assert payload["proposed_by"] == "agent_gateway.compounding_loop"

    executes = _fetch_recommendation_executes(rows)
    assert len(executes) == 1
    ex_payload = executes[0]["payload"]
    assert ex_payload["data_product_id"] == str(dp_id)
    assert ex_payload["recommendation_score"] == 3
    assert ex_payload["consumed_within_days"] == 7
    consumer_ids = set(ex_payload["consumer_agent_ids"])
    assert consumer_ids == {"agent-claude", "agent-kimi", "agent-openai"}


@pytest.mark.asyncio
async def test_two_distinct_consumers_below_threshold_no_recommendation() -> None:
    """2 distinct consumers is below the threshold (3) → no promotion."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_data_product_consumption_to_recommendation_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    dp_id = uuid4()
    for agent in ("agent-claude", "agent-kimi"):
        await _write_consumed(
            ledger, company_id=_COMPANY_ID,
            data_product_id=dp_id,
            consumed_by_agent_id=agent,
            surface="mcp",
        )

    await runner.run_once()
    assert _fetch_recommendations(await ledger.fetch(_COMPANY_ID)) == []


@pytest.mark.asyncio
async def test_repeated_consumption_by_same_agent_does_not_count_separately() -> None:
    """3 consumption rows by the SAME agent on the same product →
    only 1 distinct consumer → below threshold → no promotion."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_data_product_consumption_to_recommendation_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    dp_id = uuid4()
    for _ in range(5):
        await _write_consumed(
            ledger, company_id=_COMPANY_ID,
            data_product_id=dp_id,
            consumed_by_agent_id="agent-claude",
            surface="mcp",
        )

    await runner.run_once()
    assert _fetch_recommendations(await ledger.fetch(_COMPANY_ID)) == [], (
        "5 consumptions by same agent must NOT promote (1 distinct "
        "consumer, below threshold 3)"
    )


@pytest.mark.asyncio
async def test_dashboard_surface_consumption_does_not_count() -> None:
    """``surface=dashboard`` consumptions are filtered by quality_filter
    → 3 dashboard consumers do NOT trigger a recommendation."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_data_product_consumption_to_recommendation_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    dp_id = uuid4()
    for person_id in (uuid4(), uuid4(), uuid4()):
        await _write_consumed(
            ledger, company_id=_COMPANY_ID,
            data_product_id=dp_id,
            consumed_by_person_id=person_id,
            consumed_by_agent_id=None,
            surface="dashboard",
        )

    await runner.run_once()
    assert _fetch_recommendations(await ledger.fetch(_COMPANY_ID)) == [], (
        "dashboard-surface consumptions must be filtered out — only "
        "agent/automation traffic feeds the recommendation signal"
    )


@pytest.mark.asyncio
async def test_idempotency_filter_suppresses_duplicate_recommendation() -> None:
    """Re-dispatching after a product has already been recommended does
    NOT emit a duplicate ``data_product_recommended`` entry — the
    first-class ``idempotency_filter`` short-circuits the action."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_data_product_consumption_to_recommendation_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    dp_id = uuid4()
    for agent in ("agent-claude", "agent-kimi", "agent-openai"):
        await _write_consumed(
            ledger, company_id=_COMPANY_ID,
            data_product_id=dp_id,
            consumed_by_agent_id=agent,
            surface="mcp",
        )

    await runner.run_once()
    first = _fetch_recommendations(await ledger.fetch(_COMPANY_ID))
    assert len(first) == 1

    # More consumers land + a fresh registry spun up (bypasses
    # NotRecentlyFired) so we exercise the idempotency_filter directly.
    await _write_consumed(
        ledger, company_id=_COMPANY_ID,
        data_product_id=dp_id,
        consumed_by_agent_id="agent-cohere",
        surface="mcp",
    )
    fresh_registry = ReactivityRegistry(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    fresh_registry.register(
        make_data_product_consumption_to_recommendation_reactivity()
    )
    fresh_runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=fresh_registry,
        poll_interval_s=0.01,
    )
    await fresh_runner.run_once()
    second = _fetch_recommendations(await ledger.fetch(_COMPANY_ID))
    assert len(second) == 1, (
        f"idempotency_filter failed: expected 1 recommendation after "
        f"re-dispatch, got {len(second)}"
    )


@pytest.mark.asyncio
async def test_two_distinct_products_each_recommend_separately() -> None:
    """Two distinct data products each crossing the threshold →
    two distinct recommendations."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_data_product_consumption_to_recommendation_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    dp_a = uuid4()
    dp_b = uuid4()
    for agent in ("a-1", "a-2", "a-3"):
        await _write_consumed(
            ledger, company_id=_COMPANY_ID,
            data_product_id=dp_a, consumed_by_agent_id=agent, surface="mcp",
        )
    for agent in ("b-1", "b-2", "b-3"):
        await _write_consumed(
            ledger, company_id=_COMPANY_ID,
            data_product_id=dp_b, consumed_by_agent_id=agent, surface="agent",
        )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    recommended = _fetch_recommendations(rows)
    assert len(recommended) == 2
    dp_ids = {r["payload"]["data_product_id"] for r in recommended}
    assert dp_ids == {str(dp_a), str(dp_b)}


@pytest.mark.asyncio
async def test_api_surface_counts_alongside_mcp_and_agent() -> None:
    """All three agent-axis surfaces (mcp, agent, api) contribute to the
    distinct-consumer count."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_data_product_consumption_to_recommendation_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    dp_id = uuid4()
    await _write_consumed(
        ledger, company_id=_COMPANY_ID, data_product_id=dp_id,
        consumed_by_agent_id="agent-via-mcp", surface="mcp",
    )
    await _write_consumed(
        ledger, company_id=_COMPANY_ID, data_product_id=dp_id,
        consumed_by_agent_id="agent-via-agent", surface="agent",
    )
    await _write_consumed(
        ledger, company_id=_COMPANY_ID, data_product_id=dp_id,
        consumed_by_agent_id="agent-via-api", surface="api",
    )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    recommended = _fetch_recommendations(rows)
    assert len(recommended) == 1
