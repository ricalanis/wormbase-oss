"""Integration tests — StreamTransport abstraction (Path 3, 2026-05-21).

Pins the two transport semantics:

1. ListModeTransport (default) — byte-identical to the pre-Path-3 inline
   wrapper: collects events into a single ``{subscription_id, events}``
   response and breaks when the queue drains.
2. SseStreamTransport (opt-in) — when the FastMCP capability probe
   returns False (today's 3.2.4), degrades to ListModeTransport without
   surfacing a denial. When the probe returns True (future), returns
   the raw async generator for true SSE yield.
3. Env knob ``WORMBASE_MCP_SSE_TRANSPORT`` selects the transport at
   construction time.
4. Capability probe is honest about today's FastMCP version (False).

Why pin both transports? The transport abstraction's whole purpose is
to keep the list-mode contract byte-identical while paving the SSE
upgrade path. Tests that pin only one side erode the doctrine.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest
from fastmcp import Client

from wormbase_agent_gateway.mcp_server import build_agent_gateway_mcp_server
from wormbase_agent_gateway.subscriptions.mcp_tools import (
    SubscriptionToolDeps,
)
from wormbase_agent_gateway.subscriptions.stream_registry import StreamRegistry
from wormbase_agent_gateway.subscriptions.stream_transport import (
    ListModeTransport,
    SseStreamTransport,
    build_stream_transport_from_env,
    fastmcp_supports_streaming_tools,
    is_sse_transport_enabled,
)
from wormbase_inference import AgentID

from ._helpers import unwrap
from .test_subscription_mcp_tools import _LedgerBackedReader, _wire_subscription_deps


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Probe + env-knob unit tests
# ---------------------------------------------------------------------------


async def test_fastmcp_streaming_probe_is_honest_about_3_2_4():
    """Probe returns False for the installed FastMCP 3.2.4.

    The probe is the single point where SseStreamTransport decides
    whether to do true SSE or degrade to list-mode. As long as FastMCP
    materializes generators into lists at the tool-runner level
    (function_tool.py:_materialize_generator), this is False.
    """
    assert fastmcp_supports_streaming_tools() is False


async def test_is_sse_transport_enabled_defaults_off():
    """Env knob defaults off — byte-identical to pre-Path-3."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("WORMBASE_MCP_SSE_TRANSPORT", None)
        assert is_sse_transport_enabled() is False


@pytest.mark.parametrize("val", ["true", "1", "yes", "on", "TRUE", "On"])
async def test_is_sse_transport_enabled_honors_truthy_values(val: str):
    """Env knob accepts all canonical truthy values."""
    with patch.dict(os.environ, {"WORMBASE_MCP_SSE_TRANSPORT": val}):
        assert is_sse_transport_enabled() is True


@pytest.mark.parametrize("val", ["false", "0", "no", "off", "", "garbage"])
async def test_is_sse_transport_enabled_rejects_falsy_values(val: str):
    """Env knob rejects falsy + invalid values (default-off bias)."""
    with patch.dict(os.environ, {"WORMBASE_MCP_SSE_TRANSPORT": val}):
        assert is_sse_transport_enabled() is False


