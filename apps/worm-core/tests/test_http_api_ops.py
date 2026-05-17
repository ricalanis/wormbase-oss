"""W2.A10 — GET /api/v1/ops/health smoke tests.

Runs against the in-memory ledger so the tests stay docker-free. The
ledger has no SQL engine, so postgres health reports `unknown` rather
than `ok`/`down` — that's an honest reflection of the harness, not a
bug. The other three sections (throughput, mcp, agent loops) exercise
the canonical synthesis paths.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core.http_api import build_app
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger


API_TOKEN = "test-token-ops"


@pytest_asyncio.fixture
async def memory_ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest_asyncio.fixture
async def client(memory_ledger: InMemoryLedger) -> AsyncIterator[TestClient]:
    app = build_app(ledger=memory_ledger, api_token=API_TOKEN)
    server = TestServer(app)
    cli = TestClient(server)
    await cli.start_server()
    try:
        yield cli
    finally:
        await cli.close()


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


async def test_ops_health_requires_bearer(client: TestClient) -> None:
    resp = await client.get("/api/v1/ops/health")
    assert resp.status == 401


async def test_ops_health_returns_envelope_with_all_four_sections(
    client: TestClient,
) -> None:
    resp = await client.get("/api/v1/ops/health", headers=_auth())
    assert resp.status == 200
    body = await resp.json()
    assert set(body.keys()) >= {
        "generatedAt",
        "postgres",
        "ledgerThroughput",
        "mcpRateLimits",
        "agentLoops",
    }
    # InMemoryLedger has no SQL engine — postgres status is `unknown`.
    assert body["postgres"]["status"] == "unknown"
    # Throughput buckets always span `_OPS_THROUGHPUT_WINDOW_MIN` minutes.
    assert body["ledgerThroughput"]["windowMinutes"] == 10
    assert len(body["ledgerThroughput"]["buckets"]) == 10
    # mcpRateLimits + agentLoops are always present (they degrade
    # internally rather than being omitted from the envelope).
    assert isinstance(body["mcpRateLimits"]["enabled"], bool)
    loop_ids = {loop["id"] for loop in body["agentLoops"]}
    assert loop_ids == {"worm-core", "channel-adapter", "projection-runner"}


async def test_ops_health_throughput_picks_up_recent_writes(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """A single PEVR cycle lands four entries; the ops snapshot should
    surface them in the trailing-window throughput total."""
    # Use the canonical write helper so the ledger entries match the
    # production shape (kind + ts + payload).
    company_id = tenant_to_uuid("baseworm")

    def _propose() -> dict[str, Any]:
        return {"summary": "test propose"}

    def _execute() -> dict[str, Any]:
        return {"tool": "emit_test_event", "args": {"summary": "ops smoke"}}

    def _verify(_payload: dict[str, Any]) -> dict[str, Any]:
        return {"passed": True, "summary": "ok"}

    def _resolve(_payload: dict[str, Any]) -> dict[str, Any]:
        return {"outcome": "keep", "summary": "kept"}

    await memory_ledger.write(
        company_id=company_id,
        propose=_propose(),
        execute_fn=_execute,
        verify_fn=_verify,
        resolve_fn=_resolve,
    )

    resp = await client.get("/api/v1/ops/health", headers=_auth())
    body = await resp.json()
    assert body["ledgerThroughput"]["totalLastWindow"] >= 4
