"""HTTP-endpoint tests for the bulk-confirm route (W2.A6).

Exercises the bearer-authed POST /api/v1/people/bulk-confirm endpoint
against the in-memory ledger via aiohttp's TestClient harness — same
pattern as test_http_api_merge_split.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core import write_actions
from wormbase_core.http_api import build_app
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.hash_chain import verify_chain

API_TOKEN = "test-token-bulk"
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


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "X-Tenant-Slug": TENANT_SLUG,
    }


async def _seed_n_proposed(
    memory_ledger: InMemoryLedger, n: int,
) -> list[UUID]:
    company_id = tenant_to_uuid(TENANT_SLUG)
    pids: list[UUID] = []
    for i in range(n):
        pid, _ = await write_actions.propose_person(
            memory_ledger, company_id,
            name=f"P{i}", email=f"p{i}@x.co",
            platform="slack", platform_user_id=f"U-{i}",
            position=None, proposed_by="worm",
        )
        pids.append(pid)
    return pids


async def test_bulk_confirm_missing_auth_returns_401(client: TestClient) -> None:
    resp = await client.post(
        "/api/v1/people/bulk-confirm",
        json={"person_ids": [str(uuid4())], "confirmed_by": str(uuid4())},
    )
    assert resp.status == 401


async def test_bulk_confirm_success(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    pids = await _seed_n_proposed(memory_ledger, n=3)
    admin = str(uuid4())
    resp = await client.post(
        "/api/v1/people/bulk-confirm",
        headers=_auth_headers(),
        json={
            "person_ids": [str(p) for p in pids],
            "confirmed_by": admin,
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["confirmed_count"] == 3
    assert body["person_ids"] == [str(p) for p in pids]
    assert len(body["entry_ids"]) == 4 * 3

    rows = await memory_ledger.fetch(tenant_to_uuid(TENANT_SLUG))
    ok, broken_at = verify_chain(rows)
    assert ok, f"chain broken at seq {broken_at}"


async def test_bulk_confirm_empty_returns_422(client: TestClient) -> None:
    resp = await client.post(
        "/api/v1/people/bulk-confirm",
        headers=_auth_headers(),
        json={"person_ids": [], "confirmed_by": str(uuid4())},
    )
    # Pydantic Field(min_length=1) rejects empty list at the API boundary.
    assert resp.status == 422
