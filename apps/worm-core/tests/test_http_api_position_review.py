"""HTTP-API tests for the position-review queue (Wave H Phase 2 Task 2C).

Three endpoints land:

  * ``GET  /api/v1/people/proposals`` — returns pending position
    proposals for the tenant.
  * ``POST /api/v1/people/{person_id}/position/confirm`` — admin
    confirm of a worm-proposed position.
  * ``POST /api/v1/people/{person_id}/position/reject`` — admin reject.

Tests pin: 401 on missing auth, 422 on invalid bodies, queue dedup
across propose/confirm/reject sequences, hash-chain validity after
each write, and that the GET filters out proposals already
confirmed/rejected/superseded.
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


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "X-Tenant-Slug": TENANT_SLUG,
    }


async def _seed_proposed_position(
    client: TestClient, memory_ledger: InMemoryLedger,
    *, name: str = "Alice",
    platform_user_id: str = "U-alice",
    position: str = "senior_engineer",
) -> UUID:
    """Seed a Person + a worm-inferred position proposal."""
    company_id = tenant_to_uuid(TENANT_SLUG)
    person_id, _ = await write_actions.propose_person(
        memory_ledger, company_id,
        name=name, email=None,
        platform="slack", platform_user_id=platform_user_id,
        position=None, proposed_by="worm",
    )
    await write_actions.propose_position(
        memory_ledger, company_id,
        person_id=person_id, position=position,
        confidence=0.7, signals=("commit_msg",),
        proposed_by="worm",
    )
    return person_id


async def test_get_proposals_requires_auth(client: TestClient) -> None:
    resp = await client.get("/api/v1/people/proposals")
    assert resp.status == 401


async def test_get_proposals_returns_pending(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    pid_a = await _seed_proposed_position(
        client, memory_ledger,
        name="Alice", platform_user_id="U-a", position="senior_engineer",
    )
    pid_b = await _seed_proposed_position(
        client, memory_ledger,
        name="Bob", platform_user_id="U-b", position="data_analyst",
    )

    resp = await client.get(
        "/api/v1/people/proposals", headers=_auth_headers(),
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    proposals = body["proposals"]
    assert len(proposals) == 2

    by_pid = {p["person_id"]: p for p in proposals}
    assert by_pid[str(pid_a)]["position"] == "senior_engineer"
    assert by_pid[str(pid_a)]["person_name"] == "Alice"
    assert by_pid[str(pid_a)]["confidence"] == 0.7
    assert by_pid[str(pid_a)]["signals"] == ["commit_msg"]
    assert by_pid[str(pid_b)]["position"] == "data_analyst"


async def test_confirm_position_writes_pevr_and_dequeues(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    person_id = await _seed_proposed_position(client, memory_ledger)
    admin = str(uuid4())

    resp = await client.post(
        f"/api/v1/people/{person_id}/position/confirm",
        headers=_auth_headers(),
        json={"position": "senior_engineer", "confirmed_by": admin},
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert len(body["entry_ids"]) == 4

    # Queue is now empty.
    resp = await client.get(
        "/api/v1/people/proposals", headers=_auth_headers(),
    )
    body = await resp.json()
    assert body["proposals"] == []

    # Hash chain stays valid.
    company_id = tenant_to_uuid(TENANT_SLUG)
    rows = await memory_ledger.fetch(company_id)
    ok, _ = verify_chain(rows)
    assert ok


async def test_reject_position_writes_pevr_and_dequeues(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    person_id = await _seed_proposed_position(client, memory_ledger)
    admin = str(uuid4())

    resp = await client.post(
        f"/api/v1/people/{person_id}/position/reject",
        headers=_auth_headers(),
        json={
            "position": "senior_engineer",
            "rejected_by": admin,
            "reason": "joined as analyst",
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert len(body["entry_ids"]) == 4

    # Queue is now empty.
    resp = await client.get(
        "/api/v1/people/proposals", headers=_auth_headers(),
    )
    body = await resp.json()
    assert body["proposals"] == []

    # Reason was persisted on the entry.
    company_id = tenant_to_uuid(TENANT_SLUG)
    rows = await memory_ledger.fetch(company_id)
    rejects = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_position_rejected"
    ]
    assert len(rejects) == 1
    assert rejects[0]["payload"]["args"]["reason"] == "joined as analyst"


async def test_confirm_validation_failure_returns_422(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    person_id = await _seed_proposed_position(client, memory_ledger)
    resp = await client.post(
        f"/api/v1/people/{person_id}/position/confirm",
        headers=_auth_headers(),
        json={"position": "", "confirmed_by": str(uuid4())},
    )
    assert resp.status == 422


async def test_reject_optional_reason(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    person_id = await _seed_proposed_position(client, memory_ledger)
    admin = str(uuid4())

    resp = await client.post(
        f"/api/v1/people/{person_id}/position/reject",
        headers=_auth_headers(),
        json={"position": "senior_engineer", "rejected_by": admin},
    )
    assert resp.status == 200, await resp.text()


async def test_proposals_route_does_not_collide_with_split(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """``/people/proposals`` must not be matched as a UUID-shaped split path.

    Reordering the routes is the safety net; this test pins the safety
    net so a future refactor cannot silently re-introduce the
    collision.
    """
    resp = await client.get(
        "/api/v1/people/proposals", headers=_auth_headers(),
    )
    assert resp.status == 200
    # Must not 400 with "path segment source_person_id must be a UUID".
    body = await resp.json()
    assert "proposals" in body
