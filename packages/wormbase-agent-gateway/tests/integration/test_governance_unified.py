"""Governance unification — MCP path runs inline (Wave 2) + stateful gates.

v1.1 Task 5 / Hole #7. Verifies that ``apply_gates`` composes the four
inline gates with the four ``wormbase_governance`` stateful gates and
that the chain order is canonical (inline gates short-circuit BEFORE
stateful gates can emit ``gate_fired`` ledger writes).

The four stateful gates from ``wormbase_governance`` are:

    PIIGate         — pattern-scan + gate_fired emit
    WarmupGate      — passive always-allowed; active blocked under threshold
    InterjectionGate — daily clarify budget per channel
    KnowledgeGate   — refuses when query concepts are unknown

For the MCP-call surface most are no-ops by design (warmup-passive,
interjection-no-clarify-tool, knowledge-no-extractor); the PII gate is
the one that actively contributes new ledger entries on every MCP call
that carries PII-shaped args. This test fixture therefore focuses on
PII as the canonical signal that the unification is wired, plus
order-and-short-circuit assertions for the rest.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
# Import the gate implementations directly from the submodule to avoid
# pulling in ``wormbase_governance.relevance`` (which has a transitive
# dep on ``wormbase_core``; agent-gateway is decoupled from worm-core
# by design).
from wormbase_governance.gates import (
    InterjectionGate,
    KnowledgeGate,
    PIIGate,
    WarmupGate,
)
from wormbase_inference import AgentID, GovernanceContext
from wormbase_ledger import InMemoryLedger
from wormbase_ontology_seed import Loader

from wormbase_agent_gateway.governance import (
    GateChain,
    apply_gates,
    make_default_gate_chain,
    make_stateful_gate_bundle,
)
from wormbase_agent_gateway.identity import AgentGrant


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _grant(
    agent_value: str,
    kind: str,
    target: str = "x",
    budget: Decimal | None = None,
) -> AgentGrant:
    return AgentGrant(
        id=str(uuid4()),
        agent_id=agent_value,
        grant_kind=kind,  # type: ignore[arg-type]
        grant_target=target,
        status="active",
        granted_by="admin",
        granted_at=datetime.now(UTC),
        budget_remaining_usd=budget,
    )


async def _gate_fired_kinds(ledger: InMemoryLedger, company_id: UUID) -> list[str]:
    """Return the per-gate names of every ``gate_fired`` entry in the ledger."""
    rows = await ledger.fetch(company_id)
    gates: list[str] = []
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") != "emit_gate_fired":
            continue
        gates.append((payload.get("args") or {}).get("gate", "unknown"))
    return gates


async def _make_ramp_reader(_cid: UUID) -> Any:
    """Stub ramp reader — warmup passes for passive callers always."""

    class _Ramp:
        schema_axis = 100.0
    return _Ramp()


def _build_full_grants(agent_value: str) -> list[AgentGrant]:
    return [
        _grant(agent_value, "domain.read", "dom-1"),
        _grant(agent_value, "model.access", "kimi", budget=Decimal("10.00")),
    ]


def _build_chain_with_stateful(
    *,
    ledger: InMemoryLedger,
    company_id: UUID,
    grants: list[AgentGrant],
    seed_loader: Loader | None = None,
) -> GateChain:
    loader = seed_loader or Loader()

    pii = PIIGate(ledger, company_id, loader)
    warmup = WarmupGate(_make_ramp_reader, ledger, company_id)
    interjection = InterjectionGate(ledger, company_id)
    knowledge = KnowledgeGate(
        ontology_concepts=[],
        confirmed_concepts=[],
        ledger=ledger,
        company_id=company_id,
    )
    bundle = make_stateful_gate_bundle(
        pii_gate=pii,
        warmup_gate=warmup,
        interjection_gate=interjection,
        knowledge_gate=knowledge,
    )

    async def _lookup(_a: AgentID) -> list[AgentGrant]:
        return list(grants)

    return make_default_gate_chain(
        grant_lookup=_lookup,
        stateful=bundle,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_mcp_tool_call_runs_inline_gates_first_then_stateful():
    """The chain order: 4 inline → 4 stateful.

    With a clean args dict (no PII), the inline gates all pass, then
    each stateful adapter runs but none of them emit (PII has nothing
    to match, warmup is passive-allowed, interjection is no-op for
    non-clarify tools, knowledge is no-op without an extractor).
    """
    company_id = UUID("00000000-0000-0000-0000-000000000123")
    ledger = InMemoryLedger()
    grants = _build_full_grants("agent-a")
    chain = _build_chain_with_stateful(
        ledger=ledger, company_id=company_id, grants=grants,
    )

    denial = await apply_gates(
        chain,
        agent_id=AgentID(value="agent-a"),
        mcp_tool="lake.semantic.metric",
        args={"name": "weekly_revenue"},
    )
    assert denial is None
    # No PII in args → PIIGate stateful does not emit gate_fired.
    fired = await _gate_fired_kinds(ledger, company_id)
    assert fired == []


async def test_mcp_tool_call_with_pii_args_triggers_stateful_pii_gate():
    """A tool call whose args contain PII triggers PIIGate (stateful).

    PIIGate's contract: when its pattern set matches, it emits a
    ``gate_fired`` ledger entry with ``gate=pii`` and the matched
    pattern ids. The call itself is NOT denied (consistent with the
    inline ``PIIRedactionGate``).
    """
    company_id = UUID("00000000-0000-0000-0000-000000000123")
    ledger = InMemoryLedger()
    grants = _build_full_grants("agent-a")
    chain = _build_chain_with_stateful(
        ledger=ledger, company_id=company_id, grants=grants,
    )

    args = {
        "name": "weekly_revenue",
        "filter": {
            "owner_email": "alice@example.com",  # email PII
            "phone": "+1 555-123-4567",          # phone PII
        },
    }
    denial = await apply_gates(
        chain,
        agent_id=AgentID(value="agent-a"),
        mcp_tool="lake.semantic.metric",
        args=args,
    )
    # PII is observed, not denied.
    assert denial is None
    fired = await _gate_fired_kinds(ledger, company_id)
    # The stateful PIIGate emitted at least one gate_fired entry.
    assert "pii" in fired


async def test_existing_inline_gate_denial_short_circuits_before_stateful():
    """If an inline gate denies, stateful gates do NOT run.

    Cost-saving property of the chain: a missing access grant doesn't
    waste ledger writes from the stateful PII gate. We use a no-grant
    agent + PII-bearing args, then assert (a) the inline AgentAccessGate
    fires, (b) no ``gate_fired`` entries were written by stateful PII.
    """
    company_id = UUID("00000000-0000-0000-0000-000000000123")
    ledger = InMemoryLedger()
    # No grants — AgentAccessGate denies first.
    chain = _build_chain_with_stateful(
        ledger=ledger, company_id=company_id, grants=[],
    )

    args = {"name": "x", "filter": {"email": "carol@example.com"}}
    denial = await apply_gates(
        chain,
        agent_id=AgentID(value="agent-a"),
        mcp_tool="lake.semantic.metric",
        args=args,
    )
    assert denial is not None
    assert denial.gate_name == "agent_access"
    # Inline denial short-circuited before stateful PII ran — no
    # gate_fired ledger entries.
    fired = await _gate_fired_kinds(ledger, company_id)
    assert fired == [], (
        f"stateful gates ran despite inline denial: {fired}"
    )


async def test_chain_without_stateful_bundle_behaves_like_wave_2():
    """When ``stateful`` is None the chain is byte-identical to Wave 2.

    Existing chat-presence path is unchanged: chat-presence constructs
    PIIGate/WarmupGate/InterjectionGate/KnowledgeGate directly via
    worm-core.service and uses them on its own wire — it does NOT go
    through ``apply_gates``. This test pins the regression-safety
    boundary: setting ``stateful=None`` on the chain (the Wave 2
    default) results in zero stateful-gate writes.
    """
    company_id = UUID("00000000-0000-0000-0000-000000000123")
    ledger = InMemoryLedger()
    grants = _build_full_grants("agent-a")

    async def _lookup(_a: AgentID) -> list[AgentGrant]:
        return list(grants)

    # Default factory — no stateful bundle.
    chain = make_default_gate_chain(grant_lookup=_lookup)
    assert chain.stateful is None

    args = {
        "name": "weekly_revenue",
        "filter": {"email": "dave@example.com"},
    }
    denial = await apply_gates(
        chain,
        agent_id=AgentID(value="agent-a"),
        mcp_tool="lake.semantic.metric",
        args=args,
    )
    assert denial is None
    fired = await _gate_fired_kinds(ledger, company_id)
    assert fired == []


async def test_inline_pii_redaction_still_works_alongside_stateful():
    """Inline ``PIIRedactionGate.redact_args`` is unaffected by the unification.

    The inline gate is the audit-row-renderer; the stateful gate is the
    ledger-entry-emitter. Both must work — verifies the redact_args
    surface is intact and orthogonal to the new stateful adapter.
    """
    company_id = UUID("00000000-0000-0000-0000-000000000123")
    ledger = InMemoryLedger()
    grants = _build_full_grants("agent-a")
    chain = _build_chain_with_stateful(
        ledger=ledger, company_id=company_id, grants=grants,
    )

    args = {"nl_question": "find user bob@example.com transactions"}
    redacted, matched = chain.pii_redaction.redact_args(args)
    assert "[REDACTED:email]" in redacted["nl_question"]
    assert "email" in matched

    denial = await apply_gates(
        chain,
        agent_id=AgentID(value="agent-a"),
        mcp_tool="lake.semantic.metric",
        args=args,
    )
    assert denial is None
    fired = await _gate_fired_kinds(ledger, company_id)
    # The stateful PII gate fired on the same args.
    assert "pii" in fired


async def test_governance_context_passes_through_to_classification():
    """The unification did not break the GovernanceContext threading.

    ClassificationGate sits between the agent_access and pii_redaction
    gates and consumes ``governance.classification_ceiling``. This
    test pins that the context-bearing inline gate still runs in the
    composed chain (regression).
    """
    company_id = UUID("00000000-0000-0000-0000-000000000123")
    ledger = InMemoryLedger()
    grants = _build_full_grants("agent-a")

    async def _resource_classification(rid: str) -> str | None:
        return {"top-secret-table": "regulated"}.get(rid)

    loader = Loader()
    pii = PIIGate(ledger, company_id, loader)
    warmup = WarmupGate(_make_ramp_reader, ledger, company_id)
    interjection = InterjectionGate(ledger, company_id)
    knowledge = KnowledgeGate(
        ontology_concepts=[], confirmed_concepts=[],
        ledger=ledger, company_id=company_id,
    )
    bundle = make_stateful_gate_bundle(
        pii_gate=pii,
        warmup_gate=warmup,
        interjection_gate=interjection,
        knowledge_gate=knowledge,
    )

    async def _lookup(_a: AgentID) -> list[AgentGrant]:
        return list(grants)

    chain = make_default_gate_chain(
        grant_lookup=_lookup,
        resource_classification=_resource_classification,
        stateful=bundle,
    )

    denial = await apply_gates(
        chain,
        agent_id=AgentID(value="agent-a"),
        mcp_tool="lake.lineage",
        args={"resource_id": "top-secret-table"},
        governance=GovernanceContext(classification_ceiling="internal"),
    )
    assert denial is not None
    assert denial.gate_name == "classification"
    # Inline denial short-circuited; PII stateful did NOT fire.
    fired = await _gate_fired_kinds(ledger, company_id)
    assert "pii" not in fired
