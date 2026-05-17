"""Phase 3 Task 3B — POST /api/v1/worm/ask HTTP endpoint.

The endpoint orchestrates ``ask_the_worm`` over the same ledger the
write API uses; the dashboard's ``/api/ask`` route forwards every
question here.

Tests cover:
  * Bearer-token auth
  * 422 on empty / non-string question
  * Happy path: writes the chat_received PEVR, fires
    MentionResponseReactivity, returns the captured worm reply
  * X-Tenant-Slug routes to the right company_id (no cross-tenant leak)
  * Response shape matches the dashboard's AskResponseBody contract
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core.ask_the_worm import ASK_THE_WORM_DEFAULT_REPLY
from wormbase_core.http_api import build_app
from wormbase_ledger import InMemoryLedger


API_TOKEN = "test-token-ask"
TENANT_SLUG = "baseworm"


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


def _auth_headers(*, token: str = API_TOKEN, tenant: str = TENANT_SLUG) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Slug": tenant,
    }


async def test_post_worm_ask_missing_auth_returns_401(client: TestClient) -> None:
    resp = await client.post("/api/v1/worm/ask", json={"question": "hi"})
    assert resp.status == 401


async def test_post_worm_ask_wrong_token_returns_401(client: TestClient) -> None:
    resp = await client.post(
        "/api/v1/worm/ask",
        headers={"Authorization": "Bearer nope", "X-Tenant-Slug": TENANT_SLUG},
        json={"question": "hi"},
    )
    assert resp.status == 401


async def test_post_worm_ask_empty_question_returns_422(client: TestClient) -> None:
    resp = await client.post(
        "/api/v1/worm/ask",
        headers=_auth_headers(),
        json={"question": ""},
    )
    assert resp.status == 422


async def test_post_worm_ask_non_string_returns_422(client: TestClient) -> None:
    resp = await client.post(
        "/api/v1/worm/ask",
        headers=_auth_headers(),
        json={"question": 42},
    )
    assert resp.status == 422


async def test_post_worm_ask_happy_path(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Writes chat_received PEVR + chat_reply PEVR; returns reply text."""
    resp = await client.post(
        "/api/v1/worm/ask",
        headers=_auth_headers(),
        json={"question": "What's our Q3 net revenue?"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    assert body["passthrough"] is True
    assert body["answer"] == ASK_THE_WORM_DEFAULT_REPLY
    assert body["references"] == []
    assert body["channel_id"].startswith("in_app:")
    assert isinstance(body.get("chat_reply_id"), str)


async def test_post_worm_ask_writes_to_correct_tenant(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """X-Tenant-Slug routes the chat_received write to the matching tenant."""
    from wormbase_core.service import tenant_to_uuid

    resp = await client.post(
        "/api/v1/worm/ask",
        headers=_auth_headers(tenant="alpha"),
        json={"question": "hello"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True

    # Tenant 'alpha' got the chat_received entry; the other slug didn't.
    alpha_id = tenant_to_uuid("alpha")
    other_id = tenant_to_uuid("beta")
    rows_alpha = await memory_ledger.fetch(alpha_id)
    rows_other = await memory_ledger.fetch(other_id)

    chat_received_alpha = [
        r for r in rows_alpha
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool")
        == "channel_adapter.emit_chat_received"
    ]
    chat_received_other = [
        r for r in rows_other
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool")
        == "channel_adapter.emit_chat_received"
    ]
    assert len(chat_received_alpha) == 1
    assert len(chat_received_other) == 0


async def test_post_worm_ask_response_matches_dashboard_contract(
    client: TestClient,
) -> None:
    """Body shape must match the dashboard's AskResponseBody TypeScript type."""
    resp = await client.post(
        "/api/v1/worm/ask",
        headers=_auth_headers(),
        json={"question": "ping"},
    )
    body = await resp.json()
    # Required keys per apps/dashboard/app/api/ask/route.ts AskResponseBody.
    for k in ("ok", "answer", "references", "passthrough"):
        assert k in body, f"missing key: {k}"
    assert isinstance(body["answer"], str) and body["answer"]
    assert isinstance(body["references"], list)
    assert isinstance(body["passthrough"], bool)
