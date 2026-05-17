"""Phase 1B.C — HTTP API tests for /api/v1/tenants/signup-{initiated,completed}.

Pairs with the spike + plan at:
  - docs/superpowers/notes/2026-05-04-multitenancy-v2-spike.md
  - docs/superpowers/plans/2026-05-04-multitenancy-v2.md

Both endpoints are bearer-authed and tenant-scoped via X-Tenant-Slug.
The dashboard's Slack OAuth callback (1B.C) and magic-link confirm
endpoint (1B.D) POST here as part of the canonical signup chain.
"""
from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core.http_api import build_app
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger


API_TOKEN = "test-tenant-signup-token"
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


def _valid_initiated_body() -> dict[str, object]:
    return {
        "tenant_id": str(tenant_to_uuid(TENANT_SLUG)),
        "slug": TENANT_SLUG,
        "display_name": "Baseworm",
        "signup_source": "slack_oauth",
        "signup_email": "founder@baseworm.test",
        "pending_token_hash": hashlib.sha256(b"oauth-state-token").hexdigest(),
    }


def _valid_completed_body() -> dict[str, object]:
    return {
        "tenant_id": str(tenant_to_uuid(TENANT_SLUG)),
        "signup_source": "slack_oauth",
        "assigned_tenant_slug": TENANT_SLUG,
        "signup_email": "founder@baseworm.test",
    }


async def test_post_signup_initiated_missing_auth_returns_401(
    client: TestClient,
) -> None:
    resp = await client.post(
        "/api/v1/tenants/signup-initiated",
        json=_valid_initiated_body(),
    )
    assert resp.status == 401


async def test_post_signup_completed_missing_auth_returns_401(
    client: TestClient,
) -> None:
    resp = await client.post(
        "/api/v1/tenants/signup-completed",
        json=_valid_completed_body(),
    )
    assert resp.status == 401


async def test_post_signup_initiated_happy_path(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    resp = await client.post(
        "/api/v1/tenants/signup-initiated",
        headers=_auth_headers(),
        json=_valid_initiated_body(),
    )
    assert resp.status == 201, await resp.text()
    body = await resp.json()
    assert isinstance(body["entry_ids"], list)
    assert len(body["entry_ids"]) == 4

    cid = tenant_to_uuid(TENANT_SLUG)
    rows = await memory_ledger.fetch(cid)
    execute_tools = [
        (r["payload"] or {}).get("tool")
        for r in rows
        if r["kind"] == "execute"
    ]
    assert "emit_tenant_signup_initiated" in execute_tools


async def test_post_signup_completed_happy_path(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    resp = await client.post(
        "/api/v1/tenants/signup-completed",
        headers=_auth_headers(),
        json=_valid_completed_body(),
    )
    assert resp.status == 201, await resp.text()
    body = await resp.json()
    assert len(body["entry_ids"]) == 4

    cid = tenant_to_uuid(TENANT_SLUG)
    rows = await memory_ledger.fetch(cid)
    execute_tools = [
        (r["payload"] or {}).get("tool")
        for r in rows
        if r["kind"] == "execute"
    ]
    assert "emit_tenant_signup_completed" in execute_tools


async def test_post_signup_initiated_rejects_invalid_signup_source(
    client: TestClient,
) -> None:
    body = _valid_initiated_body()
    body["signup_source"] = "evil_source"
    resp = await client.post(
        "/api/v1/tenants/signup-initiated",
        headers=_auth_headers(),
        json=body,
    )
    # Pydantic regex fails first at body parse → 422.
    assert resp.status in (400, 422)


async def test_post_signup_initiated_rejects_short_token_hash(
    client: TestClient,
) -> None:
    body = _valid_initiated_body()
    body["pending_token_hash"] = "abc"
    resp = await client.post(
        "/api/v1/tenants/signup-initiated",
        headers=_auth_headers(),
        json=body,
    )
    assert resp.status in (400, 422)


async def test_signup_chain_isolated_across_tenants(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """A signup for tenant A does not leak into tenant B's ledger."""
    # Tenant A
    body_a = _valid_initiated_body()
    body_a["slug"] = "baseworm"
    body_a["tenant_id"] = str(tenant_to_uuid("baseworm"))
    resp = await client.post(
        "/api/v1/tenants/signup-initiated",
        headers=_auth_headers(tenant="baseworm"),
        json=body_a,
    )
    assert resp.status == 201

    # Tenant B
    body_b = dict(body_a)
    body_b["slug"] = "democorp"
    body_b["tenant_id"] = str(tenant_to_uuid("democorp"))
    body_b["signup_email"] = "b@b.com"
    resp = await client.post(
        "/api/v1/tenants/signup-initiated",
        headers=_auth_headers(tenant="democorp"),
        json=body_b,
    )
    assert resp.status == 201

    cid_a = tenant_to_uuid("baseworm")
    cid_b = tenant_to_uuid("democorp")
    rows_a = await memory_ledger.fetch(cid_a)
    rows_b = await memory_ledger.fetch(cid_b)
    text_a = repr(rows_a)
    text_b = repr(rows_b)
    assert "democorp" not in text_a
    assert "b@b.com" not in text_a
    assert "baseworm" not in text_b
    assert "founder@baseworm.test" not in text_b
