"""Wave 2 Task 4 — :class:`GovernanceContext` field on :class:`RouteRequest`.

The governance envelope carries the agent's grant ceiling, cost
budget, redaction policy, and domain scope through to the
``inference_served`` audit row. It's optional (``None`` by default)
so every existing call site keeps working unchanged.
"""
from __future__ import annotations

from decimal import Decimal

from wormbase_inference import GovernanceContext, RouteRequest


def test_governance_context_optional_default_none() -> None:
    """``governance_context`` defaults to ``None`` — back-compat for legacy callers."""
    req = RouteRequest(call_type="reasoning")
    assert req.governance_context is None


def test_governance_context_carries_classification_and_budget() -> None:
    """All four governance fields are addressable on the attached envelope."""
    gov = GovernanceContext(
        classification_ceiling="confidential",
        cost_budget_usd=Decimal("0.50"),
        pii_redaction=True,
        domain_id="finance",
    )
    req = RouteRequest(call_type="agent_tool_reasoning", governance_context=gov)
    assert req.governance_context is not None
    assert req.governance_context.classification_ceiling == "confidential"
    assert req.governance_context.cost_budget_usd == Decimal("0.50")
    assert req.governance_context.pii_redaction is True
    assert req.governance_context.domain_id == "finance"
