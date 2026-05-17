"""DELETE /api/v1/write_actions/agents_revoke/{agent_id} — v1.4 follow-up (Path 5).

Backs the agent detail page's Revoke button. Revoking an agent =
cascading-revoke over every active grant the agent holds, each written
as an ``agent_grant`` (status=``revoked``) PEVR cycle — the canonical
Addendum 3 single-kind-with-status pattern. No new ledger entry kind is
introduced.

Coverage:
- Happy revoke: agent with N active grants → N PEVR cycles (4 entries each).
- Idempotent: no active grants → 200 with revoked_grant_count=0, no writes.
- Unknown reason rejected (422).
- company_id mismatch rejected (400).
- Missing agent_id rejected (404 via routing) — covered by route shape.
- Auth + tenant routing mirrors the subscription-revoke pattern.
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

API_TOKEN = "test-token-agent-revoke"
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


async def test_revoke_agent_with_two_grants_writes_two_revoke_cycles(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Agent with N active grants → N revoke PEVR cycles."""
    company_id = _company_id()
    admin_id = uuid4()
    domain_a = uuid4()
    domain_b = uuid4()

    # Pre-register an agent with two domain.read grants.
    agent_uuid, _ = await write_actions.register_agent(
        memory_ledger,
        company_id,
        external_provider="claude",
        display_name="Pre-existing agent",
        domain_read_ids=[domain_a, domain_b],
        registered_by=admin_id,
    )
    agent_id = str(agent_uuid)

    # Count baseline entries (1 PEVR + 2 grant PEVR = 12 entries).
    rows_before = await memory_ledger.fetch(company_id)
    baseline = len(rows_before)
    assert baseline == 12

    resp = await client.delete(
        f"/api/v1/write_actions/agents_revoke/{agent_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "reason": "admin_revoked",
            "revoked_by": str(admin_id),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["revoked"] is True
    assert body["agent_id"] == agent_id
    assert body["agentId"] == agent_id
    assert body["revoked_grant_count"] == 2
    assert body["revokedGrantCount"] == 2

    rows = await memory_ledger.fetch(company_id)
    # Two revoke cycles × 4 entries = 8 more entries.
    assert len(rows) == baseline + 8
    # The two new execute entries should be agent_grant with status=revoked.
    execute_rows = [r for r in rows if r["kind"] == "execute"]
    revoked_execs = [
        r for r in execute_rows
        if r["payload"].get("tool") == "emit_agent_grant"
        and (r["payload"].get("args") or {}).get("status") == "revoked"
    ]
    assert len(revoked_execs) == 2
    # All revokes target the same agent_id.
    for r in revoked_execs:
        assert r["payload"]["args"]["agent_id"] == agent_id
        assert r["payload"]["args"]["granted_by"] == str(admin_id)
        assert r["payload"]["args"]["grant_kind"] == "domain.read"


async def test_revoke_agent_with_no_active_grants_is_idempotent(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Revoking an agent with no active grants → 200, count=0, no writes."""
    company_id = _company_id()
    admin_id = uuid4()
    agent_id = str(uuid4())  # never registered

    rows_before = await memory_ledger.fetch(company_id)
    baseline = len(rows_before)

    resp = await client.delete(
        f"/api/v1/write_actions/agents_revoke/{agent_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "reason": "admin_revoked",
            "revoked_by": str(admin_id),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["revoked"] is True
    assert body["revoked_grant_count"] == 0

    rows_after = await memory_ledger.fetch(company_id)
    assert len(rows_after) == baseline  # no writes


async def test_revoke_agent_double_revoke_is_idempotent(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Re-revoking an already-revoked agent is a no-op."""
    company_id = _company_id()
    admin_id = uuid4()
    domain_a = uuid4()

    agent_uuid, _ = await write_actions.register_agent(
        memory_ledger,
        company_id,
        external_provider="claude",
        display_name="Single-grant agent",
        domain_read_ids=[domain_a],
        registered_by=admin_id,
    )
    agent_id = str(agent_uuid)

    # First revoke.
    resp1 = await client.delete(
        f"/api/v1/write_actions/agents_revoke/{agent_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "reason": "admin_revoked",
            "revoked_by": str(admin_id),
        },
    )
    assert resp1.status == 200
    body1 = await resp1.json()
    assert body1["revoked_grant_count"] == 1

    rows_after_first = await memory_ledger.fetch(company_id)
    baseline = len(rows_after_first)

    # Second revoke — no active grants remain, so this is a no-op.
    resp2 = await client.delete(
        f"/api/v1/write_actions/agents_revoke/{agent_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "reason": "admin_revoked",
            "revoked_by": str(admin_id),
        },
    )
    assert resp2.status == 200
    body2 = await resp2.json()
    assert body2["revoked_grant_count"] == 0

    rows_after_second = await memory_ledger.fetch(company_id)
    assert len(rows_after_second) == baseline


async def test_revoke_agent_unknown_reason_rejected(
    client: TestClient,
) -> None:
    """Reason outside the canonical enum → 422."""
    agent_id = str(uuid4())
    resp = await client.delete(
        f"/api/v1/write_actions/agents_revoke/{agent_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "reason": "vibes_were_off",
            "revoked_by": str(uuid4()),
        },
    )
    assert resp.status == 422


async def test_revoke_agent_company_id_mismatch_rejected(
    client: TestClient,
) -> None:
    """Body company_id ≠ header tenant → 400."""
    agent_id = str(uuid4())
    other_company = uuid4()
    resp = await client.delete(
        f"/api/v1/write_actions/agents_revoke/{agent_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(other_company),
            "reason": "admin_revoked",
            "revoked_by": str(uuid4()),
        },
    )
    assert resp.status == 400


async def test_revoke_agent_requires_bearer_token(
    client: TestClient,
) -> None:
    """Missing bearer → 401."""
    agent_id = str(uuid4())
    resp = await client.delete(
        f"/api/v1/write_actions/agents_revoke/{agent_id}",
        headers={"X-Tenant-Slug": TENANT_SLUG},
        json={
            "company_id": str(_company_id()),
            "reason": "admin_revoked",
            "revoked_by": str(uuid4()),
        },
    )
    assert resp.status == 401
