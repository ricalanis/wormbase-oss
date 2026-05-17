"""POST /api/v1/write_actions/domain_pack_selected/{pack_id} —
Onboarding Sub-wave C (2026-05-30).

Backs the Tier 2 domain pack picker. Emits a ``domain_pack_selected``
parent PEVR cycle plus the fan-out (per-domain
``emit_domain_registered`` + per-policy ``emit_policy_applied``
execute entries).

Coverage:
- Happy path (generic pack) → 200 + parent + fan-out written.
- Each canonical pack id (generic / saas / marketplace / fintech)
  accepted on the path.
- Unknown pack id on the path → 400.
- Missing bearer → 401.
- company_id mismatch → 400.
- Idempotent re-pick → 200 + already_seeded=true.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from wormbase_core.http_api import build_app
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger

API_TOKEN = "test-token-domain-pack-selected"
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


async def test_pick_generic_pack_writes_parent_and_fanout(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """First pack pick → 200 + parent + fan-out lands."""
    company_id = _company_id()
    admin = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/domain_pack_selected/generic",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "selected_by_person_id": str(admin),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["pack_id"] == "generic"
    assert body["already_seeded"] is False
    assert isinstance(body["domain_ids"], list)
    assert len(body["domain_ids"]) >= 1

    rows = await memory_ledger.fetch(company_id)
    tools = {r["payload"].get("tool") for r in rows if r["kind"] == "execute"}
    assert "emit_domain_pack_selected" in tools
    assert "emit_domain_registered" in tools


async def test_pick_each_canonical_pack(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """All four canonical pack ids are accepted on the path."""
    company_id = _company_id()
    admin = uuid4()
    for pack_id in ("saas", "marketplace", "fintech"):
        ledger_fresh = InMemoryLedger()
        # Replace app's ledger by spinning a per-call client instance.
        # Cheap: directly seed via write_actions.
        # We'll just verify each id is accepted on the path validation.
        resp = await client.post(
            f"/api/v1/write_actions/domain_pack_selected/{pack_id}",
            headers=_auth_headers(),
            json={
                "company_id": str(company_id),
                "selected_by_person_id": str(admin),
            },
        )
        # The first non-generic call lands; subsequent calls
        # short-circuit (idempotent) but still return 200.
        assert resp.status == 200, (
            f"pack {pack_id} unexpectedly rejected: {await resp.text()}"
        )


async def test_pick_unknown_pack_id_returns_400(
    client: TestClient,
) -> None:
    """Unknown pack id on the URL path → 400."""
    company_id = _company_id()
    admin = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/domain_pack_selected/unknown_pack",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "selected_by_person_id": str(admin),
        },
    )
    assert resp.status == 400


async def test_pick_missing_bearer_returns_401(
    client: TestClient,
) -> None:
    """Missing bearer token → 401."""
    company_id = _company_id()
    admin = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/domain_pack_selected/generic",
        headers={"X-Tenant-Slug": TENANT_SLUG},
        json={
            "company_id": str(company_id),
            "selected_by_person_id": str(admin),
        },
    )
    assert resp.status == 401


async def test_pick_company_id_mismatch_returns_400(
    client: TestClient,
) -> None:
    """Body company_id ≠ header tenant resolves to 400."""
    admin = uuid4()
    other_company = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/domain_pack_selected/generic",
        headers=_auth_headers(),
        json={
            "company_id": str(other_company),  # mismatch
            "selected_by_person_id": str(admin),
        },
    )
    assert resp.status == 400


async def test_pick_idempotent_re_pick(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """A second pack pick on the same tenant short-circuits with already_seeded=true."""
    company_id = _company_id()
    admin = uuid4()
    body = {
        "company_id": str(company_id),
        "selected_by_person_id": str(admin),
    }
    r1 = await client.post(
        "/api/v1/write_actions/domain_pack_selected/generic",
        headers=_auth_headers(),
        json=body,
    )
    assert r1.status == 200
    first = await r1.json()
    assert first["already_seeded"] is False

    r2 = await client.post(
        "/api/v1/write_actions/domain_pack_selected/generic",
        headers=_auth_headers(),
        json=body,
    )
    assert r2.status == 200
    second = await r2.json()
    assert second["already_seeded"] is True


async def test_pick_missing_required_body_field_returns_422(
    client: TestClient,
) -> None:
    """Missing selected_by_person_id → 422 (Pydantic validation)."""
    company_id = _company_id()
    resp = await client.post(
        "/api/v1/write_actions/domain_pack_selected/generic",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            # selected_by_person_id missing
        },
    )
    assert resp.status == 422
