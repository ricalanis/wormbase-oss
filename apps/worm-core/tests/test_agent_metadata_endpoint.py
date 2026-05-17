"""PATCH /api/v1/write_actions/agents_metadata/{agent_id} —
final wave item #5 (2026-05-13).

Backs the agent detail page's Edit modal. Writes one
``agent_metadata_updated`` PEVR cycle. Preserves agent_id continuity so
grants, subscriptions, and the audit trail stay attached to the same
agent.

Coverage:
- Happy display_name update → 1 PEVR cycle (4 entries).
- Happy description update → 1 PEVR cycle.
- Both fields update → 1 PEVR cycle (status-consolidation: still one
  entry, not two).
- Both fields None → 422 (no-op rejected).
- display_name explicitly empty → 422 (can't clear display_name).
- company_id mismatch → 400.
- Missing bearer → 401.
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

API_TOKEN = "test-token-agent-metadata"
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


async def _register_agent(memory_ledger: InMemoryLedger) -> tuple[str, UUID]:
    """Pre-register an agent and return (agent_id, admin_id)."""
    company_id = _company_id()
    admin_id = uuid4()
    agent_uuid, _ = await write_actions.register_agent(
        memory_ledger,
        company_id,
        external_provider="claude",
        display_name="Original Agent Name",
        registered_by=admin_id,
    )
    return str(agent_uuid), admin_id


async def test_update_display_name_writes_one_pevr_cycle(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Happy path: PATCH with display_name → one agent_metadata_updated
    PEVR cycle (4 entries)."""
    company_id = _company_id()
    agent_id, admin_id = await _register_agent(memory_ledger)

    rows_before = await memory_ledger.fetch(company_id)
    baseline = len(rows_before)

    resp = await client.patch(
        f"/api/v1/write_actions/agents_metadata/{agent_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "display_name": "Renamed Agent",
            "updated_by": str(admin_id),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["updated"] is True
    assert body["agent_id"] == agent_id
    assert body["agentId"] == agent_id

    rows_after = await memory_ledger.fetch(company_id)
    # One PEVR cycle = 4 entries (propose / execute / verify / resolve).
    assert len(rows_after) == baseline + 4

    execute_rows = [r for r in rows_after if r["kind"] == "execute"]
    metadata_execs = [
        r for r in execute_rows
        if r["payload"].get("tool") == "emit_agent_metadata_updated"
    ]
    assert len(metadata_execs) == 1
    args = metadata_execs[0]["payload"]["args"]
    assert args["agent_id"] == agent_id
    assert args["display_name"] == "Renamed Agent"
    assert args["description"] is None
    assert args["updated_by_person_id"] == str(admin_id)


async def test_update_description_only_writes_one_pevr_cycle(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Description-only update — display_name None means unchanged."""
    company_id = _company_id()
    agent_id, admin_id = await _register_agent(memory_ledger)

    rows_before = await memory_ledger.fetch(company_id)
    baseline = len(rows_before)

    resp = await client.patch(
        f"/api/v1/write_actions/agents_metadata/{agent_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "description": "Daily DS agent for the finance team.",
            "reason": "quarterly scope refresh",
            "updated_by": str(admin_id),
        },
    )
    assert resp.status == 200, await resp.text()

    rows_after = await memory_ledger.fetch(company_id)
    assert len(rows_after) == baseline + 4

    execute_rows = [r for r in rows_after if r["kind"] == "execute"]
    metadata_execs = [
        r for r in execute_rows
        if r["payload"].get("tool") == "emit_agent_metadata_updated"
    ]
    assert len(metadata_execs) == 1
    args = metadata_execs[0]["payload"]["args"]
    assert args["display_name"] is None
    assert args["description"] == "Daily DS agent for the finance team."
    assert args["reason"] == "quarterly scope refresh"


async def test_update_both_fields_writes_one_consolidated_cycle(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Both fields in one request → one consolidated PEVR cycle (not two).

    Status-consolidation observed: the kind is mutable-metadata, not
    per-field. Two simultaneous changes write one entry covering both.
    """
    company_id = _company_id()
    agent_id, admin_id = await _register_agent(memory_ledger)

    rows_before = await memory_ledger.fetch(company_id)
    baseline = len(rows_before)

    resp = await client.patch(
        f"/api/v1/write_actions/agents_metadata/{agent_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "display_name": "Compliance DS Agent",
            "description": "Now also covers SOX controls.",
            "updated_by": str(admin_id),
        },
    )
    assert resp.status == 200, await resp.text()

    rows_after = await memory_ledger.fetch(company_id)
    assert len(rows_after) == baseline + 4  # one cycle, not two

    execute_rows = [r for r in rows_after if r["kind"] == "execute"]
    metadata_execs = [
        r for r in execute_rows
        if r["payload"].get("tool") == "emit_agent_metadata_updated"
    ]
    assert len(metadata_execs) == 1
    args = metadata_execs[0]["payload"]["args"]
    assert args["display_name"] == "Compliance DS Agent"
    assert args["description"] == "Now also covers SOX controls."


async def test_update_both_fields_none_rejected(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """No-op payload (both fields None) → 422; no writes."""
    company_id = _company_id()
    agent_id, admin_id = await _register_agent(memory_ledger)

    rows_before = await memory_ledger.fetch(company_id)
    baseline = len(rows_before)

    resp = await client.patch(
        f"/api/v1/write_actions/agents_metadata/{agent_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "updated_by": str(admin_id),
        },
    )
    assert resp.status == 422

    rows_after = await memory_ledger.fetch(company_id)
    assert len(rows_after) == baseline  # no writes


async def test_update_empty_display_name_rejected(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """display_name explicitly empty → 422 (can't clear; pass None instead)."""
    company_id = _company_id()
    agent_id, admin_id = await _register_agent(memory_ledger)

    resp = await client.patch(
        f"/api/v1/write_actions/agents_metadata/{agent_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "display_name": "   ",  # whitespace-only
            "updated_by": str(admin_id),
        },
    )
    assert resp.status == 422


async def test_update_company_id_mismatch_rejected(
    client: TestClient,
) -> None:
    """Body company_id ≠ header tenant → 400."""
    other_company = uuid4()
    resp = await client.patch(
        f"/api/v1/write_actions/agents_metadata/{uuid4()}",
        headers=_auth_headers(),
        json={
            "company_id": str(other_company),
            "display_name": "Whatever",
            "updated_by": str(uuid4()),
        },
    )
    assert resp.status == 400


async def test_update_requires_bearer_token(
    client: TestClient,
) -> None:
    """Missing bearer → 401."""
    resp = await client.patch(
        f"/api/v1/write_actions/agents_metadata/{uuid4()}",
        headers={"X-Tenant-Slug": TENANT_SLUG},
        json={
            "company_id": str(_company_id()),
            "display_name": "Whatever",
            "updated_by": str(uuid4()),
        },
    )
    assert resp.status == 401
