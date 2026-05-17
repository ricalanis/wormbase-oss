"""Unit tests for ``identity/audit.py`` — agent_query_pevr single-kind PEVR helper.

Per doctrine Addendum 3 §C: the helper writes ONE entry kind (``agent_query``)
across FOUR phases via ``Ledger.write(propose=, execute_fn=, verify_fn=,
resolve_fn=)``. The InMemoryLedger appends entries with envelope-kind
propose/execute/verify/resolve; the agent_query semantics live in the payload.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from wormbase_agent_gateway.identity import agent_query_pevr
from wormbase_inference import AgentID
from wormbase_ledger.ledger_api import InMemoryLedger


@pytest.mark.asyncio
async def test_agent_query_pevr_writes_four_phase_cycle() -> None:
    """One agent_query_pevr call produces exactly 4 envelope entries — one
    per PEVR phase — all sharing a single audit_trail_id."""
    ledger = InMemoryLedger()
    company_id = uuid4()
    agent = AgentID.from_legacy_string("agent-uuid-1")

    def _exec() -> dict:
        return {
            "result_ref": "row-batch://1",
            "row_count": 2,
            "cost_usd": "0.013",
            "latency_ms": 420,
        }

    audit_trail_id = await agent_query_pevr(
        ledger=ledger,
        company_id=company_id,
        agent_id=agent,
        mcp_tool="lake.semantic.metric",
        args={"name": "revenue_q3", "filter": {"region": "EMEA"}},
        route_mode="broker",
        execute_fn=_exec,
    )

    entries = await ledger.fetch(company_id)
    assert len(entries) == 4
    kinds = [e["kind"] for e in entries]
    assert kinds == ["propose", "execute", "verify", "resolve"]

    # Every payload carries the SAME audit_trail_id (cycle correlation key).
    audit_ids = {e["payload"]["audit_trail_id"] for e in entries}
    assert audit_ids == {audit_trail_id}

    # AgentQueryPayload semantics flow through every phase.
    for e in entries:
        p = e["payload"]
        assert p["agent_id"] == "agent-uuid-1"
        assert p["mcp_tool"] == "lake.semantic.metric"
        assert p["route_mode"] == "broker"
        assert p["args"] == {"name": "revenue_q3", "filter": {"region": "EMEA"}}

    # Phase-discriminator (in payload) tracks the envelope kind.
    phases = [e["payload"]["phase"] for e in entries]
    assert phases == ["propose", "execute", "verify", "resolve"]

    # Execute / verify / resolve carry measurement fields surfaced by execute_fn.
    exec_payload = entries[1]["payload"]
    assert exec_payload["row_count"] == 2
    assert exec_payload["cost_usd"] == "0.013"
    assert exec_payload["latency_ms"] == 420
    assert exec_payload["result_ref"] == "row-batch://1"


@pytest.mark.asyncio
async def test_agent_query_pevr_default_verify_passes() -> None:
    """When verify_fn is None, the helper installs a permissive verify so
    the resolve outcome is "keep"."""
    ledger = InMemoryLedger()
    company_id = uuid4()
    agent = AgentID.from_legacy_string("a")
    await agent_query_pevr(
        ledger=ledger,
        company_id=company_id,
        agent_id=agent,
        mcp_tool="lake.semantic.metric",
        args={},
        route_mode="federate",
        execute_fn=lambda: {"result_ref": "_"},
    )
    entries = await ledger.fetch(company_id)
    resolve = entries[3]["payload"]
    assert resolve["outcome"] == "keep"


@pytest.mark.asyncio
async def test_agent_query_pevr_caused_by_chains_cycles() -> None:
    """caused_by threads through every phase payload so chain analysis on
    projection_agent_queries can walk parent→child."""
    ledger = InMemoryLedger()
    company_id = uuid4()
    agent = AgentID.from_legacy_string("a")
    parent_audit_id = "parent-audit-trail-uuid"
    await agent_query_pevr(
        ledger=ledger,
        company_id=company_id,
        agent_id=agent,
        mcp_tool="lake.semantic.metric",
        args={"retry": True},
        route_mode="broker",
        execute_fn=lambda: {"result_ref": "_"},
        caused_by=parent_audit_id,
    )
    entries = await ledger.fetch(company_id)
    for e in entries:
        assert e["payload"]["caused_by"] == parent_audit_id
