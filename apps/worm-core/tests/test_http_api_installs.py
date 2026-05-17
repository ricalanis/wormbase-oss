"""HTTP API tests for ``POST /api/v1/installs`` — Tier 1 OAuth callback.

The endpoint orchestrates the full post-OAuth chain (propose installer
Person → confirm → grant tenancy.installer + tenancy.admin → emit
install_completed) — five PEVR cycles. Bearer-authed; multi-tenant via
X-Tenant-Slug.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core.http_api import build_app
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger


API_TOKEN = "test-token-123"
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


def _valid_body() -> dict[str, object]:
    return {
        "platform": "slack",
        "installer_email": "carol@x.co",
        "installer_name": "Carol Reyes",
        "installer_avatar_url": None,
        "platform_user_id": "UCAROL",
        "oauth_grant_ref": "vault://local-dev/abc123",
        "scopes": ["channels:read", "chat:write"],
        "bot_user_id": "UBOT",
    }


async def test_post_installs_missing_auth_returns_401(client: TestClient) -> None:
    resp = await client.post("/api/v1/installs", json=_valid_body())
    assert resp.status == 401


async def test_post_installs_happy_path_writes_full_chain(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    resp = await client.post(
        "/api/v1/installs",
        headers=_auth_headers(),
        json=_valid_body(),
    )
    assert resp.status == 201, await resp.text()
    body = await resp.json()
    assert UUID(body["install_id"])
    assert UUID(body["installer_person_id"])
    # Block I (production-dashboard PRD §17): complete_install now also
    # auto-provisions the default local lake (4 PEVR cycles, 16 entries).
    # Total: 5 install + 4 lake = 9 cycles × 4 = 36 entries.
    assert UUID(body["local_lake_source_id"])
    assert len(body["entry_ids"]) == 36

    company_id = tenant_to_uuid(TENANT_SLUG)
    rows = await memory_ledger.fetch(company_id)
    assert len(rows) == 36

    tools = [r["payload"]["tool"] for r in rows if r["kind"] == "execute"]
    assert tools == [
        "emit_person_proposed",
        "emit_person_confirmed",
        "emit_role_assigned",
        "emit_role_assigned",
        "emit_install_completed",
        "emit_source_proposed",
        "emit_source_confirmed",
        "emit_source_connected",
        "emit_source_profiled",
    ]


async def test_post_installs_rejects_raw_bearer_token(client: TestClient) -> None:
    body = _valid_body()
    body["oauth_grant_ref"] = "xoxb-raw-token"
    resp = await client.post(
        "/api/v1/installs", headers=_auth_headers(), json=body,
    )
    assert resp.status == 422, await resp.text()


async def test_post_installs_rejects_dev_prefix(client: TestClient) -> None:
    """Regression guard: ``dev://`` was the deleted synthesized-grant
    shape. The Pydantic validator only accepts ``kms://`` / ``vault://``.
    """
    body = _valid_body()
    body["oauth_grant_ref"] = "dev://wormbase/baseworm/slack/abc"
    resp = await client.post(
        "/api/v1/installs", headers=_auth_headers(), json=body,
    )
    assert resp.status == 422, await resp.text()


async def test_post_installs_validation_failure_returns_422(
    client: TestClient,
) -> None:
    """Empty installer_email fails Field(min_length=1)."""
    body = _valid_body()
    body["installer_email"] = ""
    resp = await client.post(
        "/api/v1/installs", headers=_auth_headers(), json=body,
    )
    assert resp.status == 422


async def test_post_installs_unknown_field_returns_422(client: TestClient) -> None:
    """``extra="forbid"`` on _Body rejects unknown payload fields."""
    body = _valid_body()
    body["nonsense_field"] = "x"
    resp = await client.post(
        "/api/v1/installs", headers=_auth_headers(), json=body,
    )
    assert resp.status == 422


# ─── GET /api/v1/installs (W7.A3) ────────────────────────────────────


async def test_get_installs_empty_tenant_returns_empty_list(
    client: TestClient,
) -> None:
    """A tenant with no install rows must return ``{"installs": []}``.

    Never 404 — callers (the demo orchestrator's pre-flight probe)
    distinguish "no install" from "endpoint missing" by status code.
    """
    resp = await client.get("/api/v1/installs", headers=_auth_headers())
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body == {"installs": []}


async def test_get_installs_missing_auth_returns_401(client: TestClient) -> None:
    resp = await client.get("/api/v1/installs")
    assert resp.status == 401


async def test_get_installs_after_post_returns_active_row(
    client: TestClient,
) -> None:
    """Posting a complete install must surface the active row on GET."""
    post = await client.post(
        "/api/v1/installs", headers=_auth_headers(), json=_valid_body(),
    )
    assert post.status == 201, await post.text()
    posted = await post.json()

    resp = await client.get("/api/v1/installs", headers=_auth_headers())
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    rows = body["installs"]
    assert len(rows) == 1, f"expected one install row, got {rows}"
    row = rows[0]
    assert row["install_id"] == posted["install_id"]
    assert row["platform"] == "slack"
    assert row["status"] == "active"
    assert row["installer_person_id"] == posted["installer_person_id"]
    assert row["scopes"] == ["channels:read", "chat:write"]
    assert row["bot_user_id"] == "UBOT"
    assert row["oauth_grant_ref"].startswith("vault://")
    # Tier 1 always carries an installed_at timestamp.
    assert row["installed_at"]