async def test_build_stream_transport_from_env_default_is_list_mode():
    """Default composition: ListModeTransport (Optional-Effect Injection §3.1)."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("WORMBASE_MCP_SSE_TRANSPORT", None)
        t = build_stream_transport_from_env()
        assert isinstance(t, ListModeTransport)


async def test_build_stream_transport_from_env_opt_in_is_sse_mode():
    """Opt-in composition: SseStreamTransport when env knob is set."""
    with patch.dict(os.environ, {"WORMBASE_MCP_SSE_TRANSPORT": "true"}):
        t = build_stream_transport_from_env()
        assert isinstance(t, SseStreamTransport)


# ---------------------------------------------------------------------------
# List-mode transport (default) — pins the byte-identical contract
# ---------------------------------------------------------------------------


async def test_list_mode_transport_is_subscription_tool_deps_default(
    gateway_deps_factory,
):
    """SubscriptionToolDeps.__post_init__ defaults to ListModeTransport.

    Construction sites that predate Path 3 (existing tests, existing
    wiring) get list-mode without importing the transport module.
    """
    harness = gateway_deps_factory()
    deps = SubscriptionToolDeps(
        ledger=harness.ledger,
        company_id=harness.deps.company_id,
        subscription_reader=_LedgerBackedReader(harness.ledger),
        stream_registry=StreamRegistry(),
    )
    assert isinstance(deps.stream_transport, ListModeTransport)


async def test_list_mode_response_shape_matches_pre_path_3(gateway_deps_factory):
    """List-mode response is ``{subscription_id, events: [...]}``.

    This is the v2.A external contract. The transport abstraction must
    not change the shape; only the underlying mechanism (inline loop vs
    transport.deliver call) is refactored.
    """
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
        # Push 3 events; the list-mode wrapper should drain all 3.
        for seq in (10, 11, 12):
            await registry.push(sub_id, {
                "subscription_id": sub_id,
                "triggering_entry_seq": seq,
                "kind": "bad_pattern_proposed",
            })

        result = await client.call_tool(
            "agent.subscriptions.stream",
            {"subscription_id": sub_id, "since_seq": 0},
        )
    data = unwrap(result)
    assert set(data.keys()) == {"subscription_id", "events"}
    assert data["subscription_id"] == sub_id
    assert [e["triggering_entry_seq"] for e in data["events"]] == [10, 11, 12]


# ---------------------------------------------------------------------------
# SSE transport (opt-in) — pins the degrade-to-list-mode-when-probe-False
# ---------------------------------------------------------------------------


async def test_sse_transport_degrades_to_list_mode_on_today_fastmcp(
    gateway_deps_factory, caplog,
):
    """SseStreamTransport degrades to list-mode when probe returns False.

    The agent receives a byte-identical ``{subscription_id, events: [...]}``
    response so flipping the env knob never breaks the client. When a
    future FastMCP grows streaming tools, the probe flips True and the
    SseStreamTransport delivers true per-event yields without any
    consumer-side change.
    """
    import logging

    harness = gateway_deps_factory()
    reader = _LedgerBackedReader(harness.ledger)
    registry = StreamRegistry()
    harness.deps.subscription_tool_deps = SubscriptionToolDeps(
        ledger=harness.ledger,
        company_id=harness.deps.company_id,
        subscription_reader=reader,
        stream_registry=registry,
        stream_transport=SseStreamTransport(),
    )
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
        await registry.push(sub_id, {
            "subscription_id": sub_id,
            "triggering_entry_seq": 7,
            "kind": "bad_pattern_proposed",
        })

        with caplog.at_level(
            logging.INFO,
            logger="wormbase_agent_gateway.subscriptions.stream_transport",
        ):
            result = await client.call_tool(
                "agent.subscriptions.stream",
                {"subscription_id": sub_id, "since_seq": 0},
            )

    # Byte-identical to list-mode contract.
    data = unwrap(result)
    assert data["subscription_id"] == sub_id
    assert len(data["events"]) == 1
    assert data["events"][0]["triggering_entry_seq"] == 7
    # The degrade is logged once at INFO so operators can see it.
    degrade_records = [
        r for r in caplog.records
        if "degrading to list-mode" in r.getMessage()
    ]
    assert len(degrade_records) >= 1


async def test_sse_transport_yields_directly_when_probe_returns_true(
    gateway_deps_factory,
):
    """When the FastMCP probe returns True, SseStreamTransport returns
    the raw async generator from .deliver().

    This pins the upgrade contract: when a future FastMCP version
    supports streaming tools and we flip the probe to True, the
    transport delivers a true async iterator. The tool runner (out of
    scope here) is then responsible for yielding each event to the
    client.

    We exercise the transport directly (bypassing the FastMCP runner)
    because today's runner materializes generators into lists — i.e.,
    even if the probe returned True, the tool-call round-trip would
    still come back as a list at the FastMCP layer. The transport-
    level contract is what we pin here.
    """
    transport = SseStreamTransport()
    registry = StreamRegistry()
    sub_id = "sub-test-sse"

    async def fake_generator():
        yield {"subscription_id": sub_id, "triggering_entry_seq": 1}
        yield {"subscription_id": sub_id, "triggering_entry_seq": 2}

    with patch(
        "wormbase_agent_gateway.subscriptions.stream_transport."
        "fastmcp_supports_streaming_tools",
        return_value=True,
    ):
        result = await transport.deliver(
            subscription_id=sub_id,
            generator=fake_generator(),
            stream_registry=registry,
        )
        # When probe is True, .deliver() returns an async iterator
        # (not a list). We drain it to verify shape.
        events: list[dict[str, Any]] = []
        async for ev in result:
            events.append(ev)

    assert len(events) == 2
    seqs = [e["triggering_entry_seq"] for e in events]
    assert seqs == [1, 2]
    # subscription_id stamped on each event for client-shape parity.
    assert all(e["subscription_id"] == sub_id for e in events)


async def test_sse_transport_wraps_events_without_subscription_id(
    gateway_deps_factory,
):
    """SSE wrapper stamps subscription_id when the generator omits it.

    The generator's denial events (status=denied) already include the
    subscription_id; replay + queue events do too. But defensive coverage:
    if a future event shape forgets to set it, the SSE wrapper injects
    it so per-event clients always know which subscription delivered.
    """
    transport = SseStreamTransport()
    registry = StreamRegistry()
    sub_id = "sub-test-stamp"

    async def fake_generator():
        # Intentionally missing subscription_id.
        yield {"triggering_entry_seq": 99, "kind": "x"}

    with patch(
        "wormbase_agent_gateway.subscriptions.stream_transport."
        "fastmcp_supports_streaming_tools",
        return_value=True,
    ):
        result = await transport.deliver(
            subscription_id=sub_id,
            generator=fake_generator(),
            stream_registry=registry,
        )
        events = [ev async for ev in result]

    assert events == [{
        "subscription_id": sub_id,
        "triggering_entry_seq": 99,
        "kind": "x",
    }]


# ---------------------------------------------------------------------------
# Tenant + auth context capture
# ---------------------------------------------------------------------------


async def test_tenant_context_captured_at_stream_open_not_per_event(
    gateway_deps_factory,
):
    """TenantContext + auth + rate-limit happen once at stream-open.

    Subsequent events drain through the generator without re-resolving
    the tenant — per the Wave 4 close-out note ("per-event rate-limiting
    on an SSE connection is an anti-pattern"). We verify this by
    counting calls to deps.agent_id_resolver over a stream that drains
    multiple events: exactly one call, regardless of event count.
    """
    harness = gateway_deps_factory()
    registry = _wire_subscription_deps(harness)
    server = build_agent_gateway_mcp_server(harness.deps)

    # Count agent-resolver invocations.
    real_resolver = harness.deps.agent_id_resolver
    call_count = {"n": 0}

    async def counting_resolver() -> AgentID:
        call_count["n"] += 1
        return await real_resolver()

    harness.deps.agent_id_resolver = counting_resolver
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
        # Push 5 events into the queue.
        for seq in range(20, 25):
            await registry.push(sub_id, {
                "subscription_id": sub_id,
                "triggering_entry_seq": seq,
                "kind": "bad_pattern_proposed",
            })

        # Reset the counter — only count the stream call.
        call_count["n"] = 0
        result = await client.call_tool(
            "agent.subscriptions.stream",
            {"subscription_id": sub_id, "since_seq": 0},
        )

    data = unwrap(result)
    assert len(data["events"]) == 5
    # Exactly one resolver call across the 5-event stream-open.
    assert call_count["n"] == 1, (
        f"agent_id_resolver should be called exactly once at stream-open, "
        f"got {call_count['n']} calls (one per event would be the anti-pattern)"
    )
