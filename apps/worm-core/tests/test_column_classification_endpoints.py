"""L6 Sub-wave C — HTTP-endpoint tests for column_classifications_confirm/reject.

Exercises the bearer-authed POST endpoints against the in-memory
ledger via aiohttp's TestClient harness — same pattern as
``test_lineage_edge_endpoints.py``,
``test_quality_check_endpoints.py``,
``test_schema_impact_endpoints.py``, and
``test_semantic_type_endpoints.py``.

The handlers follow the v2.A + L3 + L7 + L4 + L5 pattern:

  * Bearer token at the HTTP layer (401 on miss).
  * X-Tenant-Slug resolves to company_id; body ``company_id`` must
    agree (400 on mismatch).
  * ``classification_id`` must point at a prior
    ``column_classification_proposed`` entry for the tenant (404 on
    unknown).
  * ``reason`` is a strict 5-value enum on the reject path (400 on
    unknown). The L6-specific 5th value is ``wrong_level``.
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

API_TOKEN = "test-token-column-classification"
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


async def _seed_proposed_classification(
    memory_ledger: InMemoryLedger,
    *,
    classification_id: str,
    company_id: UUID | None = None,
) -> None:
    """Seed a ``column_classification_proposed`` execute entry for the tenant.

    The handlers walk the ledger for this exact tool to surface 404
    on unknown classifications; seeding a propose-cycle is the
    canonical setup.
    """
    cid = company_id if company_id is not None else tenant_to_uuid(TENANT_SLUG)
    args: dict[str, Any] = {
        "classification_id": classification_id,
        "table_id": "warehouse.dim_customer",
        "column": "email",
        "classification_level": "pii",
        "upstream_semantic_type_id": None,
        "confidence": 0.9,
        "strategy": "naming_pattern",
        "reasoning": "test seed",
        "evidence": {"regex": ".*"},
    }
    await memory_ledger.write(
        company_id=cid,
        propose={
            "target_kind": "column_classification_proposed",
            "ref_id": classification_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_column_classification_proposed",
            "args": args,
            "result_ref": classification_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


async def test_confirm_missing_auth_returns_401(client: TestClient) -> None:
    """No bearer → 401 from the HTTP layer (matches v2.A + L3 + L7 + L4 + L5)."""
    resp = await client.post(
        "/api/v1/write_actions/column_classifications_confirm/cls-1",
        json={"company_id": str(uuid4()), "confirmed_by": str(uuid4())},
    )
    assert resp.status == 401


async def test_reject_missing_auth_returns_401(client: TestClient) -> None:
    """No bearer → 401 from the HTTP layer."""
    resp = await client.post(
        "/api/v1/write_actions/column_classifications_reject/cls-1",
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
    """Successful confirm emits a ``column_classification_confirmed`` entry."""
    classification_id = "cls-confirm-1"
    await _seed_proposed_classification(
        memory_ledger, classification_id=classification_id,
    )
    company_id = tenant_to_uuid(TENANT_SLUG)
    admin = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/column_classifications_confirm/"
        f"{classification_id}",
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
    assert body["classification_id"] == classification_id
    assert body["classificationId"] == classification_id

    entries = await memory_ledger.fetch(company_id)
    tools = [
        (e.get("payload") or {}).get("tool")
        for e in entries
        if e.get("kind") == "execute"
    ]
    assert "emit_column_classification_confirmed" in tools


async def test_reject_writes_ledger_entry(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Successful reject emits a ``column_classification_rejected`` entry."""
    classification_id = "cls-reject-1"
    await _seed_proposed_classification(
        memory_ledger, classification_id=classification_id,
    )
    company_id = tenant_to_uuid(TENANT_SLUG)
    admin = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/column_classifications_reject/"
        f"{classification_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(admin),
            "reason": "wrong_level",
            "notes": "actually confidential not pii",
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["rejected"] is True
    assert body["classification_id"] == classification_id
    assert body["reason"] == "wrong_level"

    entries = await memory_ledger.fetch(company_id)
    tools = [
        (e.get("payload") or {}).get("tool")
        for e in entries
        if e.get("kind") == "execute"
    ]
    assert "emit_column_classification_rejected" in tools


async def test_confirm_404_on_unknown_classification_id(
    client: TestClient,
) -> None:
    """Classification not in the projection → 404 from the confirm handler."""
    company_id = tenant_to_uuid(TENANT_SLUG)
    resp = await client.post(
        "/api/v1/write_actions/column_classifications_confirm/unknown",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "confirmed_by": str(uuid4()),
        },
    )
    assert resp.status == 404, await resp.text()


async def test_reject_404_on_unknown_classification_id(
    client: TestClient,
) -> None:
    """Classification not in the projection → 404 from the reject handler."""
    company_id = tenant_to_uuid(TENANT_SLUG)
    resp = await client.post(
        "/api/v1/write_actions/column_classifications_reject/unknown",
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

    L4's ``already_handled`` and L5's ``wrong_type`` are NOT valid L6
    reasons — verifies the L6-specific 5-value enum is enforced
    (canonical L6-specific value is ``wrong_level``).
    """
    classification_id = "cls-reject-bad-reason"
    await _seed_proposed_classification(
        memory_ledger, classification_id=classification_id,
    )
    company_id = tenant_to_uuid(TENANT_SLUG)

    resp = await client.post(
        f"/api/v1/write_actions/column_classifications_reject/"
        f"{classification_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(uuid4()),
            "reason": "wrong_type",  # L5 reason, not L6
        },
    )
    assert resp.status == 400, await resp.text()


async def test_confirm_company_id_mismatch_400(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Body ``company_id`` must match the X-Tenant-Slug header (400)."""
    classification_id = "cls-mismatch"
    await _seed_proposed_classification(
        memory_ledger, classification_id=classification_id,
    )
    wrong_company = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/column_classifications_confirm/"
        f"{classification_id}",
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
    """The 5 canonical L6 reject reasons all 200 OK."""
    canonical = [
        "false_positive",
        "low_value",
        "wrong_level",  # L6-specific (distinct from L5's wrong_type)
        "out_of_scope",
        "other",
    ]
    company_id = tenant_to_uuid(TENANT_SLUG)
    for idx, reason in enumerate(canonical):
        classification_id = f"cls-reason-{idx}"
        await _seed_proposed_classification(
            memory_ledger, classification_id=classification_id,
        )
        resp = await client.post(
            f"/api/v1/write_actions/column_classifications_reject/"
            f"{classification_id}",
            headers=_auth_headers(),
            json={
                "company_id": str(company_id),
                "rejected_by": str(uuid4()),
                "reason": reason,
            },
        )
        assert resp.status == 200, (
            f"reason={reason!r} → status={resp.status} "
            f"text={await resp.text()}"
        )
