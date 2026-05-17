"""Tests for ``LedgerAgentGrantReader`` — v1.3 Task 1 Item #1.

The reader walks raw ledger entries with
``payload->>'tool' == 'emit_agent_grant'`` and folds them by the
canonical ``(agent_id, grant_kind, grant_target)`` triple keeping the
most-recent state. It then filters to ``status='active'`` so the gate
chain's ``grant_lookup`` consumer doesn't need its own filter.

These tests drive the reader with ``InMemoryLedger`` to stay
deployment-free; the same code path runs against Postgres in production
because both ledger surfaces expose the same row shape.

Test coverage:

* Active grants are returned for the matching agent.
* Revoked grants are filtered out.
* A grant assigned then revoked returns no rows for that agent.
* A grant revoked then re-assigned returns the re-assigned grant.
* Grants for a different agent are excluded.
* ``model.access`` grants carry ``budget_remaining_usd``.
* The reader composes with ``AgentAccessGate.grant_lookup`` via the
  closure factory.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from wormbase_agent_gateway.governance import AgentAccessGate
from wormbase_agent_gateway.identity import AgentGrant
from wormbase_core.agent_gateway_construction import _make_grant_lookup
from wormbase_core.agent_gateway_readers import LedgerAgentGrantReader
from wormbase_inference import AgentID
from wormbase_ledger import InMemoryLedger

TEST_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000abc")


def _verify_pass(_e: dict[str, Any]) -> dict[str, Any]:
    return {"checks": [], "passed": True}


def _resolve_keep(_v: dict[str, Any]) -> dict[str, Any]:
    return {"outcome": "keep", "rationale": "ok"}


async def _emit_grant(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    agent_id: str,
    grant_kind: str,
    grant_target: str,
    status: str,
    granted_by: str,
    budget_remaining_usd: str | None = None,
    timestamp: datetime | None = None,
) -> None:
    """Emit one ``emit_agent_grant`` PEVR cycle.

    Production writers use the same payload shape — see
    ``packages/ledger/tests/test_projection_builder_agents.py``.
    """
    args = {
        "agent_id": agent_id,
        "company_id": str(company_id),
        "grant_kind": grant_kind,
        "grant_target": grant_target,
        "status": status,
        "granted_by": granted_by,
        "budget_remaining_usd": budget_remaining_usd,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "agent_grant",
            "ref_id": agent_id,
            "reason": f"{status} {grant_kind} on {grant_target}",
            "proposed_by": granted_by,
        },
        execute_fn=lambda: {
            "tool": "emit_agent_grant",
            "args": args,
            "result_ref": agent_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Core fold semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_grant_returned() -> None:
    """A single active grant is returned for the matching agent."""
    ledger = InMemoryLedger()
    agent_id = str(uuid4())
    admin_id = str(uuid4())
    domain_id = str(uuid4())

    await _emit_grant(
        ledger,
        company_id=TEST_COMPANY_ID,
        agent_id=agent_id,
        grant_kind="domain.read",
        grant_target=domain_id,
        status="active",
        granted_by=admin_id,
    )

    reader = LedgerAgentGrantReader(ledger=ledger)
    grants = await reader.list_active_grants(
        company_id=TEST_COMPANY_ID,
        agent_id=AgentID(value=agent_id),
    )

    assert len(grants) == 1
    g = grants[0]
    assert g.agent_id == agent_id
    assert g.grant_kind == "domain.read"
    assert g.grant_target == domain_id
    assert g.status == "active"
    assert g.granted_by == admin_id


@pytest.mark.asyncio
async def test_revoked_grant_filtered_out() -> None:
    """A grant assigned and then revoked yields no active rows."""
    ledger = InMemoryLedger()
    agent_id = str(uuid4())
    admin_id = str(uuid4())
    domain_id = str(uuid4())

    first_ts = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)
    second_ts = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)

    await _emit_grant(
        ledger,
        company_id=TEST_COMPANY_ID,
        agent_id=agent_id,
        grant_kind="domain.read",
        grant_target=domain_id,
        status="active",
        granted_by=admin_id,
        timestamp=first_ts,
    )
    await _emit_grant(
        ledger,
        company_id=TEST_COMPANY_ID,
        agent_id=agent_id,
        grant_kind="domain.read",
        grant_target=domain_id,
        status="revoked",
        granted_by=admin_id,
        timestamp=second_ts,
    )

    reader = LedgerAgentGrantReader(ledger=ledger)
    grants = await reader.list_active_grants(
        company_id=TEST_COMPANY_ID,
        agent_id=AgentID(value=agent_id),
    )

    assert grants == []


@pytest.mark.asyncio
async def test_revoked_then_reassigned_returns_active() -> None:
    """A grant revoked and then re-assigned to the SAME triple is active again."""
    ledger = InMemoryLedger()
    agent_id = str(uuid4())
    admin_id = str(uuid4())
    domain_id = str(uuid4())

    t1 = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 15, 11, 0, tzinfo=UTC)
    t3 = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)

    await _emit_grant(
        ledger, company_id=TEST_COMPANY_ID, agent_id=agent_id,
        grant_kind="domain.read", grant_target=domain_id,
        status="active", granted_by=admin_id, timestamp=t1,
    )
    await _emit_grant(
        ledger, company_id=TEST_COMPANY_ID, agent_id=agent_id,
        grant_kind="domain.read", grant_target=domain_id,
        status="revoked", granted_by=admin_id, timestamp=t2,
    )
    await _emit_grant(
        ledger, company_id=TEST_COMPANY_ID, agent_id=agent_id,
        grant_kind="domain.read", grant_target=domain_id,
        status="active", granted_by=admin_id, timestamp=t3,
    )

    reader = LedgerAgentGrantReader(ledger=ledger)
    grants = await reader.list_active_grants(
        company_id=TEST_COMPANY_ID,
        agent_id=AgentID(value=agent_id),
    )
    assert len(grants) == 1
    assert grants[0].status == "active"


@pytest.mark.asyncio
async def test_other_agent_grants_excluded() -> None:
    """Grants for a different agent are not returned."""
    ledger = InMemoryLedger()
    agent_a = str(uuid4())
    agent_b = str(uuid4())
    admin_id = str(uuid4())
    domain_id = str(uuid4())

    await _emit_grant(
        ledger, company_id=TEST_COMPANY_ID, agent_id=agent_a,
        grant_kind="domain.read", grant_target=domain_id,
        status="active", granted_by=admin_id,
    )
    await _emit_grant(
        ledger, company_id=TEST_COMPANY_ID, agent_id=agent_b,
        grant_kind="domain.read", grant_target=domain_id,
        status="active", granted_by=admin_id,
    )

    reader = LedgerAgentGrantReader(ledger=ledger)
    a_grants = await reader.list_active_grants(
        company_id=TEST_COMPANY_ID, agent_id=AgentID(value=agent_a),
    )
    assert len(a_grants) == 1
    assert a_grants[0].agent_id == agent_a


@pytest.mark.asyncio
async def test_model_access_grant_carries_budget() -> None:
    """``model.access`` grants populate ``budget_remaining_usd``."""
    ledger = InMemoryLedger()
    agent_id = str(uuid4())
    admin_id = str(uuid4())

    await _emit_grant(
        ledger, company_id=TEST_COMPANY_ID, agent_id=agent_id,
        grant_kind="model.access", grant_target="kimi",
        status="active", granted_by=admin_id,
        budget_remaining_usd="42.50",
    )

    reader = LedgerAgentGrantReader(ledger=ledger)
    grants = await reader.list_active_grants(
        company_id=TEST_COMPANY_ID, agent_id=AgentID(value=agent_id),
    )

    assert len(grants) == 1
    g = grants[0]
    assert g.grant_kind == "model.access"
    assert g.grant_target == "kimi"
    assert g.budget_remaining_usd == Decimal("42.50")


# ---------------------------------------------------------------------------
# AgentAccessGate end-to-end via _make_grant_lookup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grant_lookup_factory_admits_with_active_grant() -> None:
    """``AgentAccessGate`` admits a tool call when the ledger has an active
    ``domain.read`` grant.
    """
    ledger = InMemoryLedger()
    agent_id = str(uuid4())
    admin_id = str(uuid4())
    domain_id = str(uuid4())

    await _emit_grant(
        ledger, company_id=TEST_COMPANY_ID, agent_id=agent_id,
        grant_kind="domain.read", grant_target=domain_id,
        status="active", granted_by=admin_id,
    )

    reader = LedgerAgentGrantReader(ledger=ledger)
    lookup = _make_grant_lookup(reader=reader, company_id=TEST_COMPANY_ID)
    gate = AgentAccessGate(grant_lookup=lookup)

    denial = await gate.check(
        agent_id=AgentID(value=agent_id),
        mcp_tool="lake.catalog.tables",
        args={},
    )
    assert denial is None


@pytest.mark.asyncio
async def test_grant_lookup_factory_denies_without_grant() -> None:
    """Without an active grant the gate denies the call."""
    ledger = InMemoryLedger()
    agent_id = str(uuid4())

    reader = LedgerAgentGrantReader(ledger=ledger)
    lookup = _make_grant_lookup(reader=reader, company_id=TEST_COMPANY_ID)
    gate = AgentAccessGate(grant_lookup=lookup)

    denial = await gate.check(
        agent_id=AgentID(value=agent_id),
        mcp_tool="lake.catalog.tables",
        args={},
    )
    assert denial is not None
    assert denial.gate_name == "agent_access"


@pytest.mark.asyncio
async def test_grant_lookup_factory_denies_after_revoke() -> None:
    """A revoked grant means the gate denies the call again."""
    ledger = InMemoryLedger()
    agent_id = str(uuid4())
    admin_id = str(uuid4())
    domain_id = str(uuid4())

    t1 = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)

    await _emit_grant(
        ledger, company_id=TEST_COMPANY_ID, agent_id=agent_id,
        grant_kind="domain.read", grant_target=domain_id,
        status="active", granted_by=admin_id, timestamp=t1,
    )
    await _emit_grant(
        ledger, company_id=TEST_COMPANY_ID, agent_id=agent_id,
        grant_kind="domain.read", grant_target=domain_id,
        status="revoked", granted_by=admin_id, timestamp=t2,
    )

    reader = LedgerAgentGrantReader(ledger=ledger)
    lookup = _make_grant_lookup(reader=reader, company_id=TEST_COMPANY_ID)
    gate = AgentAccessGate(grant_lookup=lookup)

    denial = await gate.check(
        agent_id=AgentID(value=agent_id),
        mcp_tool="lake.catalog.tables",
        args={},
    )
    assert denial is not None


@pytest.mark.asyncio
async def test_grant_lookup_factory_callable_signature() -> None:
    """The factory returns a callable matching the gate's grant_lookup type."""
    ledger = InMemoryLedger()
    reader = LedgerAgentGrantReader(ledger=ledger)
    lookup = _make_grant_lookup(reader=reader, company_id=TEST_COMPANY_ID)

    out = await lookup(AgentID(value="missing-agent"))
    assert list(out) == []  # Sequence -> empty list


