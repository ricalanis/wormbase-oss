"""Integration tests — agent.subscriptions.* MCP tools (v2.A Task 4).

Six tests covering:

1. create round-trip — entry lands in ledger; response carries subscription_id.
2. create rejects cross-agent registration.
3. list returns only the calling agent's active subs.
4. revoke writes the entry + clears the stream queue.
5. revoke rejects cross-agent.
6. tools surface "not configured" when subscription_tool_deps is None.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastmcp import Client

from wormbase_agent_gateway.mcp_server import build_agent_gateway_mcp_server
from wormbase_agent_gateway.subscriptions.mcp_tools import SubscriptionToolDeps
from wormbase_agent_gateway.subscriptions.stream_registry import StreamRegistry

from ._helpers import unwrap


pytestmark = pytest.mark.asyncio


class _LedgerBackedReader:
    """Wraps the test ledger to satisfy SubscriptionReader.

    Uses the same fold logic as the production LedgerSubscriptionReader
    so the MCP-tool round-trip (create writes → list reads) sees the
    just-created subscription immediately.
    """

    def __init__(self, ledger: Any) -> None:
        self._ledger = ledger

    async def active_subscriptions(
        self, company_id: UUID,
    ) -> list[dict[str, Any]]:
        entries = await self._ledger.fetch(company_id)
        revoked: set[str] = set()
        created: dict[str, dict[str, Any]] = {}
        for entry in entries:
            if entry.get("kind") != "execute":
                continue
            payload = entry.get("payload") or {}
            tool = payload.get("tool")
            args = payload.get("args") or {}
            sub_id = str(args.get("subscription_id") or "")
            if not sub_id:
                continue
            if tool == "emit_agent_subscription_created":
                created[sub_id] = {
                    "subscription_id": sub_id,
                    "agent_id": str(args.get("agent_id") or ""),
                    "filter": dict(args.get("filter") or {}),
                    "transport": str(args.get("transport") or ""),
                    "webhook_url": args.get("webhook_url"),
                    "webhook_secret_ref": args.get("webhook_secret_ref"),
                    "description": args.get("description"),
                    "created_seq": int(entry.get("seq", 0) or 0),
                }
            elif tool == "emit_agent_subscription_revoked":
                revoked.add(sub_id)
        return [row for sid, row in created.items() if sid not in revoked]


def _wire_subscription_deps(harness) -> StreamRegistry:
    """Helper — wire SubscriptionToolDeps onto harness.deps and return the registry."""
    reader = _LedgerBackedReader(harness.ledger)
    stream_registry = StreamRegistry()
    harness.deps.subscription_tool_deps = SubscriptionToolDeps(
        ledger=harness.ledger,
        company_id=harness.deps.company_id,
        subscription_reader=reader,
        stream_registry=stream_registry,
    )
    return stream_registry


async def test_create_round_trip(gateway_deps_factory):
    """Test 1: create writes the entry; response carries subscription_id."""
    harness = gateway_deps_factory()
    _wire_subscription_deps(harness)
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "agent.subscriptions.create",
            {
                "agent_id": harness.agent_id.value,
                "filter": {"kinds": ["bad_pattern_proposed"]},
                "transport": "mcp_stream",
                "description": "MY bad-pattern alerts",
            },
        )
    assert not result.is_error
    data = unwrap(result)
    assert data["subscription_id"]
    assert data["agent_id"] == harness.agent_id.value
    assert data["transport"] == "mcp_stream"

    # Ledger has the create entry.
    rows = await harness.ledger.fetch(harness.deps.company_id)
    create_rows = [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool")
        == "emit_agent_subscription_created"
    ]
    assert len(create_rows) == 1


async def test_create_rejects_cross_agent(gateway_deps_factory):
    """Test 2: create denies when agent_id != calling agent."""
    harness = gateway_deps_factory()
    _wire_subscription_deps(harness)
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "agent.subscriptions.create",
            {
                "agent_id": "some-other-agent",
                "filter": {"kinds": ["bad_pattern_proposed"]},
                "transport": "mcp_stream",
            },
        )
    assert not result.is_error
    data = unwrap(result)
    assert data["status"] == "denied"
    assert "may not create subscriptions" in data["reason"]


async def test_list_returns_only_calling_agent_subs(gateway_deps_factory):
    """Test 3: list returns the calling agent's active subscriptions."""
    harness = gateway_deps_factory()
    _wire_subscription_deps(harness)
    server = build_agent_gateway_mcp_server(harness.deps)

    async with Client(server.mcp) as client:
        # Create 2 subscriptions for the calling agent.
        for description in ("alert A", "alert B"):
            await client.call_tool(
                "agent.subscriptions.create",
                {
                    "agent_id": harness.agent_id.value,
                    "filter": {"kinds": ["bad_pattern_proposed"]},
                    "transport": "mcp_stream",
                    "description": description,
                },
            )
        # List.
        result = await client.call_tool(
            "agent.subscriptions.list",
            {"agent_id": harness.agent_id.value},
        )
    assert not result.is_error
    data = unwrap(result)
    assert len(data["subscriptions"]) == 2
    descriptions = {s.get("description") for s in data["subscriptions"]}
    assert descriptions == {"alert A", "alert B"}


