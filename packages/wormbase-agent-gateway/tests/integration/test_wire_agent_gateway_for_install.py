"""Integration: ``wire_agent_gateway_for_install`` boot-wire smoke test.

Confirms:

  * Calling the wire with a real ``ReactivityRegistry`` registers
    the agent-gateway Reactivities (currently
    ``OutcomeToTemplatePromotionReactivity`` and
    ``QueryOutcomeToDataProductReactivity`` — W3.2 Hole #8).
  * The returned list matches the registry's binding list (identity
    equality on the Reactivity instances).
  * After registration a ``query_outcome_recorded``-shaped propose
    entry written to the ledger DOES fire the Reactivity through the
    canonical ``ReactivityRunner`` (end-to-end smoke).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.registry import ReactivityRegistry
from wormbase_reactivities.runner import ReactivityRunner

from wormbase_agent_gateway import wire_agent_gateway_for_install
from wormbase_agent_gateway.reactivities import (
    OutcomeToTemplatePromotionReactivity,
    QueryOutcomeToDataProductReactivity,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000def")


@dataclass
class _DuckInstall:
    """Minimal Install-shaped object for the wire (mirrors the sibling
    wires' duck-typed install posture)."""

    id: UUID
    platform: str = "slack"


@pytest.mark.asyncio
async def test_wire_registers_agent_gateway_reactivities() -> None:
    """The wire registers the agent-gateway Reactivity set into the
    supplied registry.

    Five Reactivities ship after v2.B Phase 2:

      * ``OutcomeToTemplatePromotionReactivity`` — clusters 3+ outcomes
        to a durable query template (Wave 2 Task 8).
      * ``QueryOutcomeToDataProductReactivity`` — auto-promotes
        individual high-quality outcomes to ``data_product_proposed``
        (W3.2 Hole #8).
      * v2.B Phase 2 axes (built on the ``Compounding`` primitive):
          - ``agent_gateway.failure_to_bad_pattern`` — clusters of
            failed/unhelpful outcomes → ``bad_pattern_proposed``;
          - ``agent_gateway.gap_to_escalation`` — unresolved gaps >7d
            → ``semantic_gap_escalated``;
          - ``agent_gateway.consumption_to_recommendation`` —
            multi-agent consumption clusters → ``data_product_recommended``.
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    registered = await wire_agent_gateway_for_install(
        install=_DuckInstall(id=_COMPANY_ID),
        ledger=ledger,
        reactivity_registry=registry,
    )

    assert len(registered) == 5
    kinds = {type(r) for r in registered}
    # The two Phase-1 Reactivities are still concrete subclasses.
    assert OutcomeToTemplatePromotionReactivity in kinds
    assert QueryOutcomeToDataProductReactivity in kinds
    # The three Phase-2 axes are plain ``Compounding`` instances —
    # identify them by their stable ``id`` rather than class identity.
    registered_ids = {r.id for r in registered}
    assert {
        "agent_gateway.failure_to_bad_pattern",
        "agent_gateway.gap_to_escalation",
        "agent_gateway.consumption_to_recommendation",
    } <= registered_ids

    bindings = registry.list()
    assert len(bindings) == 5
    binding_ids = {b.id for b in bindings}
    assert binding_ids == registered_ids
    assert all(b.state == "active" for b in bindings)


@pytest.mark.asyncio
async def test_wire_smoke_with_outcome_recorded() -> None:
    """End-to-end smoke: wire registers the Reactivity, the runner
    picks up a query_outcome_recorded entry and fires."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    await wire_agent_gateway_for_install(
        install=_DuckInstall(id=_COMPANY_ID),
        ledger=ledger,
        reactivity_registry=registry,
    )

    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    # Land 3 same-canonical-intent + same-domain outcomes — promotion
    # threshold is 3. Canonical-PEVR shape matches what
    # ``lake.query.record_outcome`` emits (Wave 3 Task 0).
    for _ in range(3):
        aqi = str(uuid4())
        outcome_payload: dict[str, Any] = {
            "agent_query_id": aqi,
            "nl_question": "What were our daily active users last week?",
            "final_query_spec": {"domain_id": "dom-growth"},
            "result_summary": {"row_count": 7},
            "used": True,
            "useful": True,
            "user_correction": None,
            "quality_score": "1.0",
        }
        await ledger.write(
            company_id=_COMPANY_ID,
            propose={
                "target_kind": "query_outcome_recorded",
                "ref_id": aqi,
                "reason": f"test outcome aqi={aqi}",
                "proposed_by": "test",
            },
            execute_fn=lambda p=outcome_payload, a=aqi: {
                "tool": "emit_query_outcome_recorded",
                "args": dict(p),
                "result_ref": a,
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

    fired = await runner.run_once()
    assert fired >= 1, "agent-gateway Reactivity should fire on outcome triggers"

    rows = await ledger.fetch(_COMPANY_ID)
    promotions = [
        r for r in rows
        if r["kind"] == "propose"
        and "nl_intent" in (r.get("payload") or {})
        and "promoted_from_outcome_ids" in (r.get("payload") or {})
    ]
    assert len(promotions) == 1, (
        f"expected 1 query_template_promoted after wiring + 3 outcomes, "
        f"got {len(promotions)}"
    )
