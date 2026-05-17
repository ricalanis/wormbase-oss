"""L5 Sub-wave C — HTTP-endpoint tests for semantic_types_confirm/reject.

Exercises the bearer-authed POST endpoints against the in-memory
ledger via aiohttp's TestClient harness — same pattern as
``test_lineage_edge_endpoints.py``,
``test_quality_check_endpoints.py``, and
``test_schema_impact_endpoints.py``.

The handlers follow the v2.A + L3 + L7 + L4 pattern:

  * Bearer token at the HTTP layer (401 on miss).
  * X-Tenant-Slug resolves to company_id; body ``company_id`` must
    agree (400 on mismatch).
  * ``type_id`` must point at a prior ``semantic_type_proposed``
    entry for the tenant (404 on unknown).
  * ``reason`` is a strict 5-value enum on the reject path (400 on
    unknown). The L5-specific 5th value is ``wrong_type``.
  * Admin role enforcement lives at the dashboard server action layer
    (defense in depth) — the HTTP layer is bearer + tenant only.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core.http_api import build_app
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger

API_TOKEN = "test-token-semantic-type"
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


async def _seed_proposed_type(
    memory_ledger: InMemoryLedger,
    *,
    type_id: str,
    company_id: UUID | None = None,
) -> None:
    """Seed a ``semantic_type_proposed`` execute entry for the tenant.

    The handlers walk the ledger for this exact tool to surface 404
    on unknown semantic-types; seeding a propose-cycle is the
    canonical setup.
    """
    cid = company_id if company_id is not None else tenant_to_uuid(TENANT_SLUG)
    args: dict[str, Any] = {
        "type_id": type_id,
        "table_id": "warehouse.dim_customer",
        "column": "email",
        "semantic_type": "email",
        "confidence": 0.9,
        "strategy": "column_name",
        "reasoning": "test seed",
        "evidence": {"regex": ".*"},
    }
    await memory_ledger.write(
        company_id=cid,
        propose={
            "target_kind": "semantic_type_proposed",
            "ref_id": type_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_semantic_type_proposed",
            "args": args,
            "result_ref": type_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


async def test_confirm_missing_auth_returns_401(client: TestClient) -> None:
    """No bearer → 401 from the HTTP layer (matches v2.A + L3 + L7 + L4 pattern)."""
    resp = await client.post(
        "/api/v1/write_actions/semantic_types_confirm/type-1",
        json={"company_id": str(uuid4()), "confirmed_by": str(uuid4())},
    )
    assert resp.status == 401


async def test_reject_missing_auth_returns_401(client: TestClient) -> None:
    """No bearer → 401 from the HTTP layer."""
    resp = await client.post(
        "/api/v1/write_actions/semantic_types_reject/type-1",
        json={
            "company_id": str(uuid4()),
            "rejected_by": str(uuid4()),
            "reason": "false_positive",
        },
    )
    assert resp.status == 401


async def test_confirm_writes_ledger_entry(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Successful confirm emits a ``semantic_type_confirmed`` execute entry."""
    type_id = "type-confirm-1"
    await _seed_proposed_type(memory_ledger, type_id=type_id)
    company_id = tenant_to_uuid(TENANT_SLUG)
    admin = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/semantic_types_confirm/{type_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "confirmed_by": str(admin),
            "notes": "approved",
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["confirmed"] is True
    assert body["type_id"] == type_id
    assert body["typeId"] == type_id

    entries = await memory_ledger.fetch(company_id)
    tools = [
        (e.get("payload") or {}).get("tool")
        for e in entries
        if e.get("kind") == "execute"
    ]
    assert "emit_semantic_type_confirmed" in tools


async def test_reject_writes_ledger_entry(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Successful reject emits a ``semantic_type_rejected`` execute entry."""
    type_id = "type-reject-1"
    await _seed_proposed_type(memory_ledger, type_id=type_id)
    company_id = tenant_to_uuid(TENANT_SLUG)
    admin = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/semantic_types_reject/{type_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(admin),
            "reason": "wrong_type",
            "notes": "actually phone_e164 not email",
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["rejected"] is True
    assert body["type_id"] == type_id
    assert body["reason"] == "wrong_type"

    entries = await memory_ledger.fetch(company_id)
    tools = [
        (e.get("payload") or {}).get("tool")
        for e in entries
        if e.get("kind") == "execute"
    ]
    assert "emit_semantic_type_rejected" in tools


async def test_confirm_404_on_unknown_type_id(client: TestClient) -> None:
    """Type not in the projection → 404 from the confirm handler."""
    company_id = tenant_to_uuid(TENANT_SLUG)
    resp = await client.post(
        "/api/v1/write_actions/semantic_types_confirm/unknown-type",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "confirmed_by": str(uuid4()),
        },
    )
    assert resp.status == 404, await resp.text()


async def test_reject_404_on_unknown_type_id(client: TestClient) -> None:
    """Type not in the projection → 404 from the reject handler."""
    company_id = tenant_to_uuid(TENANT_SLUG)
    resp = await client.post(
        "/api/v1/write_actions/semantic_types_reject/unknown-type",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(uuid4()),
            "reason": "false_positive",
        },
    )
    assert resp.status == 404, await resp.text()


async def test_reject_400_on_invalid_reason(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Invalid reject ``reason`` → 400 from the reject handler.

    L4's ``already_handled`` is NOT a valid L5 reason — verifies
    L5-specific 5-value enum is enforced.
    """
    type_id = "type-reject-bad-reason"
    await _seed_proposed_type(memory_ledger, type_id=type_id)
    company_id = tenant_to_uuid(TENANT_SLUG)

    resp = await client.post(
        f"/api/v1/write_actions/semantic_types_reject/{type_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(uuid4()),
            "reason": "already_handled",  # L4 reason, not L5
        },
    )
    assert resp.status == 400, await resp.text()


async def test_confirm_company_id_mismatch_400(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Body ``company_id`` must match the X-Tenant-Slug header (400)."""
    type_id = "type-mismatch"
    await _seed_proposed_type(memory_ledger, type_id=type_id)
    wrong_company = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/semantic_types_confirm/{type_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(wrong_company),
            "confirmed_by": str(uuid4()),
        },
    )
    assert resp.status == 400, await resp.text()


async def test_reject_accepts_all_5_canonical_reasons(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """The 5 canonical L5 reject reasons all 200 OK."""
    canonical = [
        "false_positive",
        "low_value",
        "wrong_type",  # L5-specific (replaces L4's already_handled)
        "out_of_scope",
        "other",
    ]
    company_id = tenant_to_uuid(TENANT_SLUG)
    for idx, reason in enumerate(canonical):
        type_id = f"type-reason-{idx}"
        await _seed_proposed_type(memory_ledger, type_id=type_id)
        resp = await client.post(
            f"/api/v1/write_actions/semantic_types_reject/{type_id}",
            headers=_auth_headers(),
            json={
                "company_id": str(company_id),
                "rejected_by": str(uuid4()),
                "reason": reason,
            },
        )
        assert resp.status == 200, (
            f"reason={reason!r} → status={resp.status} text={await resp.text()}"
        )
