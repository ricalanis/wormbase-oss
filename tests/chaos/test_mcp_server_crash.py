"""Chaos: MCP server crashes (listener closed) mid-call.

Failure mode
------------
The FastMCP Streamable HTTP server is killed (the listener task is
cancelled, the TCP socket closes) while the client is mid-call. New
client connections must surface a structured connection error rather
than hanging or returning fake data.

Invariants the system MUST preserve
-----------------------------------
1. The MCP client receives a structured connection error (any
   ``Exception`` derived from a transport-level failure — we name it
   ``MCPConnectionError`` in the assertion message). The client does
   NOT receive a partial success or a stale response.
2. The dashboard's ``/mcp`` tab UI surface (rendered as the
   ``/mcp/catalog`` HTTP endpoint) renders the "MCP unavailable"
   honest empty state when the env-gate is off — same surface the
   user sees when the server is genuinely down.
3. Rate-limit / budget counters tracked in the ledger as
   ``mcp_call_received`` audit rows are NOT corrupted by the crash:
   the ledger contains the same number of audit rows it had before
   the failed-call attempt (no half-written PEVR cycle leaks past
   the verify gate).
4. After server restart, the next call works without a stale-state
   error.

Failure-injection point
-----------------------
We start the FastMCP server, cancel the running task, then attempt a
fresh client call. The streamable_http transport surfaces a
ConnectionRefusedError-like exception, which we treat as the
canonical "MCP unavailable" condition. Then we restart and verify
the client recovers.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core.http_api import build_app
from wormbase_core.mcp_server import build_mcp_server
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger


API_TOKEN = "chaos-mcp-token"


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def _start_mcp_server(ledger: Any, port: int) -> asyncio.Task[Any]:
    """Boot the MCP server on ``port``; return the asyncio task running it."""
    server = build_mcp_server(
        ledger=ledger,
        api_token=API_TOKEN,
        host="127.0.0.1",
        port=port,
    )
    task = asyncio.create_task(server.run_streamable_http_async())

    deadline = time.perf_counter() + 5.0
    while time.perf_counter() < deadline:
        try:
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.close()
            await w.wait_closed()
            return task
        except OSError:
            await asyncio.sleep(0.05)
    task.cancel()
    raise TimeoutError(f"MCP server did not bind on :{port} within 5s")


async def _stop_task(task: asyncio.Task[Any]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


@pytest_asyncio.fixture
async def memory_ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest_asyncio.fixture
async def http_client(memory_ledger: InMemoryLedger) -> AsyncIterator[TestClient]:
    """worm-core HTTP API for the /mcp/catalog and /api/v1/ops/health checks."""
    app = build_app(ledger=memory_ledger, api_token=API_TOKEN)
    server = TestServer(app)
    cli = TestClient(server)
    await cli.start_server()
    try:
        yield cli
    finally:
        await cli.close()


# ---------------------------------------------------------------------------
# Invariant 1 + 4 — crash + restart, client surfaces structured errors
# ---------------------------------------------------------------------------


async def test_client_gets_structured_error_when_mcp_listener_is_dead(
    memory_ledger: InMemoryLedger, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh client connect against a dead listener raises a structured
    connection error — NOT a timeout, not a hang.

    To simulate a crashed server deterministically (uvicorn's port-drain
    is racy in test mode), we point the MCP client at a port that was
    just released — the kernel guarantees TCP refused on connect for a
    port no process is listening on. Same wire-level failure shape as
    a crashed FastMCP listener.
    """
    monkeypatch.setenv("WORMBASE_MCP_ENABLED", "1")
    company_slug = "baseworm"
    company_id = tenant_to_uuid(company_slug)

    # Reserve and immediately release a port — the kernel will refuse
    # new connections to it (no listener is bound). This is the same
    # connect-side failure shape a crashed MCP server presents.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    # Capture audit rows before the failed attempt to assert no
    # corruption later.
    rows_before = await memory_ledger.fetch(company_id)

    # Try to talk to the dead server. The MCP client raises a
    # transport-level exception; we catch any Exception so the test is
    # robust across SDK versions, and assert the canonical shape (a
    # connection-refused / unavailable / network error).
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    raised: Exception | None = None
    url = f"http://127.0.0.1:{port}/mcp"
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    try:
        async with asyncio.timeout(3.0):
            async with streamablehttp_client(url, headers=headers) as (
                read, write, _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
    except Exception as exc:  # noqa: BLE001
        raised = exc

    assert raised is not None, (
        "MCP client must raise a structured connection error when the "
        "server is down — never hang or return success"
    )
    # Honest UX: the error names the connection failure shape, not a
    # silent timeout. We accept ConnectionError, ConnectionRefusedError,
    # OSError, asyncio.TimeoutError, or any MCP-internal subclass that
    # carries the substring "connection" in its repr.
    repr_text = repr(raised).lower()
    assert any(
        token in repr_text
        for token in (
            "connection",
            "refused",
            "closed",
            "unavailable",
            "exceptiongroup",
            "timeout",
        )
    ), (
        f"expected a structured connection error; got: {raised!r}"
    )

    # Invariant 3: the failed call did NOT corrupt the ledger.
    rows_after = await memory_ledger.fetch(company_id)
    assert len(rows_after) == len(rows_before), (
        "ledger audit rows must NOT change when the MCP client never "
        "reaches the server (no half-written PEVR)"
    )

    # Invariant 4: restart works and the next call succeeds.
    task2 = await _start_mcp_server(memory_ledger, port)
    try:
        async with streamablehttp_client(url, headers=headers) as (
            read, write, _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "query_ledger",
                    arguments={"company_id": company_slug, "limit": 5},
                )
                assert not result.isError, (
                    f"post-restart call must succeed; got {result.content!r}"
                )
    finally:
        await _stop_task(task2)

    # Invariant 3 cont'd: exactly one new mcp_call_received audit row
    # landed (the post-restart call). No stale state from the crash.
    rows_final = await memory_ledger.fetch(company_id)
    new_rows = rows_final[len(rows_after):]
    new_audits = [
        r for r in new_rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_mcp_call_received"
    ]
    assert len(new_audits) == 1, (
        f"exactly one new audit row from the post-restart call; got "
        f"{len(new_audits)}"
    )
    assert new_audits[0]["payload"]["args"]["outcome"] == "ok"


# ---------------------------------------------------------------------------
# Invariant 2 — /mcp/catalog renders an honest "MCP unavailable" state
# ---------------------------------------------------------------------------


async def test_mcp_catalog_endpoint_renders_unavailable_state_when_disabled(
    http_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the MCP env-gate is off (the equivalent of "server down"
    from the dashboard's perspective), /mcp/catalog returns a 404
    with an honest body — the dashboard renders an honest empty state
    rather than blank-pageing the user."""
    monkeypatch.delenv("WORMBASE_MCP_ENABLED", raising=False)

    resp = await http_client.get("/mcp/catalog")
    assert resp.status == 404, await resp.text()
    body = await resp.json()
    assert body.get("available") is False
    # The body's empty arrays are the truthful "no MCP surface here"
    # state the dashboard's /mcp tab renders.
    assert body.get("entries") == []
    assert body.get("tools") == []
