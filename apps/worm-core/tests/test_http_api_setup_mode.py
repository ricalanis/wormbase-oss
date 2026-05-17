"""HTTP API tests for ``POST /api/v1/setup-mode`` — Block G4.

The endpoint runs a single PEVR cycle that writes
``emit_setup_mode_chosen``. The projection stamps every install row for
the tenant so the dashboard's redirect guard can resolve the choice in
one query.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

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


def _auth_headers(
    *, token: str = API_TOKEN, tenant: str = TENANT_SLUG,
) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Slug": tenant,
    }


def _valid_body() -> dict[str, object]:
    return {
        "mode": "wizard",
        "chosen_by_person_id": str(uuid4()),
    }


async def test_post_setup_mode_missing_auth_returns_401(
    client: TestClient,
) -> None:
    resp = await client.post("/api/v1/setup-mode", json=_valid_body())
    assert resp.status == 401


async def test_post_setup_mode_wizard_writes_pevr_cycle(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    resp = await client.post(
        "/api/v1/setup-mode",
        headers=_auth_headers(),
        json=_valid_body(),
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    # One PEVR cycle = 4 entries
    assert len(body["entry_ids"]) == 4

    company_id = tenant_to_uuid(TENANT_SLUG)
    rows = await memory_ledger.fetch(company_id)
    assert len(rows) == 4

    tools = [
        r["payload"]["tool"] for r in rows if r["kind"] == "execute"
    ]
    assert tools == ["emit_setup_mode_chosen"]

    # Payload carries mode + chosen_by + tenant_id
    execute_args = next(
        r["payload"]["args"] for r in rows if r["kind"] == "execute"
    )
    assert execute_args["mode"] == "wizard"
    assert "chosen_by_person_id" in execute_args
    assert "tenant_id" in execute_args


async def test_post_setup_mode_bot_path(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    body = _valid_body()
    body["mode"] = "bot"
    resp = await client.post(
        "/api/v1/setup-mode",
        headers=_auth_headers(),
        json=body,
    )
    assert resp.status == 200, await resp.text()

    company_id = tenant_to_uuid(TENANT_SLUG)
    rows = await memory_ledger.fetch(company_id)
    execute_args = next(
        r["payload"]["args"] for r in rows if r["kind"] == "execute"
    )
    assert execute_args["mode"] == "bot"


async def test_post_setup_mode_rejects_invalid_mode(
    client: TestClient,
) -> None:
    body = _valid_body()
    body["mode"] = "neither"
    resp = await client.post(
        "/api/v1/setup-mode",
        headers=_auth_headers(),
        json=body,
    )
    assert resp.status == 422


async def test_post_setup_mode_rejects_non_uuid_chooser(
    client: TestClient,
) -> None:
    body = _valid_body()
    body["chosen_by_person_id"] = "not-a-uuid"
    resp = await client.post(
        "/api/v1/setup-mode",
        headers=_auth_headers(),
        json=body,
    )
    assert resp.status == 422
