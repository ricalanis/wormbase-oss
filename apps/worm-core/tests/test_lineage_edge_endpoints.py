"""L3 Sub-wave C — HTTP-endpoint tests for lineage_edges_confirm/reject.

Exercises the bearer-authed POST endpoints against the in-memory
ledger via aiohttp's TestClient harness — same pattern as
``test_http_api_bulk_confirm.py``.

The handlers follow the v2.A subscription-revoke pattern:

  * Bearer token at the HTTP layer (401 on miss).
  * X-Tenant-Slug resolves to company_id; body ``company_id`` must
    agree (400 on mismatch).
  * ``edge_id`` must point at a prior ``lineage_edge_proposed``
    entry for the tenant (404 on unknown).
  * ``reason`` is a strict enum on the reject path (400 on unknown).
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

API_TOKEN = "test-token-lineage"
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


async def _seed_proposed_edge(
    memory_ledger: InMemoryLedger,
    *,
    edge_id: str,
    company_id: UUID | None = None,
) -> None:
    """Seed a ``lineage_edge_proposed`` execute entry for the tenant.

    The handlers walk the ledger for this exact tool to surface 404
    on unknown edges; seeding a propose-cycle is the canonical setup.
    """
    cid = company_id if company_id is not None else tenant_to_uuid(TENANT_SLUG)
    args: dict[str, Any] = {
        "edge_id": edge_id,
        "src_table_id": "src.tbl",
        "src_column": "id",
        "tgt_table_id": "tgt.tbl",
        "tgt_column": "id",
        "confidence": 0.85,
        "strategy": "naming_heuristic",
        "reasoning": "test",
        "evidence": {},
    }
    await memory_ledger.write(
        company_id=cid,
        propose={
            "target_kind": "lineage_edge_proposed",
            "ref_id": edge_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_lineage_edge_proposed",
            "args": args,
            "result_ref": edge_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


async def test_confirm_missing_auth_returns_401(client: TestClient) -> None:
    """No bearer → 401 from the HTTP layer (matches v2.A pattern)."""
    resp = await client.post(
        "/api/v1/write_actions/lineage_edges_confirm/edge-1",
        json={"company_id": str(uuid4()), "confirmed_by": str(uuid4())},
    )
    assert resp.status == 401


async def test_reject_missing_auth_returns_401(client: TestClient) -> None:
    """No bearer → 401 from the HTTP layer."""
    resp = await client.post(
        "/api/v1/write_actions/lineage_edges_reject/edge-1",
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
    """Successful confirm emits a ``lineage_edge_confirmed`` execute entry."""
    edge_id = "edge-confirm-1"
    await _seed_proposed_edge(memory_ledger, edge_id=edge_id)
    company_id = tenant_to_uuid(TENANT_SLUG)
    admin = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/lineage_edges_confirm/{edge_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "confirmed_by": str(admin),
            "notes": "human review approved",
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["confirmed"] is True
    assert body["edge_id"] == edge_id

    # Verify the ledger has the new entry with the correct tool.
    entries = await memory_ledger.fetch(company_id)
    confirmed_tools = [
        (e.get("payload") or {}).get("tool")
        for e in entries
        if e.get("kind") == "execute"
    ]
    assert "emit_lineage_edge_confirmed" in confirmed_tools


async def test_reject_writes_ledger_entry(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Successful reject emits a ``lineage_edge_rejected`` execute entry."""
    edge_id = "edge-reject-1"
    await _seed_proposed_edge(memory_ledger, edge_id=edge_id)
    company_id = tenant_to_uuid(TENANT_SLUG)
    admin = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/lineage_edges_reject/{edge_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(admin),
            "reason": "false_positive",
            "notes": "naming-heuristic match was misleading",
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["rejected"] is True
    assert body["edge_id"] == edge_id
    assert body["reason"] == "false_positive"

    entries = await memory_ledger.fetch(company_id)
    tools = [
        (e.get("payload") or {}).get("tool")
        for e in entries
        if e.get("kind") == "execute"
    ]
    assert "emit_lineage_edge_rejected" in tools


async def test_confirm_404_on_unknown_edge_id(
    client: TestClient,
) -> None:
    """Edge not in the projection → 404 from the confirm handler."""
    company_id = tenant_to_uuid(TENANT_SLUG)
    resp = await client.post(
        "/api/v1/write_actions/lineage_edges_confirm/unknown-edge",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "confirmed_by": str(uuid4()),
        },
    )
    assert resp.status == 404, await resp.text()


async def test_reject_404_on_unknown_edge_id(
    client: TestClient,
) -> None:
    """Edge not in the projection → 404 from the reject handler."""
    company_id = tenant_to_uuid(TENANT_SLUG)
    resp = await client.post(
        "/api/v1/write_actions/lineage_edges_reject/unknown-edge",
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
    edge_id = "edge-reject-bad-reason"
    await _seed_proposed_edge(memory_ledger, edge_id=edge_id)
    company_id = tenant_to_uuid(TENANT_SLUG)

    resp = await client.post(
        f"/api/v1/write_actions/lineage_edges_reject/{edge_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(uuid4()),
            "reason": "made_up_reason",
        },
    )
    assert resp.status == 400, await resp.text()


async def test_confirm_company_id_mismatch_400(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Body ``company_id`` must match the X-Tenant-Slug header (400)."""
    edge_id = "edge-mismatch"
    await _seed_proposed_edge(memory_ledger, edge_id=edge_id)
    wrong_company = uuid4()  # not the baseworm tenant

    resp = await client.post(
        f"/api/v1/write_actions/lineage_edges_confirm/{edge_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(wrong_company),
            "confirmed_by": str(uuid4()),
        },
    )
    assert resp.status == 400, await resp.text()