@pytest.mark.asyncio
async def test_reader_dunder_call_requires_company_id_binding() -> None:
    """The reader's bare ``__call__`` raises without a bound tenant.

    Production wiring uses :func:`_make_grant_lookup` which closes over
    the company_id; the bare callable form is intentionally tenant-naive
    so accidental cross-tenant lookups are impossible.
    """
    ledger = InMemoryLedger()
    reader = LedgerAgentGrantReader(ledger=ledger)
    with pytest.raises(RuntimeError):
        await reader(AgentID(value="someone"))


@pytest.mark.asyncio
async def test_reader_returns_agentgrant_instances() -> None:
    """Returned objects are real :class:`AgentGrant` value types."""
    ledger = InMemoryLedger()
    agent_id = str(uuid4())
    admin_id = str(uuid4())
    domain_id = str(uuid4())

    await _emit_grant(
        ledger, company_id=TEST_COMPANY_ID, agent_id=agent_id,
        grant_kind="resource.maintainer", grant_target=domain_id,
        status="active", granted_by=admin_id,
    )

    reader = LedgerAgentGrantReader(ledger=ledger)
    grants = await reader.list_active_grants(
        company_id=TEST_COMPANY_ID, agent_id=AgentID(value=agent_id),
    )

    assert len(grants) == 1
    assert isinstance(grants[0], AgentGrant)
