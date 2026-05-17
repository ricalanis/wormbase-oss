"""Integration tests for the ``decisions.*`` MCP tool family (Wave 3.2 Hole #3).

Covers:

    1. The three dotted tool names are advertised
    2. ``decisions.list`` happy-path returns rows + emits PEVR audit
    3. ``decisions.get`` returns a single row by id
    4. ``decisions.search`` substring-matches over decision_text
    5. Gate-denial path lands a 4-entry denial PEVR
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastmcp import Client

from wormbase_agent_gateway.mcp_server import build_agent_gateway_mcp_server

from ._helpers import unwrap


pytestmark = pytest.mark.asyncio


DECISION_TOOL_NAMES = {"decisions.list", "decisions.get", "decisions.search"}


def _seed_decision(
    *,
    decision_id: str | None = None,
    decision_text: str,
    domain_id: str | None = None,
) -> dict:
    return {
        "decision_id": decision_id or str(uuid4()),
        "decision_text": decision_text,
        "decision_at": datetime.now(UTC).isoformat(),
        "channel_id": "C-test",
        "decided_by_persons": [str(uuid4())],
        "evidence_message_ids": ["msg-1", "msg-2"],
        "confidence": 0.85,
        "domain_id": domain_id,
    }


async def test_decisions_tools_advertised(gateway_deps_factory):
    """The 3 decisions.* tools register with the right dotted names."""
    harness = gateway_deps_factory()
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
    assert DECISION_TOOL_NAMES.issubset(names), (
        f"missing tools: {DECISION_TOOL_NAMES - names}"
    )


async def test_decisions_list_happy_path(gateway_deps_factory):
    """decisions.list returns seeded rows + lands a 4-entry PEVR audit cycle."""
    harness = gateway_deps_factory()
    d1 = _seed_decision(decision_text="push Q3 close to Friday")
    d2 = _seed_decision(decision_text="adopt OKR cadence")
    harness.decision_reader.rows = [d1, d2]

    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool("decisions.list", {"limit": 10})
    assert not result.is_error
    data = unwrap(result)
    assert data["row_count"] == 2
    assert {d["decision_text"] for d in data["decisions"]} == {
        "push Q3 close to Friday",
        "adopt OKR cadence",
    }
    audit_id = data["audit_trail_id"]
    assert audit_id

    # PEVR audit landed
    rows = await harness.ledger.fetch(harness.deps.company_id)
    matching = [
        r for r in rows if r["payload"].get("audit_trail_id") == audit_id
    ]
    kinds = [r["kind"] for r in matching]
    assert kinds == ["propose", "execute", "verify", "resolve"], (
        f"agent_query PEVR cycle should have all 4 envelope kinds; got {kinds}"
    )
    for r in matching:
        assert r["payload"]["mcp_tool"] == "decisions.list"
        assert r["payload"]["agent_id"] == harness.agent_id.value


async def test_decisions_list_filter_by_domain(gateway_deps_factory):
    """domain_id filter passes through to the reader."""
    harness = gateway_deps_factory()
    finance = _seed_decision(
        decision_text="defer audit fees", domain_id="finance",
    )
    product = _seed_decision(
        decision_text="ship feature flag", domain_id="product",
    )
    harness.decision_reader.rows = [finance, product]

    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "decisions.list", {"domain_id": "finance", "limit": 10},
        )
    data = unwrap(result)
    assert data["row_count"] == 1
    assert data["decisions"][0]["decision_text"] == "defer audit fees"


async def test_decisions_get_returns_single_row(gateway_deps_factory):
    """decisions.get fetches by decision_id; missing id returns null payload."""
    harness = gateway_deps_factory()
    target = _seed_decision(decision_text="dual-vendor strategy")
    harness.decision_reader.rows = [target]

    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "decisions.get", {"decision_id": target["decision_id"]},
        )
    data = unwrap(result)
    assert data["decision"] is not None
    assert data["decision"]["decision_text"] == "dual-vendor strategy"

    # missing id
    async with Client(server.mcp) as client:
        result_missing = await client.call_tool(
            "decisions.get", {"decision_id": str(uuid4())},
        )
    data_missing = unwrap(result_missing)
    assert data_missing["decision"] is None
    assert data_missing["audit_trail_id"]


async def test_decisions_search_substring_match(gateway_deps_factory):
    """decisions.search substring-matches case-insensitively."""
    harness = gateway_deps_factory()
    harness.decision_reader.rows = [
        _seed_decision(decision_text="adopt OKR cadence in Q4"),
        _seed_decision(decision_text="defer audit fees to Q1"),
    ]

    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "decisions.search", {"nl_question": "OKR", "limit": 5},
        )
    data = unwrap(result)
    assert len(data["matches"]) == 1
    assert "OKR" in data["matches"][0]["decision_text"]


async def test_decisions_denied_when_no_grant(gateway_deps_factory):
    """No active grant -> AgentAccessGate denial with 4-entry audit trail."""
    harness = gateway_deps_factory(grants=[])  # empty grants -> denial
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool("decisions.list", {"limit": 10})
    data = unwrap(result)
    assert data["status"] == "denied"
    assert data["gate_name"] == "agent_access"
    assert data["audit_trail_id"]

    rows = await harness.ledger.fetch(harness.deps.company_id)
    audit_rows = [
        r for r in rows
        if r["payload"].get("audit_trail_id") == data["audit_trail_id"]
    ]
    assert len(audit_rows) == 4, (
        f"denied call must still land 4 PEVR entries; got {len(audit_rows)}"
    )
