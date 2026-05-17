"""L4 Sub-wave C — HTTP-endpoint tests for schema_impacts_confirm/reject.

Exercises the bearer-authed POST endpoints against the in-memory
ledger via aiohttp's TestClient harness — same pattern as
``test_lineage_edge_endpoints.py`` and ``test_quality_check_endpoints.py``.

The handlers follow the v2.A + L3 + L7 pattern:

  * Bearer token at the HTTP layer (401 on miss).
  * X-Tenant-Slug resolves to company_id; body ``company_id`` must
    agree (400 on mismatch).
  * ``impact_id`` must point at a prior ``schema_impact_proposed``
    entry for the tenant (404 on unknown).
  * ``reason`` is a strict 5-value enum on the reject path (400 on
    unknown).
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

API_TOKEN = "test-token-schema-impact"
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


async def _seed_proposed_impact(
    memory_ledger: InMemoryLedger,
    *,
    impact_id: str,
    company_id: UUID | None = None,
) -> None:
    """Seed a ``schema_impact_proposed`` execute entry for the tenant.

    The handlers walk the ledger for this exact tool to surface 404
    on unknown impacts; seeding a propose-cycle is the canonical
    setup.
    """
    cid = company_id if company_id is not None else tenant_to_uuid(TENANT_SLUG)
    args: dict[str, Any] = {
        "impact_id": impact_id,
        "source_id": "stripe_src",
        "src_table": "stripe_src.public.customers",
        "src_column": "customer_id",
        "change_kind": "column_dropped",
        "impact_kind": "tgt_column_orphaned",
        "tgt_table_id": "warehouse.dim_customer",
        "tgt_column": "customer_id",
        "upstream_lineage_edge_id": "edge-1",
        "confidence": 0.88,
        "strategy": "lineage_edge",
        "reasoning": "test",
        "evidence": {},
    }
    await memory_ledger.write(
        company_id=cid,
        propose={
            "target_kind": "schema_impact_proposed",
            "ref_id": impact_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_schema_impact_proposed",
            "args": args,
            "result_ref": impact_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


async def test_confirm_missing_auth_returns_401(client: TestClient) -> None:
    """No bearer → 401 from the HTTP layer (matches v2.A + L3 + L7 pattern)."""
    resp = await client.post(
        "/api/v1/write_actions/schema_impacts_confirm/impact-1",
        json={"company_id": str(uuid4()), "confirmed_by": str(uuid4())},
    )
    assert resp.status == 401


async def test_reject_missing_auth_returns_401(client: TestClient) -> None:
    """No bearer → 401 from the HTTP layer."""
    resp = await client.post(
        "/api/v1/write_actions/schema_impacts_reject/impact-1",
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
    """Successful confirm emits a ``schema_impact_confirmed`` execute entry."""
    impact_id = "impact-confirm-1"
    await _seed_proposed_impact(memory_ledger, impact_id=impact_id)
    company_id = tenant_to_uuid(TENANT_SLUG)
    admin = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/schema_impacts_confirm/{impact_id}",
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
    assert body["impact_id"] == impact_id
    assert body["impactId"] == impact_id

    entries = await memory_ledger.fetch(company_id)
    tools = [
        (e.get("payload") or {}).get("tool")
        for e in entries
        if e.get("kind") == "execute"
    ]
    assert "emit_schema_impact_confirmed" in tools


async def test_reject_writes_ledger_entry(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Successful reject emits a ``schema_impact_rejected`` execute entry."""
    impact_id = "impact-reject-1"
    await _seed_proposed_impact(memory_ledger, impact_id=impact_id)
    company_id = tenant_to_uuid(TENANT_SLUG)
    admin = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/schema_impacts_reject/{impact_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(admin),
            "reason": "already_handled",
            "notes": "downstream already migrated",
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["rejected"] is True
    assert body["impact_id"] == impact_id
    assert body["reason"] == "already_handled"

    entries = await memory_ledger.fetch(company_id)
    tools = [
        (e.get("payload") or {}).get("tool")
        for e in entries
        if e.get("kind") == "execute"
    ]
    assert "emit_schema_impact_rejected" in tools


async def test_confirm_404_on_unknown_impact_id(client: TestClient) -> None:
    """Impact not in the projection → 404 from the confirm handler."""
    company_id = tenant_to_uuid(TENANT_SLUG)
    resp = await client.post(
        "/api/v1/write_actions/schema_impacts_confirm/unknown-impact",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "confirmed_by": str(uuid4()),
        },
    )
    assert resp.status == 404, await resp.text()


async def test_reject_404_on_unknown_impact_id(client: TestClient) -> None:
    """Impact not in the projection → 404 from the reject handler."""
    company_id = tenant_to_uuid(TENANT_SLUG)
    resp = await client.post(
        "/api/v1/write_actions/schema_impacts_reject/unknown-impact",
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
    """Invalid reject ``reason`` → 400 from the reject handler."""
    impact_id = "impact-reject-bad-reason"
    await _seed_proposed_impact(memory_ledger, impact_id=impact_id)
    company_id = tenant_to_uuid(TENANT_SLUG)

    resp = await client.post(
        f"/api/v1/write_actions/schema_impacts_reject/{impact_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(uuid4()),
            "reason": "fabricated_reason",
        },
    )
    assert resp.status == 400, await resp.text()


async def test_confirm_company_id_mismatch_400(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Body ``company_id`` must match the X-Tenant-Slug header (400)."""
    impact_id = "impact-mismatch"
    await _seed_proposed_impact(memory_ledger, impact_id=impact_id)
    wrong_company = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/schema_impacts_confirm/{impact_id}",
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
    """The 5 canonical reject reasons all 200 OK."""
    canonical = [
        "false_positive",
        "already_handled",
        "low_value",
        "out_of_scope",
        "other",
    ]
    company_id = tenant_to_uuid(TENANT_SLUG)
    for idx, reason in enumerate(canonical):
        impact_id = f"impact-reason-{idx}"
        await _seed_proposed_impact(memory_ledger, impact_id=impact_id)
        resp = await client.post(
            f"/api/v1/write_actions/schema_impacts_reject/{impact_id}",
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