async def test_revoke_writes_entry_clears_queue(gateway_deps_factory):
    """Test 4: revoke writes the revocation entry + clears the stream queue."""
    harness = gateway_deps_factory()
    registry = _wire_subscription_deps(harness)
    server = build_agent_gateway_mcp_server(harness.deps)

    async with Client(server.mcp) as client:
        # Create.
        create_result = await client.call_tool(
            "agent.subscriptions.create",
            {
                "agent_id": harness.agent_id.value,
                "filter": {"kinds": ["bad_pattern_proposed"]},
                "transport": "mcp_stream",
            },
        )
        sub_id = unwrap(create_result)["subscription_id"]
        # Pre-populate the queue (simulate an in-flight delivery).
        await registry.push(sub_id, {"event": "test"})
        assert registry.size(sub_id) == 1

        # Revoke.
        revoke_result = await client.call_tool(
            "agent.subscriptions.revoke",
            {"subscription_id": sub_id, "reason": "agent_request"},
        )
    data = unwrap(revoke_result)
    assert data["revoked"] is True
    assert data["subscription_id"] == sub_id

    # Ledger has the revoke entry.
    rows = await harness.ledger.fetch(harness.deps.company_id)
    revoke_rows = [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool")
        == "emit_agent_subscription_revoked"
    ]
    assert len(revoke_rows) == 1

    # Queue cleared.
    assert registry.size(sub_id) == 0


async def test_revoke_rejects_cross_agent(gateway_deps_factory):
    """Test 5: revoke denies when the caller doesn't own the subscription."""
    # Create as agent-A.
    harness_a = gateway_deps_factory(agent_id_value="agent-a")
    registry = _wire_subscription_deps(harness_a)
    server_a = build_agent_gateway_mcp_server(harness_a.deps)
    async with Client(server_a.mcp) as client:
        result = await client.call_tool(
            "agent.subscriptions.create",
            {
                "agent_id": "agent-a",
                "filter": {"kinds": ["bad_pattern_proposed"]},
                "transport": "mcp_stream",
            },
        )
        sub_id = unwrap(result)["subscription_id"]

    # Try to revoke as agent-B (same ledger, same registry).
    harness_b = gateway_deps_factory(
        company_id=harness_a.deps.company_id,
        agent_id_value="agent-b",
    )
    # Reuse the same ledger so agent-b sees agent-a's subscription.
    harness_b.deps.ledger = harness_a.ledger
    harness_b.deps.subscription_tool_deps = SubscriptionToolDeps(
        ledger=harness_a.ledger,
        company_id=harness_a.deps.company_id,
        subscription_reader=_LedgerBackedReader(harness_a.ledger),
        stream_registry=registry,
    )
    server_b = build_agent_gateway_mcp_server(harness_b.deps)
    async with Client(server_b.mcp) as client:
        result = await client.call_tool(
            "agent.subscriptions.revoke",
            {"subscription_id": sub_id},
        )
    data = unwrap(result)
    assert data["status"] == "denied"
    assert "does not own" in data["reason"]


async def test_tools_surface_not_configured_when_deps_missing(gateway_deps_factory):
    """Test 6: each tool returns a clear denial when subscription_tool_deps is None."""
    harness = gateway_deps_factory()
    # Deliberately do NOT wire subscription_tool_deps.
    assert harness.deps.subscription_tool_deps is None
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        for tool_name, params in (
            (
                "agent.subscriptions.create",
                {
                    "agent_id": harness.agent_id.value,
                    "filter": {"kinds": ["bad_pattern_proposed"]},
                    "transport": "mcp_stream",
                },
            ),
            ("agent.subscriptions.list", {"agent_id": harness.agent_id.value}),
            (
                "agent.subscriptions.revoke",
                {"subscription_id": "some-id", "reason": "agent_request"},
            ),
        ):
            result = await client.call_tool(tool_name, params)
            data = unwrap(result)
            assert data["status"] == "denied", (
                f"tool {tool_name!r} did not surface denial: {data!r}"
            )
            assert "not configured" in data["reason"]
