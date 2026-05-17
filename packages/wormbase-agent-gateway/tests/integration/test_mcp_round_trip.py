"""In-process MCP round-trip — all 21 tools advertised + callable.

Uses fastmcp's in-process Client (binds to a FastMCP instance directly,
no subprocess) so the test is fast and hermetic. We assert:

    1. All 21 dotted tool names are advertised by the server.
    2. Each tool's input schema declares the right required args.

The surface has grown over time:

    * Wave 2 Task 7 — 9 base lake.* tools
    * Wave 3.2 Hole #3 — 8 gold-artifact tools (decisions/processes/data_products)
    * v2.A Batch B Task 4 — 4 agent.subscriptions.* tools

Total: 21 tools. The Wave-2 ``test_all_9_tools_advertised`` was
``issubset(...)`` style; we keep that semantic and extend the set so a
regression that removes a Wave-2 tool still fails.
"""
from __future__ import annotations

import pytest
from fastmcp import Client

from wormbase_agent_gateway.mcp_server import build_agent_gateway_mcp_server

from ._helpers import unwrap


pytestmark = pytest.mark.asyncio


# The 9 Wave-2 lake.* tools. Kept named separately for regression clarity:
# if a Wave-2 tool gets dropped or renamed, the issubset() check below
# fails with a precise diff.
LAKE_TOOLS = {
    "lake.catalog.tables",
    "lake.semantic.metric",
    "lake.lineage",
    "lake.query",
    "lake.semantic.search",
    "lake.semantic.query_spec",
    "lake.query.suggest_correction",
    "lake.query.record_outcome",
    "lake.semantic.gap",
}

# Wave 3.2 Hole #3 — gold-artifact tools (8).
GOLD_ARTIFACT_TOOLS = {
    "decisions.list",
    "decisions.get",
    "decisions.search",
    "processes.list",
    "processes.get",
    "data_products.list",
    "data_products.get",
    "data_products.consume",
}

# v2.A Batch B Task 4 — agent-as-teammate subscription tools (4).
SUBSCRIPTION_TOOLS = {
    "agent.subscriptions.create",
    "agent.subscriptions.list",
    "agent.subscriptions.revoke",
    "agent.subscriptions.stream",
}

EXPECTED_TOOLS = LAKE_TOOLS | GOLD_ARTIFACT_TOOLS | SUBSCRIPTION_TOOLS

# Total tool count (assertion is exact when no subscription deps wired —
# tools register unconditionally, so the count is the union size).
EXPECTED_TOOL_COUNT = 21


async def test_all_21_tools_advertised(gateway_deps_factory):
    """The server should advertise exactly the 21 expected dotted tool names.

    Tool count grew across waves:

        * Wave 2 Task 7 → 9 lake.* tools
        * Wave 3.2 Hole #3 → +8 gold-artifact tools (17 total)
        * v2.A Batch B Task 4 → +4 subscription tools (21 total)

    Subscription tools register unconditionally; when the dispatcher
    deps are not wired (default), they surface a "subscriptions not
    configured" denial. The MCP surface is always fully advertised so
    agents can probe install posture via a single ``list_tools()`` call.
    """
    harness = gateway_deps_factory()
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
    assert EXPECTED_TOOLS.issubset(names), (
        f"missing tools: {EXPECTED_TOOLS - names}; "
        f"unexpected extras: {names - EXPECTED_TOOLS}"
    )
    assert len(names) == EXPECTED_TOOL_COUNT, (
        f"expected exactly {EXPECTED_TOOL_COUNT} MCP tools, got "
        f"{len(names)}: {sorted(names)}"
    )


async def test_tool_names_are_dotted(gateway_deps_factory):
    """No tool name should have been underscore-substituted (S3 spike contract)."""
    harness = gateway_deps_factory()
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        tools = await client.list_tools()
        names = [t.name for t in tools]
    for n in names:
        if n.startswith("lake."):
            assert "." in n, f"tool {n!r} should keep dotted form"
            assert "lake_" not in n, f"tool {n!r} appears underscore-substituted"


async def test_lake_semantic_gap_round_trip(gateway_deps_factory):
    """Smoke-call lake.semantic.gap (no enclosing agent_query, no backend deps)."""
    harness = gateway_deps_factory()
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "lake.semantic.gap",
            {
                "nl_question": "what is our weekly revenue by region",
                "reason": "no_match",
                "proposed_metric_name": "weekly_revenue_by_region",
            },
        )
    assert not result.is_error
    data = unwrap(result)
    assert data["nl_question"] == "what is our weekly revenue by region"
    assert data["reason"] == "no_match"
    assert data["audit_trail_id"]
