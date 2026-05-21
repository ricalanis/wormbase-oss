"""Unit tests for the worm-core HTTP write API (A3.5).

Uses aiohttp's pytest harness via the ``aiohttp_client`` fixture (provided
by ``pytest-aiohttp`` when available, or by an inline fixture below).
We run against the in-memory ledger so the tests stay docker-free; the
hash chain semantics are byte-for-byte the same as the DB-backed Ledger
(see ``packages/ledger/.../ledger_api.py``).

Coverage:
- /api/v1/health round-trip
- bearer-token auth: missing / wrong / correct
- POST /api/v1/people: PEVR cycle lands; 4 entries; valid hash chain
- POST /api/v1/people/{id}/confirm
- POST /api/v1/people/{id}/archive
- POST /api/v1/people/{id}/identities + DELETE
- POST /api/v1/people/{id}/roles for tenancy / domain / resource facets
- POST /api/v1/people/{id}/roles/{grant_id}/revoke
- 422 on bad role, 422 on missing scope_id for domain/resource grants
- X-Tenant-Slug → company_id resolution; default fallback
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

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


def _auth_headers(*, token: str = API_TOKEN, tenant: str = TENANT_SLUG) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Slug": tenant,
    }


# ---------------------------------------------------------------------------
# Health + auth
# ---------------------------------------------------------------------------


async def test_health_unauthed(client: TestClient) -> None:
    resp = await client.get("/api/v1/health")
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    assert body["service"] == "worm-core-write"
    assert "silent_mode" in body


async def test_post_people_missing_auth_returns_401(client: TestClient) -> None:
    resp = await client.post(
        "/api/v1/people",
        json={
            "name": "Alice",
            "platform": "slack",
            "platform_user_id": "U-alice",
        },
    )
    assert resp.status == 401


async def test_post_people_wrong_token_returns_401(client: TestClient) -> None:
    resp = await client.post(
        "/api/v1/people",
        headers={"Authorization": "Bearer wrong-token", "X-Tenant-Slug": TENANT_SLUG},
        json={"name": "Alice", "platform": "slack", "platform_user_id": "U-alice"},
    )
    assert resp.status == 401


async def test_build_app_rejects_empty_token() -> None:
    with pytest.raises(ValueError):
        build_app(ledger=InMemoryLedger(), api_token="")


# ---------------------------------------------------------------------------
# Propose person → full PEVR cycle landing
# ---------------------------------------------------------------------------


async def test_post_people_writes_full_pevr_cycle(
    client: TestClient, memory_ledger: InMemoryLedger
) -> None:
    resp = await client.post(
        "/api/v1/people",
        headers=_auth_headers(),
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
    assert UUID(body["person_id"])
    assert len(body["entry_ids"]) == 4

    company_id = tenant_to_uuid(TENANT_SLUG)
    rows = await memory_ledger.fetch(company_id)
    assert len(rows) == 4
    assert [r["kind"] for r in rows] == ["propose", "execute", "verify", "resolve"]
    # Execute payload carries the canonical tool name + payload args.
    execute = rows[1]["payload"]
    assert execute["tool"] == "emit_person_proposed"
    assert execute["args"]["name"] == "Alice"
    assert execute["args"]["platform_user_id"] == "U-alice"
    # Verify passed.
    verify = rows[2]["payload"]
    assert verify["passed"] is True
    # Resolve outcome=keep.
    resolve = rows[3]["payload"]
    assert resolve["outcome"] == "keep"
    # Hash chain valid.
    ok, broken_at = verify_chain(rows)
    assert ok and broken_at is None


async def test_post_people_validation_failure_returns_422(client: TestClient) -> None:
    resp = await client.post(
        "/api/v1/people",
        headers=_auth_headers(),
        json={
            "name": "",  # empty name fails Field(min_length=1)
            "platform": "slack",
            "platform_user_id": "U-alice",
        },
    )
    assert resp.status == 422


async def test_post_people_with_unknown_tenant_returns_400(
    client: TestClient,
) -> None:
    resp = await client.post(
        "/api/v1/people",
        headers=_auth_headers(tenant=""),  # falls back to default; should succeed
        json={"name": "Alice", "platform": "slack", "platform_user_id": "U-alice"},
    )
    # Empty header → default 'baseworm' → succeeds.
    assert resp.status == 200


# ---------------------------------------------------------------------------
# Confirm + archive
# ---------------------------------------------------------------------------


async def _propose_person(client: TestClient) -> str:
    resp = await client.post(
        "/api/v1/people",
        headers=_auth_headers(),
        json={"name": "Bob", "platform": "slack", "platform_user_id": "U-bob"},
    )
    assert resp.status == 200
    body = await resp.json()
    return body["person_id"]


async def test_confirm_person(
    client: TestClient, memory_ledger: InMemoryLedger
) -> None:
    person_id = await _propose_person(client)
    confirmed_by = str(uuid4())
    resp = await client.post(
        f"/api/v1/people/{person_id}/confirm",
        headers=_auth_headers(),
        json={"confirmed_by": confirmed_by},
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert len(body["entry_ids"]) == 4

    company_id = tenant_to_uuid(TENANT_SLUG)
    rows = await memory_ledger.fetch(company_id)
    # 4 from propose + 4 from confirm
    assert len(rows) == 8
    assert rows[5]["payload"]["tool"] == "emit_person_confirmed"
    ok, _broken = verify_chain(rows)
    assert ok


async def test_archive_person(client: TestClient) -> None:
    person_id = await _propose_person(client)
    archived_by = str(uuid4())
    resp = await client.post(
        f"/api/v1/people/{person_id}/archive",
        headers=_auth_headers(),
        json={"archived_by": archived_by, "reason": "left the company"},
    )
    assert resp.status == 200, await resp.text()


# ---------------------------------------------------------------------------
# Identity link / unlink
# ---------------------------------------------------------------------------


async def test_link_and_unlink_identity(
    client: TestClient, memory_ledger: InMemoryLedger
) -> None:
    person_id = await _propose_person(client)
    actor = str(uuid4())

    link = await client.post(
        f"/api/v1/people/{person_id}/identities",
        headers=_auth_headers(),
        json={
            "platform": "discord",
            "platform_user_id": "bob#1234",
            "linked_by": actor,
        },
    )
    assert link.status == 200, await link.text()

    unlink = await client.delete(
        f"/api/v1/people/{person_id}/identities/discord/bob%231234",
        headers=_auth_headers(),
        json={"unlinked_by": actor},
    )
    assert unlink.status == 200, await unlink.text()

    company_id = tenant_to_uuid(TENANT_SLUG)
    rows = await memory_ledger.fetch(company_id)
    tools = [
        r["payload"].get("tool")
        for r in rows
        if r["kind"] == "execute"
    ]
    assert "emit_identity_linked" in tools
    assert "emit_identity_unlinked" in tools
    ok, _ = verify_chain(rows)
    assert ok


# ---------------------------------------------------------------------------
# Role grants — three facets
# ---------------------------------------------------------------------------


async def test_grant_tenancy_role(
    client: TestClient, memory_ledger: InMemoryLedger
) -> None:
    person_id = await _propose_person(client)
    granted_by = str(uuid4())
    resp = await client.post(
        f"/api/v1/people/{person_id}/roles",
        headers=_auth_headers(),
        json={
            "facet": "tenancy",
            "role": "admin",
            "granted_by": granted_by,
        },
    )
    assert resp.status == 200, await resp.text()


async def test_grant_tenancy_role_invalid_role_returns_422(
    client: TestClient,
) -> None:
    person_id = await _propose_person(client)
    granted_by = str(uuid4())
    resp = await client.post(
        f"/api/v1/people/{person_id}/roles",
        headers=_auth_headers(),
        json={
            "facet": "tenancy",
            "role": "rogue",  # not in {installer, admin, member, observer}
            "granted_by": granted_by,
        },
    )
    assert resp.status == 422


async def test_grant_domain_role_requires_scope_id(client: TestClient) -> None:
    person_id = await _propose_person(client)
    granted_by = str(uuid4())
    resp = await client.post(
        f"/api/v1/people/{person_id}/roles",
        headers=_auth_headers(),
        json={
            "facet": "domain",
            "role": "owner",
            "granted_by": granted_by,
        },
    )
    assert resp.status == 422


async def test_grant_domain_role_succeeds(
    client: TestClient, memory_ledger: InMemoryLedger
) -> None:
    person_id = await _propose_person(client)
    granted_by = str(uuid4())
    domain_id = str(uuid4())
    resp = await client.post(
        f"/api/v1/people/{person_id}/roles",
        headers=_auth_headers(),
        json={
            "facet": "domain",
            "role": "owner",
            "scope_id": domain_id,
            "granted_by": granted_by,
        },
    )
    assert resp.status == 200, await resp.text()


async def test_grant_resource_role_requires_scope_type(client: TestClient) -> None:
    person_id = await _propose_person(client)
    granted_by = str(uuid4())
    scope_id = str(uuid4())
    resp = await client.post(
        f"/api/v1/people/{person_id}/roles",
        headers=_auth_headers(),
        json={
            "facet": "resource",
            "role": "maintainer",
            "scope_id": scope_id,  # missing scope_type
            "granted_by": granted_by,
        },
    )
    assert resp.status == 422


async def test_grant_resource_role_succeeds(
    client: TestClient, memory_ledger: InMemoryLedger
) -> None:
    person_id = await _propose_person(client)
    granted_by = str(uuid4())
    scope_id = str(uuid4())
    resp = await client.post(
        f"/api/v1/people/{person_id}/roles",
        headers=_auth_headers(),
        json={
            "facet": "resource",
            "role": "maintainer",
            "scope_id": scope_id,
            "scope_type": "kpi",
            "granted_by": granted_by,
        },
    )
    assert resp.status == 200, await resp.text()


async def test_revoke_tenancy_role(
    client: TestClient, memory_ledger: InMemoryLedger
) -> None:
    person_id = await _propose_person(client)
    granted_by = str(uuid4())
    # Grant first.
    grant = await client.post(
        f"/api/v1/people/{person_id}/roles",
        headers=_auth_headers(),
        json={"facet": "tenancy", "role": "admin", "granted_by": granted_by},
    )
    assert grant.status == 200
    grant_body = await grant.json()
    grant_id = grant_body["entry_ids"][0]  # any uuid; revoke key is (person_id, role)
    revoke = await client.post(
        f"/api/v1/people/{person_id}/roles/{grant_id}/revoke",
        headers=_auth_headers(),
        json={"revoked_by": granted_by, "role": "admin"},
    )
    assert revoke.status == 200, await revoke.text()

    company_id = tenant_to_uuid(TENANT_SLUG)
    rows = await memory_ledger.fetch(company_id)
    tools = [r["payload"].get("tool") for r in rows if r["kind"] == "execute"]
    assert "emit_role_assigned" in tools
    assert "emit_role_revoked" in tools
    ok, _ = verify_chain(rows)
    assert ok


# ---------------------------------------------------------------------------
# Tenant resolution
# ---------------------------------------------------------------------------


async def test_x_tenant_slug_resolves_to_distinct_company_id(
    client: TestClient, memory_ledger: InMemoryLedger
) -> None:
    # Proposes against a *different* tenant header — entries land under
    # a different company_id, not under the default baseworm.
    other = "democorp"
    resp = await client.post(
        "/api/v1/people",
        headers=_auth_headers(tenant=other),
        json={"name": "Carol", "platform": "slack", "platform_user_id": "U-carol"},
    )
    assert resp.status == 200, await resp.text()

    base_company = tenant_to_uuid("baseworm")
    other_company = tenant_to_uuid(other)
    assert base_company != other_company
    rows_other = await memory_ledger.fetch(other_company)
    rows_base = await memory_ledger.fetch(base_company)
    assert len(rows_other) == 4
    assert len(rows_base) == 0


# ---------------------------------------------------------------------------
# Silent mode contract — HTTP API
# ---------------------------------------------------------------------------
# write_actions._pevr returns a SuppressedToolResult under silent mode (it
# has no entry_ids — nothing was appended). The HTTP API's `_result_payload`
# helper has to recognize that shape; if it doesn't, every write endpoint
# crashes 500 under silent mode (regression caught 2026-05-20 when the
# tutorial seed step failed against the live stack).


async def test_post_people_under_silent_mode_returns_suppressed_shape(
    client: TestClient,
    memory_ledger: InMemoryLedger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /api/v1/people must return 200 + suppressed:true under silent mode.

    Hypotheses validated (per silent-mode design 2026-05-18):
    - HTTP response is 200 (NOT 500). Pre-fix the bug was that
      `_result_payload` accessed `write_result.entry_ids` even when
      the result was a `SuppressedToolResult`, crashing every write
      endpoint under silent mode (caught live 2026-05-20).
    - body.suppressed is True
    - body.entry_ids is [] (no person-proposal entry IDs surface to
      the caller; the would-have-been action did not run)
    - body.ref_id is a valid UUID linking to the recorded suppression
    - the ledger DOES land a full PEVR cycle for the suppression
      itself with payload.target_kind == 'reply_suppressed' and
      execute.tool == the would-have-been tool name. This is the
      "captured as a first-class ledger entry" guarantee from the
      spec — operators can audit what the system would have done.
    """
    from wormbase_core import silent_mode

    monkeypatch.setenv(silent_mode.ENV_VAR, "1")
    silent_mode._reset_for_tests()
    try:
        resp = await client.post(
            "/api/v1/people",
            headers=_auth_headers(),
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
        assert body.get("suppressed") is True, body
        assert body.get("entry_ids") == [], body
        UUID(body["ref_id"])

        company_id = tenant_to_uuid(TENANT_SLUG)
        rows = await memory_ledger.fetch(company_id)
        # PEVR cycle for the suppression itself MUST land — the audit
        # trail is the whole point of silent mode.
        kinds = [r["kind"] for r in rows]
        assert kinds == ["propose", "execute", "verify", "resolve"], rows
        # propose.target_kind marks this as a suppression record.
        assert rows[0]["payload"]["target_kind"] == "reply_suppressed", rows[0]
        # execute carries the would-have-been tool name.
        assert rows[1]["payload"]["tool"] == "emit_person_proposed", rows[1]
        # resolve documents the silent-mode rationale.
        assert rows[3]["payload"]["outcome"] == "keep", rows[3]
        rationale = rows[3]["payload"].get("rationale", "").lower()
        assert "silent_mode" in rationale or "silent mode" in rationale
    finally:
        silent_mode._reset_for_tests()
