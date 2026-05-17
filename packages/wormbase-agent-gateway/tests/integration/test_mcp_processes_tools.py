"""Integration tests for the ``processes.*`` MCP tool family (Wave 3.2 Hole #3).

Covers:

    1. Both dotted tool names are advertised
    2. ``processes.list`` happy-path returns rows + emits PEVR audit
    3. ``processes.get`` returns a single row by process_map_id
    4. Gate-denial path lands a 4-entry denial PEVR
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastmcp import Client

from wormbase_agent_gateway.mcp_server import build_agent_gateway_mcp_server

from ._helpers import unwrap


pytestmark = pytest.mark.asyncio


PROCESS_TOOL_NAMES = {"processes.list", "processes.get"}


def _seed_process_map(
    *,
    process_id: str | None = None,
    process_name: str,
    domain: str = "general",
    domain_id: str | None = None,
    steps: list | None = None,
) -> dict:
    return {
        "process_id": process_id or str(uuid4()),
        "process_name": process_name,
        "domain": domain,
        "confidence": 0.78,
        "steps": steps if steps is not None else [
            {"order": 1, "actor": "Bob", "action": "export", "source_message_id": "m-1"},
            {"order": 2, "actor": "Alice", "action": "review", "source_message_id": "m-2"},
        ],
        "proposed_at": datetime.now(UTC).isoformat(),
        "domain_id": domain_id,
    }


async def test_processes_tools_advertised(gateway_deps_factory):
    """The 2 processes.* tools register with the right dotted names."""
    harness = gateway_deps_factory()
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
    assert PROCESS_TOOL_NAMES.issubset(names), (
        f"missing tools: {PROCESS_TOOL_NAMES - names}"
    )


async def test_processes_list_happy_path(gateway_deps_factory):
    """processes.list returns seeded rows + lands 4-entry PEVR audit cycle."""
    harness = gateway_deps_factory()
    p1 = _seed_process_map(process_name="Q3 close")
    p2 = _seed_process_map(process_name="release approval", domain="product")
    harness.process_map_reader.rows = [p1, p2]

    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool("processes.list", {"limit": 10})
    assert not result.is_error
    data = unwrap(result)
    assert data["row_count"] == 2
    names = {p["process_name"] for p in data["processes"]}
    assert names == {"Q3 close", "release approval"}
    audit_id = data["audit_trail_id"]
    assert audit_id

    # PEVR audit landed
    rows = await harness.ledger.fetch(harness.deps.company_id)
    matching = [
        r for r in rows if r["payload"].get("audit_trail_id") == audit_id
    ]
    kinds = [r["kind"] for r in matching]
    assert kinds == ["propose", "execute", "verify", "resolve"]
    for r in matching:
        assert r["payload"]["mcp_tool"] == "processes.list"


async def test_processes_get_returns_single_row(gateway_deps_factory):
    """processes.get fetches by process_id; missing id returns null payload."""
    harness = gateway_deps_factory()
    target = _seed_process_map(process_name="P&L review")
    harness.process_map_reader.rows = [target]

    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "processes.get", {"process_map_id": target["process_id"]},
        )
    data = unwrap(result)
    assert data["process_map"] is not None
    assert data["process_map"]["process_name"] == "P&L review"
    assert len(data["process_map"]["steps"]) == 2


async def test_processes_get_missing_returns_null(gateway_deps_factory):
    """missing process_map_id returns null payload but still audits."""
    harness = gateway_deps_factory()
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "processes.get", {"process_map_id": str(uuid4())},
        )
    data = unwrap(result)
    assert data["process_map"] is None
    assert data["audit_trail_id"]


async def test_processes_denied_when_no_grant(gateway_deps_factory):
    """No active grant -> AgentAccessGate denial."""
    harness = gateway_deps_factory(grants=[])
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool("processes.list", {"limit": 10})
    data = unwrap(result)
    assert data["status"] == "denied"
    assert data["gate_name"] == "agent_access"
    assert data["audit_trail_id"]

    rows = await harness.ledger.fetch(harness.deps.company_id)
    audit_rows = [
        r for r in rows
        if r["payload"].get("audit_trail_id") == data["audit_trail_id"]
    ]
    assert len(audit_rows) == 4
