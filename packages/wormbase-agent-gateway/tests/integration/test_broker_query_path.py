"""Broker query path — lake.semantic.metric end-to-end with PEVR audit.

Asserts:
    1. Pre-seeded metric resolves via QuerySpec validate+plan+compile.
    2. The injected snowflake driver receives the compiled SQL.
    3. The response carries the audit_trail_id + row_count.
    4. The ledger holds exactly 4 entries for the agent_query PEVR
       cycle, all keyed on the same audit_trail_id.
"""
from __future__ import annotations

import pytest
from fastmcp import Client

from wormbase_agent_gateway.mcp_server import build_agent_gateway_mcp_server

from ._helpers import unwrap


pytestmark = pytest.mark.asyncio


async def test_lake_semantic_metric_full_pevr(gateway_deps_factory):
    harness = gateway_deps_factory()
    # Seed a metric and its source table.
    harness.catalog_client.metrics["weekly_revenue"] = {
        "name": "weekly_revenue",
        "source_table_id": "tbl-rev-001",
        "source_kind": "snowflake",
        "expression": "SUM(amount)",
    }
    harness.catalog_client.tables["tbl-rev-001"] = {
        "name": "ANALYTICS.MART.REVENUE",
        "external_id": "tbl-rev-001",
        "upstream_kind": "snowflake",
        "columns": [{"name": "amount"}, {"name": "region"}],
    }
    # Seed the driver's canned rows.
    harness.driver.rows = [
        {"weekly_revenue": 4_200_000},
        {"weekly_revenue": 4_350_000},
    ]

    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "lake.semantic.metric",
            {"name": "weekly_revenue", "filter": {"region": "EMEA"}},
        )
    assert not result.is_error
    data = unwrap(result)
    audit_id = data["audit_trail_id"]
    assert data["row_count"] == 2
    assert data["metric_name"] == "weekly_revenue"
    assert data["sample_rows_hash"]

    # Driver should have seen the compiled SQL with parameter binding.
    assert harness.driver.last_call is not None
    assert "SELECT" in harness.driver.last_call["sql"]
    assert harness.driver.last_call["params"] == ["EMEA"]

    # Ledger: count entries belonging to the agent_query PEVR cycle.
    rows = await harness.ledger.fetch(harness.deps.company_id)
    matching = [
        r for r in rows
        if r["payload"].get("audit_trail_id") == audit_id
    ]
    kinds = [r["kind"] for r in matching]
    assert kinds == ["propose", "execute", "verify", "resolve"], (
        f"agent_query PEVR cycle should have all 4 envelope kinds; got {kinds}"
    )

    # Every phase entry carries mcp_tool="lake.semantic.metric".
    for r in matching:
        assert r["payload"]["mcp_tool"] == "lake.semantic.metric"
        assert r["payload"]["route_mode"] == "broker"


async def test_denied_when_agent_lacks_grant(gateway_deps_factory):
    """When the agent has no active read grant, the call returns a DeniedResponse."""
    # Empty grants list -> AgentAccessGate denial.
    harness = gateway_deps_factory(grants=[])
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "lake.semantic.metric",
            {"name": "weekly_revenue"},
        )
    assert not result.is_error
    data = unwrap(result)
    assert data["status"] == "denied"
    assert data["gate_name"] == "agent_access"
    assert data["audit_trail_id"]

    # Audit row should land even on denial.
    rows = await harness.ledger.fetch(harness.deps.company_id)
    audit_rows = [
        r for r in rows
        if r["payload"].get("audit_trail_id") == data["audit_trail_id"]
    ]
    assert len(audit_rows) == 4, (
        f"denied call must still land 4 PEVR entries; got {len(audit_rows)}"
    )
