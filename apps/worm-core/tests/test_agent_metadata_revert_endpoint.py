"""POST /api/v1/write_actions/agents_metadata_revert/{agent_id} —
post-rest path #4 (2026-05-13).

Backs the agent detail page's Revert button. Reverts the most-recent
``agent_metadata_updated`` by emitting a new compensating
``agent_metadata_updated`` PEVR cycle (forward-only doctrine). No new
ledger kind, no mutation of prior entries.

Coverage:
- Revert with 0 prior updates → 400 (helpful message).
- Revert with 1 update → reverts to ``agent_registered`` baseline (both
  display_name AND description revert; description clears to "").
- Revert with 2+ updates → reverts to the second-most-recent state.
- Revert preserves agent_id (no revoke; agent stays addressable).
- Revert emits a new ledger entry (forward-only; not a mutation).
- Revert reason carries the auto "revert from seq {N}" prefix.
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

API_TOKEN = "test-token-agent-metadata-revert"
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
        display_name="Original Name",
        registered_by=admin_id,
    )
    return str(agent_uuid), admin_id


def _latest_metadata_args(
    rows: list[dict],
    agent_id: str,
) -> dict | None:
    """Return the args of the most-recent agent_metadata_updated execute."""
    for entry in reversed(rows):
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        if payload.get("tool") != "emit_agent_metadata_updated":
            continue
        args = payload.get("args") or {}
        if str(args.get("agent_id") or "") == agent_id:
            return args
    return None


async def test_revert_with_no_prior_update_returns_400(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """An agent with zero prior agent_metadata_updated entries → 400."""
    company_id = _company_id()
    agent_id, admin_id = await _register_agent(memory_ledger)

    rows_before = await memory_ledger.fetch(company_id)
    baseline = len(rows_before)

    resp = await client.post(
        f"/api/v1/write_actions/agents_metadata_revert/{agent_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "updated_by": str(admin_id),
        },
    )
    assert resp.status == 400
    body_text = await resp.text()
    assert (
        "no prior" in body_text.lower()
        or "nothing to revert" in body_text.lower()
    )

    rows_after = await memory_ledger.fetch(company_id)
    assert len(rows_after) == baseline  # no writes


async def test_revert_with_one_update_restores_registration_baseline(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """One prior update → revert to agent_registered baseline.

    Both display_name AND description should revert: display_name back to
    the registration value, description cleared to "" (since registration
    didn't set one).
    """
    company_id = _company_id()
    agent_id, admin_id = await _register_agent(memory_ledger)

    # Apply one metadata update — both fields touched.
    await write_actions.update_agent_metadata(
        memory_ledger,
        company_id,
        agent_id=agent_id,
        updated_by_person_id=admin_id,
        display_name="Updated Name",
        description="Now covers compliance.",
    )

    resp = await client.post(
        f"/api/v1/write_actions/agents_metadata_revert/{agent_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "updated_by": str(admin_id),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["reverted"] is True
    assert body["agent_id"] == agent_id

    rows = await memory_ledger.fetch(company_id)
    latest = _latest_metadata_args(rows, agent_id)
    assert latest is not None
    # Revert restores registration display_name. Description clears to
    # "" since registration didn't set one (None ≠ unchanged in revert).
    assert latest["display_name"] == "Original Name"
    assert latest["description"] == ""


async def test_revert_with_two_updates_restores_second_most_recent(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Two prior updates → revert to the second-most-recent's state."""
    company_id = _company_id()
    agent_id, admin_id = await _register_agent(memory_ledger)

    # Update #1: rename + set description.
    await write_actions.update_agent_metadata(
        memory_ledger,
        company_id,
        agent_id=agent_id,
        updated_by_person_id=admin_id,
        display_name="Mid State Name",
        description="Mid state description.",
    )
    # Update #2: rename again, leave description alone (None = unchanged).
    await write_actions.update_agent_metadata(
        memory_ledger,
        company_id,
        agent_id=agent_id,
        updated_by_person_id=admin_id,
        display_name="Head State Name",
        description=None,
    )

    resp = await client.post(
        f"/api/v1/write_actions/agents_metadata_revert/{agent_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "updated_by": str(admin_id),
        },
    )
    assert resp.status == 200, await resp.text()

    rows = await memory_ledger.fetch(company_id)
    latest = _latest_metadata_args(rows, agent_id)
    assert latest is not None
    # Revert resolves the pre-head fold: display_name from update #1
    # ("Mid State Name"), description from update #1 ("Mid state
    # description.") since update #2 left it None (unchanged).
    assert latest["display_name"] == "Mid State Name"
    assert latest["description"] == "Mid state description."


