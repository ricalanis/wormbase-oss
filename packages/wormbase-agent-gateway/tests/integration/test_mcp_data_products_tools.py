"""Integration tests for the ``data_products.*`` MCP tool family (Wave 3.2 Hole #3).

Covers:

    1. The three dotted tool names are advertised
    2. ``data_products.list`` happy-path returns rows + emits PEVR audit
    3. ``data_products.get`` returns a single row by id
    4. ``data_products.consume`` lands TWO PEVR cycles:
       - The agent_query envelope wrapping the tool call
       - The chained ``emit_data_product_consumed`` PEVR carrying
         ``caused_by`` back to the audit_trail_id
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


DATA_PRODUCT_TOOL_NAMES = {
    "data_products.list",
    "data_products.get",
    "data_products.consume",
}


def _seed_data_product(
    *,
    data_product_id: str | None = None,
    name: str,
    kind: str = "chart",
    status: str = "generated",
    domain_id: str | None = None,
) -> dict:
    return {
        "data_product_id": data_product_id or str(uuid4()),
        "name": name,
        "kind": kind,
        "status": status,
        "requested_by_person_id": str(uuid4()),
        "domain_id": domain_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "content_hash": "a" * 64,
        "contents_uri": f"lake://gold/{name}.parquet",
    }


async def test_data_products_tools_advertised(gateway_deps_factory):
    """All 3 data_products.* tools register with the right dotted names."""
    harness = gateway_deps_factory()
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
    assert DATA_PRODUCT_TOOL_NAMES.issubset(names), (
        f"missing tools: {DATA_PRODUCT_TOOL_NAMES - names}"
    )


async def test_data_products_list_happy_path(gateway_deps_factory):
    """data_products.list returns seeded rows + lands a 4-entry PEVR audit."""
    harness = gateway_deps_factory()
    dp1 = _seed_data_product(name="weekly-revenue", kind="chart")
    dp2 = _seed_data_product(name="q3-forecast", kind="table")
    harness.data_product_reader.rows = [dp1, dp2]

    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool("data_products.list", {"limit": 10})
    assert not result.is_error
    data = unwrap(result)
    assert data["row_count"] == 2
    audit_id = data["audit_trail_id"]
    assert audit_id

    rows = await harness.ledger.fetch(harness.deps.company_id)
    matching = [
        r for r in rows if r["payload"].get("audit_trail_id") == audit_id
    ]
    kinds = [r["kind"] for r in matching]
    assert kinds == ["propose", "execute", "verify", "resolve"]
    for r in matching:
        assert r["payload"]["mcp_tool"] == "data_products.list"


async def test_data_products_list_filter_by_status(gateway_deps_factory):
    """status filter passes through to the reader."""
    harness = gateway_deps_factory()
    harness.data_product_reader.rows = [
        _seed_data_product(name="active-dp", status="generated"),
        _seed_data_product(name="old-dp", status="archived"),
    ]
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "data_products.list", {"status": "generated", "limit": 10},
        )
    data = unwrap(result)
    assert data["row_count"] == 1
    assert data["data_products"][0]["name"] == "active-dp"


async def test_data_products_get_returns_single_row(gateway_deps_factory):
    """data_products.get fetches by id; missing id returns null payload."""
    harness = gateway_deps_factory()
    target = _seed_data_product(name="cohort-retention")
    harness.data_product_reader.rows = [target]

    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "data_products.get",
            {"data_product_id": target["data_product_id"]},
        )
    data = unwrap(result)
    assert data["data_product"] is not None
    assert data["data_product"]["name"] == "cohort-retention"


async def test_data_products_consume_chains_emit_consumed(gateway_deps_factory):
    """data_products.consume emits two PEVR cycles:

    - The agent_query envelope wrapping the consume call itself
    - A chained ``data_product_consumed`` PEVR carrying caused_by
      back to the audit_trail_id

    Verifies the chain is reconstructable from the ledger alone.
    """
    harness = gateway_deps_factory()
    target = _seed_data_product(name="q3-board-deck")
    harness.data_product_reader.rows = [target]

    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "data_products.consume",
            {
                "data_product_id": target["data_product_id"],
                "surface": "agent",
                "channel": None,
            },
        )
    assert not result.is_error
    data = unwrap(result)
    audit_id = data["audit_trail_id"]
    assert audit_id
    assert data["data_product_id"] == target["data_product_id"]
    assert data["consumed_by_agent_id"] == harness.agent_id.value

    rows = await harness.ledger.fetch(harness.deps.company_id)

    # 1) The agent_query envelope (PEVR) for the tool call
    audit_rows = [
        r for r in rows if r["payload"].get("audit_trail_id") == audit_id
    ]
    kinds = [r["kind"] for r in audit_rows]
    assert kinds == ["propose", "execute", "verify", "resolve"], (
        f"agent_query envelope should have all 4 phases; got {kinds}"
    )
    for r in audit_rows:
        assert r["payload"]["mcp_tool"] == "data_products.consume"

    # 2) The chained data_product_consumed PEVR — propose carries
    # caused_by + target_kind; execute carries tool=emit_data_product_consumed.
    consumed_propose = [
        r for r in rows
        if r["kind"] == "propose"
        and r["payload"].get("target_kind") == "data_product_consumed"
        and r["payload"].get("caused_by") == audit_id
    ]
    assert len(consumed_propose) == 1, (
        f"expected 1 propose for data_product_consumed chained to {audit_id}; "
        f"got {len(consumed_propose)}"
    )

    consumed_execute = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_data_product_consumed"
    ]
    assert len(consumed_execute) == 1
    consume_args = consumed_execute[0]["payload"]["args"]
    assert consume_args["data_product_id"] == target["data_product_id"]
    # v1.1 Task 4: both consumed_by_person_id (back-compat, required by
    # canonical payload) and consumed_by_agent_id (new, additive) must
    # land in the execute args so the data_product_consumption
    # projection can fold the entry and downstream readers can
    # distinguish agent-driven consumption.
    assert consume_args["consumed_by_person_id"] == harness.agent_id.value
    assert consume_args["consumed_by_agent_id"] == harness.agent_id.value
    assert consume_args["surface"] == "agent"


async def test_data_products_denied_when_no_grant(gateway_deps_factory):
    """No active grant -> AgentAccessGate denial on data_products.list."""
    harness = gateway_deps_factory(grants=[])
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool("data_products.list", {"limit": 10})
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


async def test_data_products_consume_denied_does_not_emit_chained(
    gateway_deps_factory,
):
    """Denied consume must NOT emit a chained data_product_consumed entry.

    The gate fires BEFORE the write — only the denial-audit PEVR should
    land.
    """
    harness = gateway_deps_factory(grants=[])
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "data_products.consume",
            {"data_product_id": str(uuid4()), "surface": "agent"},
        )
    data = unwrap(result)
    assert data["status"] == "denied"

    rows = await harness.ledger.fetch(harness.deps.company_id)
    consumed_execute = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_data_product_consumed"
    ]
    assert consumed_execute == [], (
        "denied consume must not emit a chained data_product_consumed entry"
    )
