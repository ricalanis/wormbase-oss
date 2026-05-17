"""Unit tests for the inline governance gates.

Covers:
    - AgentAccessGate denies when the agent has no matching grant.
    - AgentAccessGate accepts on resource.maintainer (super-reader).
    - ClassificationGate denies when resource exceeds ceiling.
    - PIIRedactionGate redacts emails / SSNs in args, never denies.
    - CostGate denies when model.access budget <= 0.
    - apply_gates composes in canonical order + short-circuits.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from wormbase_inference import AgentID, GovernanceContext

from wormbase_agent_gateway.governance import (
    AgentAccessGate,
    ClassificationGate,
    CostGate,
    PIIRedactionGate,
    apply_gates,
    make_default_gate_chain,
)
from wormbase_agent_gateway.identity import AgentGrant


pytestmark = pytest.mark.asyncio


def _grant(agent_value: str, kind: str, target: str = "x", budget=None, status="active") -> AgentGrant:
    return AgentGrant(
        id=str(uuid4()),
        agent_id=agent_value,
        grant_kind=kind,  # type: ignore[arg-type]
        grant_target=target,
        status=status,  # type: ignore[arg-type]
        granted_by="admin",
        granted_at=datetime.now(UTC),
        budget_remaining_usd=budget,
    )


async def test_agent_access_denies_with_no_grant():
    async def _lookup(_a): return []
    gate = AgentAccessGate(grant_lookup=_lookup)
    denial = await gate.check(
        agent_id=AgentID(value="a"),
        mcp_tool="lake.semantic.metric",
        args={},
    )
    assert denial is not None
    assert denial.gate_name == "agent_access"
    assert "lacks an active grant" in denial.reason


async def test_agent_access_accepts_resource_maintainer():
    """resource.maintainer is a super-reader; should satisfy any read tool."""
    grants = [_grant("a", "resource.maintainer", "res-1")]
    async def _lookup(_a): return grants
    gate = AgentAccessGate(grant_lookup=_lookup)
    denial = await gate.check(
        agent_id=AgentID(value="a"),
        mcp_tool="lake.lineage",
        args={"resource_id": "res-1"},
    )
    assert denial is None


async def test_agent_access_denies_on_unknown_tool():
    async def _lookup(_a): return []
    gate = AgentAccessGate(grant_lookup=_lookup)
    denial = await gate.check(
        agent_id=AgentID(value="a"),
        mcp_tool="lake.unregistered.tool",
        args={},
    )
    assert denial is not None
    assert "unknown mcp_tool" in denial.reason


async def test_classification_denies_when_resource_exceeds_ceiling():
    async def _lookup(rid):
        return {"top-secret-table": "regulated"}.get(rid)
    gate = ClassificationGate(resource_classification=_lookup)
    denial = await gate.check(
        agent_id=AgentID(value="a"),
        mcp_tool="lake.semantic.metric",
        args={"resource_id": "top-secret-table"},
        governance=GovernanceContext(classification_ceiling="internal"),
    )
    assert denial is not None
    assert denial.gate_name == "classification"


async def test_classification_passes_when_under_ceiling():
    async def _lookup(rid): return "internal"
    gate = ClassificationGate(resource_classification=_lookup)
    denial = await gate.check(
        agent_id=AgentID(value="a"),
        mcp_tool="lake.lineage",
        args={"resource_id": "tbl-1"},
        governance=GovernanceContext(classification_ceiling="confidential"),
    )
    assert denial is None


async def test_classification_passes_when_no_lookup():
    gate = ClassificationGate(resource_classification=None)
    denial = await gate.check(
        agent_id=AgentID(value="a"),
        mcp_tool="lake.semantic.metric",
        args={"resource_id": "x"},
        governance=GovernanceContext(),
    )
    assert denial is None


async def test_pii_redaction_never_denies_but_redacts_args():
    gate = PIIRedactionGate()
    denial = await gate.check(
        agent_id=AgentID(value="a"),
        mcp_tool="lake.semantic.metric",
        args={"nl_question": "find user bob@example.com transactions"},
    )
    assert denial is None
    redacted, matched = gate.redact_args(
        {"nl_question": "bob@example.com SSN 123-45-6789"},
    )
    assert "[REDACTED:email]" in redacted["nl_question"]
    assert "[REDACTED:ssn]" in redacted["nl_question"]
    assert "email" in matched
    assert "ssn" in matched


async def test_pii_redaction_walks_nested_dicts_and_lists():
    gate = PIIRedactionGate()
    redacted, matched = gate.redact_args({
        "filter": {"email": "alice@example.com"},
        "tokens": ["foo", "bob@example.com"],
    })
    assert "[REDACTED:email]" in redacted["filter"]["email"]
    assert "[REDACTED:email]" in redacted["tokens"][1]
    assert matched == ["email"]


async def test_cost_denies_when_budget_zero():
    grants = [_grant("a", "model.access", "kimi", budget=Decimal("0.00"))]
    async def _lookup(_a): return grants
    gate = CostGate(grant_lookup=_lookup)
    denial = await gate.check(
        agent_id=AgentID(value="a"),
        mcp_tool="lake.semantic.metric",
        args={},
    )
    assert denial is not None
    assert denial.gate_name == "cost"


async def test_cost_passes_when_no_model_grant():
    """Agent without a model.access grant is governed by other gates only."""
    grants = [_grant("a", "domain.read", "dom-1")]
    async def _lookup(_a): return grants
    gate = CostGate(grant_lookup=_lookup)
    denial = await gate.check(
        agent_id=AgentID(value="a"),
        mcp_tool="lake.semantic.metric",
        args={},
    )
    assert denial is None


async def test_apply_gates_short_circuits_on_first_denial():
    """When AgentAccessGate fires, ClassificationGate / Cost / PII don't run."""
    async def _empty(_a): return []
    chain = make_default_gate_chain(grant_lookup=_empty)
    denial = await apply_gates(
        chain,
        agent_id=AgentID(value="a"),
        mcp_tool="lake.semantic.metric",
        args={"resource_id": "x"},
    )
    assert denial is not None
    assert denial.gate_name == "agent_access"


async def test_apply_gates_passes_with_full_grants():
    grants = [
        _grant("a", "domain.read", "dom-1"),
        _grant("a", "model.access", "kimi", budget=Decimal("5.00")),
    ]
    async def _lookup(_a): return grants
    chain = make_default_gate_chain(grant_lookup=_lookup)
    denial = await apply_gates(
        chain,
        agent_id=AgentID(value="a"),
        mcp_tool="lake.semantic.metric",
        args={"name": "weekly_revenue"},
    )
    assert denial is None