async def test_revert_emits_new_forward_only_entry(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Revert emits ONE NEW PEVR cycle; preserves agent_id; no mutation.

    Pins the forward-only doctrine: the head entry's row is untouched,
    a new row is appended, and the agent_id stays addressable.
    """
    company_id = _company_id()
    agent_id, admin_id = await _register_agent(memory_ledger)

    # One prior update to set up the revert.
    await write_actions.update_agent_metadata(
        memory_ledger,
        company_id,
        agent_id=agent_id,
        updated_by_person_id=admin_id,
        display_name="Will Be Reverted",
    )

    rows_before = await memory_ledger.fetch(company_id)
    baseline = len(rows_before)
    # Snapshot the metadata-updated executes — these should be untouched.
    pre_meta_executes = [
        r for r in rows_before
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool")
        == "emit_agent_metadata_updated"
    ]
    pre_meta_seqs = {r["seq"] for r in pre_meta_executes}

    resp = await client.post(
        f"/api/v1/write_actions/agents_metadata_revert/{agent_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "updated_by": str(admin_id),
        },
    )
    assert resp.status == 200, await resp.text()

    rows_after = await memory_ledger.fetch(company_id)
    # One new PEVR cycle = 4 rows.
    assert len(rows_after) == baseline + 4
    # All prior metadata-updated entries still present, unchanged.
    post_meta_executes = [
        r for r in rows_after
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool")
        == "emit_agent_metadata_updated"
    ]
    post_meta_seqs = {r["seq"] for r in post_meta_executes}
    assert pre_meta_seqs.issubset(post_meta_seqs)
    # Exactly one new metadata-updated execute landed.
    assert len(post_meta_executes) == len(pre_meta_executes) + 1

    # Agent_id is preserved on the new entry.
    latest = _latest_metadata_args(rows_after, agent_id)
    assert latest is not None
    assert latest["agent_id"] == agent_id


async def test_revert_reason_carries_auto_prefix(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """The new entry's reason starts with "revert from seq {N}"."""
    company_id = _company_id()
    agent_id, admin_id = await _register_agent(memory_ledger)

    await write_actions.update_agent_metadata(
        memory_ledger,
        company_id,
        agent_id=agent_id,
        updated_by_person_id=admin_id,
        display_name="Renamed Once",
    )

    resp = await client.post(
        f"/api/v1/write_actions/agents_metadata_revert/{agent_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "updated_by": str(admin_id),
            "reason": "operator changed their mind",
        },
    )
    assert resp.status == 200, await resp.text()

    rows = await memory_ledger.fetch(company_id)
    latest = _latest_metadata_args(rows, agent_id)
    assert latest is not None
    reason = latest.get("reason") or ""
    assert reason.startswith("revert from seq "), reason
    # User-supplied reason appended.
    assert "operator changed their mind" in reason


async def test_revert_company_id_mismatch_rejected(
    client: TestClient,
) -> None:
    """Body company_id ≠ header tenant → 400."""
    other_company = uuid4()
    resp = await client.post(
        f"/api/v1/write_actions/agents_metadata_revert/{uuid4()}",
        headers=_auth_headers(),
        json={
            "company_id": str(other_company),
            "updated_by": str(uuid4()),
        },
    )
    assert resp.status == 400


async def test_revert_requires_bearer_token(
    client: TestClient,
) -> None:
    """Missing bearer → 401."""
    resp = await client.post(
        f"/api/v1/write_actions/agents_metadata_revert/{uuid4()}",
        headers={"X-Tenant-Slug": TENANT_SLUG},
        json={
            "company_id": str(_company_id()),
            "updated_by": str(uuid4()),
        },
    )
    assert resp.status == 401
