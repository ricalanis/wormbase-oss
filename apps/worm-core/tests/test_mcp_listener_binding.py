"""Tests for the agent-gateway MCP listener binding — v1.3 Task 1 Item #2.

The listener is opt-in via ``WORMBASE_AGENT_GATEWAY_MCP_LISTENER_ENABLED``
and supports two transports:

* ``stdio`` (default) — Claude Desktop and other local-MCP-client
  integrations. Starts FastMCP's stdio loop.
* ``http`` — single-tenant FastMCP HTTP listener on the configured
  host/port (default ``127.0.0.1:8911``). Multi-tenant routing is v2
  per spec §11.

Listener startup is failure-isolated: any crash logs loudly and the
coroutine returns cleanly so worm-core boot continues.

Tests in this module cover:

1. Env resolution: transport, host, port defaults and overrides.
2. ``is_listener_enabled`` env knob.
3. The stdio path can start + cancel cleanly (lifecycle smoke).
4. The HTTP path binds and exposes the FastMCP HTTP surface.
5. Failure isolation: a crashing inner call surfaces in logs but the
   coroutine returns cleanly.

The tests use minimal stubs for ``server.mcp`` so we don't pull
fastmcp's full async runtime into the unit-test path; the production
path is exercised by ``test_agent_gateway_construction_v1_2.py`` and
``test_agent_gateway_construction_v1_3.py`` (Item #1's e2e).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest
from wormbase_core.agent_gateway_construction import (
    is_listener_enabled,
    resolve_listener_http_host,
    resolve_listener_http_port,
    resolve_listener_transport,
    run_agent_gateway_mcp_listener,
)

TEST_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000abc")


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubMCP:
    """Replaces ``server.mcp`` with a recordable async runner.

    Lets us assert that the listener picks the right transport / host /
    port without spinning up a real network loop. Each ``run_*_async``
    coroutine takes the keyword args FastMCP accepts and records the
    invocation. ``raise_on_run`` lets a test simulate a listener crash.
    """

    def __init__(self, *, raise_on_run: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._raise = raise_on_run

    async def run_stdio_async(self, **kwargs: Any) -> None:
        self.calls.append(("stdio", kwargs))
        if self._raise is not None:
            raise self._raise
        # Block until cancelled; matches FastMCP's real stdio loop.
        await asyncio.Event().wait()

    async def run_http_async(self, **kwargs: Any) -> None:
        self.calls.append(("http", kwargs))
        if self._raise is not None:
            raise self._raise
        await asyncio.Event().wait()


@dataclass
class _StubDeps:
    install_id: str = str(TEST_COMPANY_ID)


@dataclass
class _StubServer:
    mcp: _StubMCP
    deps: _StubDeps


def _make_stub_server(*, raise_on_run: Exception | None = None) -> _StubServer:
    return _StubServer(
        mcp=_StubMCP(raise_on_run=raise_on_run),
        deps=_StubDeps(),
    )


# ---------------------------------------------------------------------------
# Env-resolution helpers
# ---------------------------------------------------------------------------


def test_resolve_transport_defaults_to_stdio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "WORMBASE_AGENT_GATEWAY_MCP_TRANSPORT", raising=False,
    )
    assert resolve_listener_transport() == "stdio"


def test_resolve_transport_honors_http_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "WORMBASE_AGENT_GATEWAY_MCP_TRANSPORT", "http",
    )
    assert resolve_listener_transport() == "http"


def test_resolve_transport_coerces_unknown_to_stdio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "WORMBASE_AGENT_GATEWAY_MCP_TRANSPORT", "websocket",
    )
    assert resolve_listener_transport() == "stdio"


def test_resolve_http_port_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "WORMBASE_AGENT_GATEWAY_MCP_PORT", raising=False,
    )
    assert resolve_listener_http_port() == 8911


def test_resolve_http_port_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "WORMBASE_AGENT_GATEWAY_MCP_PORT", "9000",
    )
    assert resolve_listener_http_port() == 9000


def test_resolve_http_port_invalid_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "WORMBASE_AGENT_GATEWAY_MCP_PORT", "not-an-int",
    )
    assert resolve_listener_http_port() == 8911


def test_resolve_http_host_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "WORMBASE_AGENT_GATEWAY_MCP_HOST", raising=False,
    )
    assert resolve_listener_http_host() == "127.0.0.1"


def test_resolve_http_host_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "WORMBASE_AGENT_GATEWAY_MCP_HOST", "0.0.0.0",
    )
    assert resolve_listener_http_host() == "0.0.0.0"


def test_is_listener_enabled_default_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "WORMBASE_AGENT_GATEWAY_MCP_LISTENER_ENABLED", raising=False,
    )
    assert is_listener_enabled() is False


def test_is_listener_enabled_true_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "WORMBASE_AGENT_GATEWAY_MCP_LISTENER_ENABLED", "1",
    )
    assert is_listener_enabled() is True


# ---------------------------------------------------------------------------
# Listener lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stdio_listener_starts_and_cancels_cleanly() -> None:
    """The stdio listener starts and accepts a graceful cancel."""
    server = _make_stub_server()
    task = asyncio.create_task(
        run_agent_gateway_mcp_listener(server, transport="stdio"),  # type: ignore[arg-type]
    )

    # Give the listener a tick to enter run_stdio_async.
    await asyncio.sleep(0)
    assert server.mcp.calls == [("stdio", {"show_banner": False})]

    # Cancel + await — CancelledError should propagate as a normal stop.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_http_listener_uses_resolved_host_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The HTTP listener passes the configured host/port to FastMCP."""
    monkeypatch.setenv("WORMBASE_AGENT_GATEWAY_MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("WORMBASE_AGENT_GATEWAY_MCP_PORT", "8912")
    server = _make_stub_server()
    task = asyncio.create_task(
        run_agent_gateway_mcp_listener(server, transport="http"),  # type: ignore[arg-type]
    )
    await asyncio.sleep(0)
    assert server.mcp.calls == [
        ("http", {
            "show_banner": False,
            "host": "127.0.0.1",
            "port": 8912,
        }),
    ]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_http_listener_explicit_args_win() -> None:
    """Explicit host/port args override env."""
    server = _make_stub_server()
    task = asyncio.create_task(
        run_agent_gateway_mcp_listener(
            server,  # type: ignore[arg-type]
            transport="http",
            host="0.0.0.0",
            port=9999,
        ),
    )
    await asyncio.sleep(0)
    assert server.mcp.calls == [
        ("http", {
            "show_banner": False,
            "host": "0.0.0.0",
            "port": 9999,
        }),
    ]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ---------------------------------------------------------------------------
# Failure isolation (Item #2 contract)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listener_failure_logs_and_returns_cleanly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A crash inside the FastMCP runner logs at ERROR and does not raise.

    The contract is "listener failure does NOT crash worm-core boot" —
    the coroutine must return cleanly so ``asyncio.gather`` keeps the
    rest of the lifecycle running.
    """
    boom = RuntimeError("stdio transport unavailable")
    server = _make_stub_server(raise_on_run=boom)

    caplog.set_level("ERROR")
    # Should NOT raise — the contract is failure-isolated.
    await run_agent_gateway_mcp_listener(server, transport="stdio")  # type: ignore[arg-type]

    # The error message should mention the failure for ops.
    assert any(
        "agent-gateway MCP listener" in record.message
        and "crashed" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_unknown_transport_logs_and_returns_cleanly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A defensive branch handles an unknown transport string."""
    server = _make_stub_server()
    caplog.set_level("ERROR")
    # transport= bypasses env coercion to exercise the inner branch.
    await run_agent_gateway_mcp_listener(
        server,  # type: ignore[arg-type]
        transport="not-a-transport",
    )
    assert server.mcp.calls == []
    assert any(
        "unknown transport" in record.message for record in caplog.records
    )
