"""POST /api/v1/write_actions/agent_subscriptions_create + DELETE — v2.A Task 7.

Backs the v2.A dashboard subscription path: the admin-create / admin-revoke
flow on /people/agents/[id]/subscriptions. The MCP-tool path
(agent self-management) goes through ``packages/wormbase-agent-gateway/
.../subscriptions/mcp_tools.py``; both paths land the same canonical
entry kinds (``emit_agent_subscription_created`` /
``emit_agent_subscription_revoked``) so the LedgerSubscriptionReader
projects the union with one scan.

Coverage:
- Happy create: writes one PEVR cycle (4 entries).
- Wildcard filter rejected (422).
- Unknown transport rejected (422).
- Webhook transport requires url + secret_ref (422 when either missing).
- Happy revoke: writes one PEVR cycle (4 entries).
- Unknown revoke reason rejected (422).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from wormbase_core.http_api import build_app
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger

API_TOKEN = "test-token-agent-subs"
TENANT_SLUG = "baseworm"


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "X-Tenant-Slug": TENANT_SLUG,
    }


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


def _company_id() -> UUID:
    return tenant_to_uuid(TENANT_SLUG)


async def test_create_subscription_happy_path(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Create with one filter axis → one PEVR cycle (4 entries)."""
    admin_id = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/agent_subscriptions_create",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "agent_id": "agent_xyz",
            "filter": {
                "kinds": ["bad_pattern_proposed"],
                "domains": [],
                "agent_id_ref": None,
                "payload_path_eq": [],
            },
            "transport": "mcp_stream",
            "webhook_url": None,
            "webhook_secret_ref": None,
            "description": "MY bad-pattern alerts",
            "granted_by": str(admin_id),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert "subscription_id" in body
    assert "subscriptionId" in body
    assert body["subscription_id"] == body["subscriptionId"]
    assert UUID(body["subscription_id"])

    rows = await memory_ledger.fetch(_company_id())
    assert len(rows) == 4  # 1 PEVR cycle = 4 entries
    execute_rows = [r for r in rows if r["kind"] == "execute"]
    assert len(execute_rows) == 1
    assert execute_rows[0]["payload"]["tool"] == "emit_agent_subscription_created"
    args = execute_rows[0]["payload"]["args"]
    assert args["agent_id"] == "agent_xyz"
    assert args["transport"] == "mcp_stream"
    assert args["filter"]["kinds"] == ["bad_pattern_proposed"]
    assert args["description"] == "MY bad-pattern alerts"
    assert args["granted_by"] == str(admin_id)


async def test_create_subscription_wildcard_filter_rejected(
    client: TestClient,
) -> None:
    """Empty filter (would match every entry) → 422."""
    resp = await client.post(
        "/api/v1/write_actions/agent_subscriptions_create",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "agent_id": "agent_xyz",
            "filter": {
                "kinds": [],
                "domains": [],
                "agent_id_ref": None,
                "payload_path_eq": [],
            },
            "transport": "mcp_stream",
            "granted_by": str(uuid4()),
        },
    )
    assert resp.status == 422


async def test_create_subscription_unknown_transport_rejected(
    client: TestClient,
) -> None:
    """``transport != mcp_stream | webhook`` → 422."""
    resp = await client.post(
        "/api/v1/write_actions/agent_subscriptions_create",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "agent_id": "agent_xyz",
            "filter": {"kinds": ["bad_pattern_proposed"]},
            "transport": "smoke_signal",
            "granted_by": str(uuid4()),
        },
    )
    assert resp.status == 422


async def test_create_subscription_webhook_requires_url_and_secret(
    client: TestClient,
) -> None:
    """Webhook transport without url or secret_ref → 422."""
    resp = await client.post(
        "/api/v1/write_actions/agent_subscriptions_create",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "agent_id": "agent_xyz",
            "filter": {"kinds": ["bad_pattern_proposed"]},
            "transport": "webhook",
            "webhook_url": None,
            "webhook_secret_ref": None,
            "granted_by": str(uuid4()),
        },
    )
    assert resp.status == 422


async def test_revoke_subscription_happy_path(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Revoke writes one ``emit_agent_subscription_revoked`` PEVR cycle."""
    sub_id = str(uuid4())
    admin_id = uuid4()
    resp = await client.delete(
        f"/api/v1/write_actions/agent_subscriptions_revoke/{sub_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "reason": "admin_revoked",
            "revoked_by": str(admin_id),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["revoked"] is True
    assert body["subscription_id"] == sub_id

    rows = await memory_ledger.fetch(_company_id())
    assert len(rows) == 4
    execute_rows = [r for r in rows if r["kind"] == "execute"]
    assert execute_rows[0]["payload"]["tool"] == "emit_agent_subscription_revoked"
    args = execute_rows[0]["payload"]["args"]
    assert args["subscription_id"] == sub_id
    assert args["reason"] == "admin_revoked"
    assert args["revoked_by"] == str(admin_id)


async def test_revoke_subscription_unknown_reason_rejected(
    client: TestClient,
) -> None:
    """Reason outside the canonical enum → 422."""
    sub_id = str(uuid4())
    resp = await client.delete(
        f"/api/v1/write_actions/agent_subscriptions_revoke/{sub_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "reason": "vibes_were_off",
            "revoked_by": str(uuid4()),
        },
    )
    assert resp.status == 422
