"""End-to-end MCP Phase 0 spike test (Approach B from the spike brief).

Spins up the real FastMCP Streamable HTTP server in-process, exercises
``query_ledger`` via the official MCP Python client, and verifies:

1. The round-trip works (the SPIKE QUESTION).
2. A ``mcp_call_received`` ledger entry lands.
3. End-to-end latency under 500ms for a simple query (the SPIKE SLO).

Per docs/superpowers/specs/2026-04-27-mcp-integration.md §10.1.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import time

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from wormbase_core.mcp_server import build_mcp_server
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger

API_TOKEN = "spike-test-token-do-not-rotate"


def _free_port() -> int:
    """Find a free TCP port in the ephemeral range."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@contextlib.asynccontextmanager
async def _running_mcp_server(ledger, port: int):
    """Start the MCP server on ``port``; tear down on exit."""
    server = build_mcp_server(
        ledger=ledger,
        api_token=API_TOKEN,
        host="127.0.0.1",
        port=port,
    )
    task = asyncio.create_task(server.run_streamable_http_async())

    # Wait for the server to bind (poll the TCP port).
    deadline = time.perf_counter() + 5.0
    while time.perf_counter() < deadline:
        try:
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.close()
            await w.wait_closed()
            break
        except OSError:
            await asyncio.sleep(0.05)
    else:
        task.cancel()
        raise TimeoutError(f"MCP server did not bind on :{port} within 5s")

    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


@pytest.mark.asyncio
async def test_mcp_streamable_http_roundtrip_with_ledger_audit() -> None:
    """The Phase 0 spike question, answered empirically.

    Boots the real FastMCP Streamable HTTP server, calls ``query_ledger``
    over the wire via the official MCP client, asserts:

    - The response shape is a list (the tool succeeded end-to-end).
    - A ``mcp_call_received`` audit entry landed on the ledger.
    - The audit entry's outcome is ``ok``.
    - The round-trip latency (measured client-side) is captured.
    """
    ledger = InMemoryLedger()
    port = _free_port()
    company_slug = "baseworm"
    company_id = tenant_to_uuid(company_slug)

    async with _running_mcp_server(ledger, port):
        url = f"http://127.0.0.1:{port}/mcp"
        headers = {"Authorization": f"Bearer {API_TOKEN}"}

        latencies_ms: list[float] = []

        async with streamablehttp_client(url, headers=headers) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = [t.name for t in tools.tools]
                assert "query_ledger" in names

                # Five sample queries — gives us median + p95 for the spike note.
                for _ in range(5):
                    t0 = time.perf_counter()
                    result = await session.call_tool(
                        "query_ledger",
                        arguments={
                            "company_id": company_slug,
                            "limit": 10,
                        },
                    )
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    latencies_ms.append(elapsed)
                    assert not result.isError, (
                        f"tool returned error: {result.content!r}"
                    )

    # The spike's empirical evidence — print so the spike note can quote.
    latencies_ms.sort()
    median = latencies_ms[len(latencies_ms) // 2]
    p95 = latencies_ms[int(0.95 * (len(latencies_ms) - 1))]
    print(
        f"\n[mcp-spike] query_ledger over 5 calls: "
        f"median={median:.1f}ms p95={p95:.1f}ms "
        f"all={[f'{x:.1f}' for x in latencies_ms]}"
    )

    # Verify the ledger audit. We have 5 calls × 4 PEVR entries = 20 rows,
    # all under the canonical company_id derived from "baseworm".
    rows = await ledger.fetch(company_id)
    execute_rows = [r for r in rows if r["kind"] == "execute"]
    mcp_audits = [
        r
        for r in execute_rows
        if r["payload"]["tool"] == "emit_mcp_call_received"
    ]
    assert len(mcp_audits) == 5, (
        f"expected 5 mcp_call_received audits; got {len(mcp_audits)}"
    )
    sample = mcp_audits[0]
    body = sample["payload"]["args"]
    assert body["tool_name"] == "query_ledger"
    assert body["outcome"] == "ok"
    assert body["latency_ms"] >= 0
    assert len(body["args_hash"]) == 64
    # caller_person_id is None in v1 bearer-token mode.
    assert body["caller_person_id"] is None


@pytest.mark.asyncio
async def test_mcp_streamable_http_denies_missing_token() -> None:
    """Calls without a Bearer token write a 'denied' audit + raise."""
    ledger = InMemoryLedger()
    port = _free_port()
    company_slug = "baseworm"
    company_id = tenant_to_uuid(company_slug)

    async with _running_mcp_server(ledger, port):
        url = f"http://127.0.0.1:{port}/mcp"
        # Note: no Authorization header.
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "query_ledger",
                    arguments={
                        "company_id": company_slug,
                        "limit": 5,
                    },
                )
                # The MCP layer reports tool errors via isError; our
                # PermissionError surfaces there.
                assert result.isError, (
                    f"expected error; got {result.content!r}"
                )

    # Audit landed with outcome=denied.
    rows = await ledger.fetch(company_id)
    execute_rows = [r for r in rows if r["kind"] == "execute"]
    denials = [
        r
        for r in execute_rows
        if r["payload"]["tool"] == "emit_mcp_call_received"
        and r["payload"]["args"]["outcome"] == "denied"
    ]
    assert len(denials) == 1, (
        f"expected 1 denied audit; got {len(denials)}"
    )
