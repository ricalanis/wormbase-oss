"""L5 integration test for the dashboard → worm-core HTTP write path (A3.5).

Boots the worm-core HTTP write server in-process (aiohttp) backed by an
``InMemoryLedger``, then sends a real HTTP request through the same
``aiohttp.ClientSession`` the dashboard helper would use in production.
Asserts a real, hash-chained ledger entry chain (4 entries: propose,
execute, verify, resolve) lands with valid hash linkage and that
``verify_chain`` returns OK across the entire chain.

Why in-memory: the assertion under test is "the dashboard's request
turns into a real PEVR cycle", not "Postgres is reachable". The
hash-chain semantics in InMemoryLedger are byte-for-byte the same as
the DB-backed Ledger (see ``packages/ledger/src/wormbase_ledger/ledger_api.py``).
This test runs without Docker. The replay determinism harness
(``tests/integration/test_replay_determinism_across_full_stack.py``)
covers the DB-backed surface.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core.http_api import build_app
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.hash_chain import verify_chain


API_TOKEN = "integration-test-token"
TENANT_SLUG = "baseworm"


@pytest_asyncio.fixture
async def ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest_asyncio.fixture
async def http_client(ledger: InMemoryLedger) -> AsyncIterator[TestClient]:
    app = build_app(ledger=ledger, api_token=API_TOKEN)
    server = TestServer(app)
    cli = TestClient(server)
    await cli.start_server()
    try:
        yield cli
    finally:
        await cli.close()


@pytest.mark.integration
async def test_dashboard_post_people_lands_full_pevr_cycle(
    http_client: TestClient, ledger: InMemoryLedger
) -> None:
    """Dashboard's POST /api/people → worm-core's POST /api/v1/people →
    full PEVR cycle in the ledger with a valid hash chain.
    """
    company_id = tenant_to_uuid(TENANT_SLUG)

    resp = await http_client.post(
        "/api/v1/people",
        headers={
            "Authorization": f"Bearer {API_TOKEN}",
            "X-Tenant-Slug": TENANT_SLUG,
            "Content-Type": "application/json",
        },
        json={
            "name": "Alice",
            "email": "alice@example.com",
            "platform": "slack",
            "platform_user_id": "U-alice",
            "position": "data_engineer",
            "proposed_by": "dashboard-admin",
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert "person_id" in body
    assert len(body["entry_ids"]) == 4

    rows = await ledger.fetch(company_id)
    assert len(rows) == 4
    assert [r["kind"] for r in rows] == ["propose", "execute", "verify", "resolve"]

    # Hash-chain integrity end-to-end.
    ok, broken_at = verify_chain(rows)
    assert ok, f"chain broken at index {broken_at}"

    # Every entry's prev_hash matches the previous entry's hash.
    for prev, curr in zip(rows, rows[1:]):
        assert curr["prev_hash"] == prev["hash"], (
            "prev_hash chaining broken between "
            f"seq={prev['seq']} and seq={curr['seq']}"
        )

    # Execute entry carries the canonical tool name + payload args.
    execute = rows[1]["payload"]
    assert execute["tool"] == "emit_person_proposed"
    assert execute["args"]["name"] == "Alice"
    assert execute["args"]["platform_user_id"] == "U-alice"
    # Resolve outcome=keep.
    resolve = rows[3]["payload"]
    assert resolve["outcome"] == "keep"


@pytest.mark.integration
async def test_dashboard_unauthorised_request_does_not_touch_ledger(
    http_client: TestClient, ledger: InMemoryLedger
) -> None:
    company_id = tenant_to_uuid(TENANT_SLUG)
    resp = await http_client.post(
        "/api/v1/people",
        headers={
            # Missing Authorization header.
            "X-Tenant-Slug": TENANT_SLUG,
            "Content-Type": "application/json",
        },
        json={
            "name": "Bob",
            "platform": "slack",
            "platform_user_id": "U-bob",
        },
    )
    assert resp.status == 401
    rows = await ledger.fetch(company_id)
    assert rows == []


@pytest.mark.integration
async def test_dashboard_full_lifecycle_chains_through_propose_confirm_grant(
    http_client: TestClient, ledger: InMemoryLedger
) -> None:
    """A larger PEVR sequence stays hash-chained: propose → confirm → grant role.

    Three high-level operations land 12 ledger rows; verify_chain must
    return OK across the whole chain.
    """
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "X-Tenant-Slug": TENANT_SLUG,
        "Content-Type": "application/json",
    }
    company_id = tenant_to_uuid(TENANT_SLUG)

    # 1. propose
    propose_resp = await http_client.post(
        "/api/v1/people",
        headers=headers,
        json={"name": "Carol", "platform": "slack", "platform_user_id": "U-carol"},
    )
    assert propose_resp.status == 200
    person_id = (await propose_resp.json())["person_id"]

    # 2. confirm
    confirm_resp = await http_client.post(
        f"/api/v1/people/{person_id}/confirm",
        headers=headers,
        json={"confirmed_by": "00000000-0000-0000-0000-0000000000aa"},
    )
    assert confirm_resp.status == 200, await confirm_resp.text()

    # 3. grant tenancy role
    grant_resp = await http_client.post(
        f"/api/v1/people/{person_id}/roles",
        headers=headers,
        json={
            "facet": "tenancy",
            "role": "admin",
            "granted_by": "00000000-0000-0000-0000-0000000000bb",
        },
    )
    assert grant_resp.status == 200, await grant_resp.text()

    rows = await ledger.fetch(company_id)
    assert len(rows) == 12
    ok, broken_at = verify_chain(rows)
    assert ok, f"chain broken at index {broken_at}"
