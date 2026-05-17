"""Federate query path — lake.query issues a ScopedDataToken.

Asserts:
    1. The federate path returns sql + token_id + callback_url.
    2. The broker can validate the issued token (is_valid==True).
    3. A `credential` ledger entry lands with status="active".
    4. The agent_query PEVR cycle carries route_mode="federate".
"""
from __future__ import annotations

import pytest
from fastmcp import Client

from wormbase_agent_gateway.mcp_server import build_agent_gateway_mcp_server

from ._helpers import unwrap


pytestmark = pytest.mark.asyncio


async def test_lake_query_issues_scoped_token(gateway_deps_factory):
    harness = gateway_deps_factory()
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "lake.query",
            {
                "sql": "SELECT 1 AS smoke FROM ANALYTICS.MART.REVENUE LIMIT 1",
                "resource_id": "tbl-rev-001",
                "scope_token": None,
            },
        )
    assert not result.is_error
    data = unwrap(result)
    assert data["sql"].startswith("SELECT")
    assert data["token_id"]
    assert data["callback_url"].endswith(data["token_id"])

    # The broker should recognize the token as valid.
    is_valid = await harness.broker.is_valid(data["token_id"])
    assert is_valid is True

    # The agent_query trail should carry route_mode="federate".
    rows = await harness.ledger.fetch(harness.deps.company_id)
    aq_rows = [
        r for r in rows
        if r["payload"].get("audit_trail_id") == data["audit_trail_id"]
    ]
    assert all(r["payload"]["route_mode"] == "federate" for r in aq_rows), (
        "every PEVR entry must carry route_mode=federate"
    )
    assert [r["kind"] for r in aq_rows] == [
        "propose", "execute", "verify", "resolve",
    ]

    # A `credential` ledger entry should also land.
    cred_propose_entries = [
        r for r in rows
        if r["kind"] == "propose"
        and r["payload"].get("credential_kind") == "data"
        and r["payload"].get("status") == "active"
    ]
    assert len(cred_propose_entries) >= 1, (
        "lake.query should emit at least one credential ledger entry"
    )
    assert (
        cred_propose_entries[0]["payload"].get("target") == "tbl-rev-001"
    )
