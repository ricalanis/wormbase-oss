"""HTTP-endpoint tests for the merge/split routes (A6).

Exercises the bearer-authed POST /api/v1/people/merge and
POST /api/v1/people/{source_person_id}/split endpoints against the
in-memory ledger via aiohttp's TestClient harness — same pattern as
test_http_api.py.
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

API_TOKEN = "test-token-456"
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


async def _seed_two_persons(
    memory_ledger: InMemoryLedger,
) -> tuple[UUID, UUID]:
    company_id = tenant_to_uuid(TENANT_SLUG)
    p1, _ = await write_actions.propose_person(
        memory_ledger, company_id, name="Bob", email="bob@x.co",
        platform="slack", platform_user_id="U-bob",
        position=None, proposed_by="worm",
    )
    p2, _ = await write_actions.propose_person(
        memory_ledger, company_id, name="Bob M", email="bob@x.co",
        platform="discord", platform_user_id="bob#1234",
        position=None, proposed_by="worm",
    )
    return p1, p2


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


async def test_merge_missing_auth_returns_401(client: TestClient) -> None:
    resp = await client.post(
        "/api/v1/people/merge",
        json={
            "keeper_id": str(uuid4()),
            "mergee_id": str(uuid4()),
            "merged_by": str(uuid4()),
        },
    )
    assert resp.status == 401


async def test_split_missing_auth_returns_401(client: TestClient) -> None:
    resp = await client.post(
        f"/api/v1/people/{uuid4()}/split",
        json={
            "new_person_name": "X",
            "identities_to_move": [
                {"platform": "slack", "platform_user_id": "U-x"},
            ],
            "split_by": str(uuid4()),
        },
    )
    assert resp.status == 401


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


async def test_merge_success_returns_expected_shape(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    p1, p2 = await _seed_two_persons(memory_ledger)
    admin = str(uuid4())
    resp = await client.post(
        "/api/v1/people/merge",
        headers=_auth_headers(),
        json={
            "keeper_id": str(p1),
            "mergee_id": str(p2),
            "merged_by": admin,
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["keeper_id"] == str(p1)
    assert body["mergee_id"] == str(p2)
    assert body["identities_moved"] == 1
    # 1 unlink + 1 link + 1 archive = 3 PEVR cycles = 12 entry_ids.
    assert len(body["entry_ids"]) == 12

    # Hash chain still valid after the sequence of writes.
    company_id = tenant_to_uuid(TENANT_SLUG)
    rows = await memory_ledger.fetch(company_id)
    ok, _ = verify_chain(rows)
    assert ok


async def test_merge_keeper_equals_mergee_returns_422(
    client: TestClient,
) -> None:
    same = str(uuid4())
    resp = await client.post(
        "/api/v1/people/merge",
        headers=_auth_headers(),
        json={
            "keeper_id": same,
            "mergee_id": same,
            "merged_by": str(uuid4()),
        },
    )
    assert resp.status == 422


async def test_merge_invalid_uuid_returns_422(client: TestClient) -> None:
    resp = await client.post(
        "/api/v1/people/merge",
        headers=_auth_headers(),
        json={
            "keeper_id": "not-a-uuid",
            "mergee_id": str(uuid4()),
            "merged_by": str(uuid4()),
        },
    )
    assert resp.status == 422


async def test_merge_extra_fields_rejected(client: TestClient) -> None:
    resp = await client.post(
        "/api/v1/people/merge",
        headers=_auth_headers(),
        json={
            "keeper_id": str(uuid4()),
            "mergee_id": str(uuid4()),
            "merged_by": str(uuid4()),
            "rogue_field": "evil",
        },
    )
    assert resp.status == 422


# ---------------------------------------------------------------------------
# Split
# ---------------------------------------------------------------------------


async def test_split_success_returns_expected_shape(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    company_id = tenant_to_uuid(TENANT_SLUG)
    src, _ = await write_actions.propose_person(
        memory_ledger, company_id, name="Alice + Bob", email=None,
        platform="slack", platform_user_id="U-alice",
        position=None, proposed_by="worm",
    )
    await write_actions.link_identity(
        memory_ledger, company_id, person_id=src,
        platform="discord", platform_user_id="bob#1234",
        linked_by=uuid4(),
    )
    admin = str(uuid4())
    resp = await client.post(
        f"/api/v1/people/{src}/split",
        headers=_auth_headers(),
        json={
            "new_person_name": "Bob",
            "new_person_email": "bob@x.co",
            "new_person_position": "engineer",
            "identities_to_move": [
                {"platform": "discord", "platform_user_id": "bob#1234"},
            ],
            "split_by": admin,
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["source_person_id"] == str(src)
    assert UUID(body["new_person_id"])
    assert body["identities_moved"] == 1
    # 1 propose + 1 unlink (seed) = 2 PEVR cycles = 8 entries.
    assert len(body["entry_ids"]) == 8

    rows = await memory_ledger.fetch(company_id)
    ok, _ = verify_chain(rows)
    assert ok


async def test_split_empty_identities_returns_422(client: TestClient) -> None:
    resp = await client.post(
        f"/api/v1/people/{uuid4()}/split",
        headers=_auth_headers(),
        json={
            "new_person_name": "X",
            "identities_to_move": [],
            "split_by": str(uuid4()),
        },
    )
    assert resp.status == 422


async def test_split_invalid_path_uuid_returns_400(client: TestClient) -> None:
    resp = await client.post(
        "/api/v1/people/not-a-uuid/split",
        headers=_auth_headers(),
        json={
            "new_person_name": "X",
            "identities_to_move": [
                {"platform": "slack", "platform_user_id": "U-x"},
            ],
            "split_by": str(uuid4()),
        },
    )
    assert resp.status == 400


async def test_split_missing_new_name_returns_422(client: TestClient) -> None:
    resp = await client.post(
        f"/api/v1/people/{uuid4()}/split",
        headers=_auth_headers(),
        json={
            "new_person_name": "",
            "identities_to_move": [
                {"platform": "slack", "platform_user_id": "U-x"},
            ],
            "split_by": str(uuid4()),
        },
    )
    assert resp.status == 422
