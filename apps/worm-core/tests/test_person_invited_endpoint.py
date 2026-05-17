"""POST /api/v1/write_actions/person_invited — Onboarding Sub-wave C.

Backs the Tier 2 co-admin invite form. Emits a ``person_invited``
PEVR cycle.

Coverage:
- Happy path (email-only invite) → 200 + entry lands.
- Happy path (platform_id-only invite) → 200.
- Both invitee fields absent → 400.
- Invalid role_intent → 422.
- Missing bearer → 401.
- company_id mismatch → 400.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from wormbase_core.http_api import build_app
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger

API_TOKEN = "test-token-person-invited"
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


def _find_person_invited_entry(rows: list[dict]) -> dict | None:
    for r in rows:
        if r.get("kind") != "execute":
            continue
        if r.get("payload", {}).get("tool") == "emit_person_invited":
            return r["payload"]["args"]
    return None


async def test_email_only_invite_succeeds(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Email-only invite → 200 + person_invited entry lands."""
    company_id = _company_id()
    inviter = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/person_invited",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "invited_by_person_id": str(inviter),
            "invitee_email": "alice@example.com",
            "role_intent": "admin",
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["invited"] is True
    assert body["invitee_email"] == "alice@example.com"
    assert body["role_intent"] == "admin"

    rows = await memory_ledger.fetch(company_id)
    args = _find_person_invited_entry(rows)
    assert args is not None
    assert args["invitee_email"] == "alice@example.com"
    assert args["role_intent"] == "admin"


async def test_platform_id_only_invite_succeeds(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Platform-id-only invite → 200."""
    company_id = _company_id()
    inviter = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/person_invited",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "invited_by_person_id": str(inviter),
            "invitee_platform_id": "slack:U01ABC",
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["invitee_platform_id"] == "slack:U01ABC"
    assert body["role_intent"] == "member"  # default


async def test_both_invitee_fields_absent_returns_400(
    client: TestClient,
) -> None:
    """Both invitee_email + invitee_platform_id absent → 400."""
    company_id = _company_id()
    inviter = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/person_invited",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "invited_by_person_id": str(inviter),
        },
    )
    assert resp.status == 400


async def test_invalid_role_intent_returns_422(
    client: TestClient,
) -> None:
    """role_intent not in {admin, member, observer} → 422."""
    company_id = _company_id()
    inviter = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/person_invited",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "invited_by_person_id": str(inviter),
            "invitee_email": "x@example.com",
            "role_intent": "superuser",
        },
    )
    assert resp.status == 422


async def test_missing_bearer_returns_401(
    client: TestClient,
) -> None:
    """Missing bearer → 401."""
    company_id = _company_id()
    inviter = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/person_invited",
        headers={"X-Tenant-Slug": TENANT_SLUG},
        json={
            "company_id": str(company_id),
            "invited_by_person_id": str(inviter),
            "invitee_email": "x@example.com",
        },
    )
    assert resp.status == 401


async def test_company_id_mismatch_returns_400(
    client: TestClient,
) -> None:
    """Body company_id ≠ header tenant → 400."""
    inviter = uuid4()
    other_company = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/person_invited",
        headers=_auth_headers(),
        json={
            "company_id": str(other_company),
            "invited_by_person_id": str(inviter),
            "invitee_email": "x@example.com",
        },
    )
    assert resp.status == 400
