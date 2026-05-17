"""Integration tests — agent.subscriptions.stream MCP tool (v2.A Task 4).

Four tests covering the SSE-style long-poll generator and ledger-replay
resumption:

1. Stream returns queued events for the calling agent.
2. Resumption (since_seq) replays agent_event_delivered entries.
3. Stream denies when the caller doesn't own the subscription.
4. Stream surfaces "not configured" when subscription_tool_deps is None.

The stream() generator's live-tail mode would block on
``asyncio.Queue.get()`` indefinitely, so these tests exercise the
finite path: pre-queued events drain on the first poll, then the
list-mode wrapper returns immediately when the queue is empty.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastmcp import Client

from wormbase_agent_gateway.mcp_server import build_agent_gateway_mcp_server
from wormbase_agent_gateway.subscriptions.mcp_tools import SubscriptionToolDeps

from ._helpers import unwrap
from .test_subscription_mcp_tools import _LedgerBackedReader, _wire_subscription_deps


pytestmark = pytest.mark.asyncio


async def test_stream_returns_queued_events(gateway_deps_factory):
    """Test 1: pre-queued events are surfaced by the stream tool."""
    harness = gateway_deps_factory()
    registry = _wire_subscription_deps(harness)
    server = build_agent_gateway_mcp_server(harness.deps)

    async with Client(server.mcp) as client:
        create_result = await client.call_tool(
            "agent.subscriptions.create",
            {
                "agent_id": harness.agent_id.value,
                "filter": {"kinds": ["bad_pattern_proposed"]},
                "transport": "mcp_stream",
            },
        )
        sub_id = unwrap(create_result)["subscription_id"]

        # Pre-populate queue.
        await registry.push(sub_id, {
            "subscription_id": sub_id,
            "triggering_entry_seq": 10,
            "kind": "bad_pattern_proposed",
        })
        await registry.push(sub_id, {
            "subscription_id": sub_id,
            "triggering_entry_seq": 11,
            "kind": "bad_pattern_proposed",
        })

        stream_result = await client.call_tool(
            "agent.subscriptions.stream",
            {"subscription_id": sub_id, "since_seq": 0},
        )
    data = unwrap(stream_result)
    assert data["subscription_id"] == sub_id
    assert len(data["events"]) == 2
    seqs = [e["triggering_entry_seq"] for e in data["events"]]
    assert seqs == [10, 11]


async def test_resumption_replays_delivered_entries(gateway_deps_factory):
    """Test 2: since_seq replays past agent_event_delivered entries from the ledger."""
    harness = gateway_deps_factory()
    _wire_subscription_deps(harness)
    server = build_agent_gateway_mcp_server(harness.deps)

    async with Client(server.mcp) as client:
        create_result = await client.call_tool(
            "agent.subscriptions.create",
            {
                "agent_id": harness.agent_id.value,
                "filter": {"kinds": ["bad_pattern_proposed"]},
                "transport": "mcp_stream",
            },
        )
        sub_id = unwrap(create_result)["subscription_id"]

    # Seed two agent_event_delivered entries (one before since_seq, one after).
    for seq in (5, 15):
        await harness.ledger.write(
            company_id=harness.deps.company_id,
            propose={
                "target_kind": "agent_event_delivered",
                "subscription_id": sub_id,
                "triggering_entry_seq": seq,
                "triggering_entry_kind": "bad_pattern_proposed",
                "transport_used": "mcp_stream",
                "delivery_status": "delivered",
            },
            execute_fn=(
                lambda seq=seq: {
                    "tool": "emit_agent_event_delivered",
                    "args": {
                        "subscription_id": sub_id,
                        "triggering_entry_seq": seq,
                        "triggering_entry_kind": "bad_pattern_proposed",
                        "transport_used": "mcp_stream",
                        "delivery_status": "delivered",
                        "duration_ms": 0,
                        "error": None,
                    },
                    "result_ref": sub_id,
                }
            ),
            verify_fn=lambda _e: {
                "checks": [
                    {"name": "agent_event_delivered_recorded", "ok": True},
                ],
                "passed": True,
            },
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test seed"},
            timestamp=datetime.now(UTC),
            quadrant="active_deterministic",
        )

    # Resume from seq=10 → should replay only seq=15.
    async with Client(server.mcp) as client:
        stream_result = await client.call_tool(
            "agent.subscriptions.stream",
            {"subscription_id": sub_id, "since_seq": 10},
        )
    data = unwrap(stream_result)
    assert len(data["events"]) == 1
    assert data["events"][0]["triggering_entry_seq"] == 15
    assert data["events"][0]["replay"] is True


async def test_stream_denies_cross_agent(gateway_deps_factory):
    """Test 3: stream denies when the caller doesn't own the subscription."""
    harness_a = gateway_deps_factory(agent_id_value="agent-a")
    registry = _wire_subscription_deps(harness_a)
    server_a = build_agent_gateway_mcp_server(harness_a.deps)
    async with Client(server_a.mcp) as client:
        create_result = await client.call_tool(
            "agent.subscriptions.create",
            {
                "agent_id": "agent-a",
                "filter": {"kinds": ["bad_pattern_proposed"]},
                "transport": "mcp_stream",
            },
        )
        sub_id = unwrap(create_result)["subscription_id"]

    # Stream as agent-b.
    harness_b = gateway_deps_factory(
        company_id=harness_a.deps.company_id,
        agent_id_value="agent-b",
    )
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
            "agent.subscriptions.stream",
            {"subscription_id": sub_id, "since_seq": 0},
        )
    data = unwrap(result)
    # Stream returns events list where the first event is a denial token.
    assert len(data["events"]) == 1
    assert data["events"][0]["status"] == "denied"
    assert "does not own" in data["events"][0]["reason"]


async def test_stream_surfaces_not_configured(gateway_deps_factory):
    """Test 4: stream surfaces a denial when subscription_tool_deps is None."""
    harness = gateway_deps_factory()
    assert harness.deps.subscription_tool_deps is None
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "agent.subscriptions.stream",
            {"subscription_id": "sub_xyz", "since_seq": 0},
        )
    data = unwrap(result)
    assert data["status"] == "denied"
    assert "not configured" in data["reason"]
