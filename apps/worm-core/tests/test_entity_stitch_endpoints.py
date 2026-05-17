"""L8 Sub-wave C — HTTP-endpoint tests for entity_stitches_confirm/reject.

Exercises the bearer-authed POST endpoints against the in-memory
ledger via aiohttp's TestClient harness — same pattern as
``test_lineage_edge_endpoints.py``,
``test_quality_check_endpoints.py``,
``test_schema_impact_endpoints.py``,
``test_semantic_type_endpoints.py``, and
``test_column_classification_endpoints.py``.

The handlers follow the v2.A + L3 + L7 + L4 + L5 + L6 pattern:

  * Bearer token at the HTTP layer (401 on miss).
  * X-Tenant-Slug resolves to company_id; body ``company_id`` must
    agree (400 on mismatch).
  * ``stitch_id`` must point at a prior ``entity_stitch_proposed``
    entry for the tenant (404 on unknown).
  * ``reason`` is a strict 5-value enum on the reject path (400 on
    unknown). The L8-specific 5th value is ``wrong_pairing``.
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

API_TOKEN = "test-token-entity-stitch"
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


async def _seed_proposed_stitch(
    memory_ledger: InMemoryLedger,
    *,
    stitch_id: str,
    company_id: UUID | None = None,
) -> None:
    """Seed an ``entity_stitch_proposed`` execute entry for the tenant.

    The handlers walk the ledger for this exact tool to surface 404
    on unknown stitches; seeding a propose-cycle is the canonical
    setup. Same pattern as L6's ``_seed_proposed_classification``.
    """
    cid = company_id if company_id is not None else tenant_to_uuid(TENANT_SLUG)
    args: dict[str, Any] = {
        "stitch_id": stitch_id,
        "src_source_id_a": "crm",
        "src_table_a": "crm.contacts",
        "src_column_a": "email",
        "src_source_id_b": "app",
        "src_table_b": "app.users",
        "src_column_b": "email_address",
        "upstream_semantic_type_id": None,
        "entity_kind": "person",
        "confidence": 0.85,
        "strategy": "name_match",
        "reasoning": "test seed",
        "evidence": {"path": "fuzzy_name", "similarity": 0.87},
    }
    await memory_ledger.write(
        company_id=cid,
        propose={
            "target_kind": "entity_stitch_proposed",
            "ref_id": stitch_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_entity_stitch_proposed",
            "args": args,
            "result_ref": stitch_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


async def test_confirm_missing_auth_returns_401(client: TestClient) -> None:
    """No bearer → 401 from the HTTP layer (matches v2.A + L3 + L7 + L4 + L5 + L6)."""
    resp = await client.post(
        "/api/v1/write_actions/entity_stitches_confirm/stitch-1",
        json={"company_id": str(uuid4()), "confirmed_by": str(uuid4())},
    )
    assert resp.status == 401


async def test_reject_missing_auth_returns_401(client: TestClient) -> None:
    """No bearer → 401 from the HTTP layer."""
    resp = await client.post(
        "/api/v1/write_actions/entity_stitches_reject/stitch-1",
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
    """Successful confirm emits an ``entity_stitch_confirmed`` entry."""
    stitch_id = "stitch-confirm-1"
    await _seed_proposed_stitch(memory_ledger, stitch_id=stitch_id)
    company_id = tenant_to_uuid(TENANT_SLUG)
    admin = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/entity_stitches_confirm/{stitch_id}",
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
    assert body["stitch_id"] == stitch_id
    assert body["stitchId"] == stitch_id

    entries = await memory_ledger.fetch(company_id)
    tools = [
        (e.get("payload") or {}).get("tool")
        for e in entries
        if e.get("kind") == "execute"
    ]
    assert "emit_entity_stitch_confirmed" in tools


async def test_reject_writes_ledger_entry(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Successful reject emits an ``entity_stitch_rejected`` entry."""
    stitch_id = "stitch-reject-1"
    await _seed_proposed_stitch(memory_ledger, stitch_id=stitch_id)
    company_id = tenant_to_uuid(TENANT_SLUG)
    admin = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/entity_stitches_reject/{stitch_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(admin),
            "reason": "wrong_pairing",
            "notes": "actually two different people sharing an email pattern",
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["rejected"] is True
    assert body["stitch_id"] == stitch_id
    assert body["reason"] == "wrong_pairing"

    entries = await memory_ledger.fetch(company_id)
    tools = [
        (e.get("payload") or {}).get("tool")
        for e in entries
        if e.get("kind") == "execute"
    ]
    assert "emit_entity_stitch_rejected" in tools


async def test_confirm_404_on_unknown_stitch_id(
    client: TestClient,
) -> None:
    """Stitch not in the projection → 404 from the confirm handler."""
    company_id = tenant_to_uuid(TENANT_SLUG)
    resp = await client.post(
        "/api/v1/write_actions/entity_stitches_confirm/unknown",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "confirmed_by": str(uuid4()),
        },
    )
    assert resp.status == 404, await resp.text()


async def test_reject_404_on_unknown_stitch_id(
    client: TestClient,
) -> None:
    """Stitch not in the projection → 404 from the reject handler."""
    company_id = tenant_to_uuid(TENANT_SLUG)
    resp = await client.post(
        "/api/v1/write_actions/entity_stitches_reject/unknown",
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

    L4's ``already_handled``, L7's ``wrong_threshold``, L5's
    ``wrong_type``, and L6's ``wrong_level`` are NOT valid L8 reasons
    — verifies the L8-specific 5-value enum is enforced (canonical
    L8-specific value is ``wrong_pairing``).
    """
    stitch_id = "stitch-reject-bad-reason"
    await _seed_proposed_stitch(memory_ledger, stitch_id=stitch_id)
    company_id = tenant_to_uuid(TENANT_SLUG)

    resp = await client.post(
        f"/api/v1/write_actions/entity_stitches_reject/{stitch_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(uuid4()),
            "reason": "wrong_level",  # L6 reason, not L8
        },
    )
    assert resp.status == 400, await resp.text()


async def test_confirm_company_id_mismatch_400(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Body ``company_id`` must match the X-Tenant-Slug header (400)."""
    stitch_id = "stitch-mismatch"
    await _seed_proposed_stitch(memory_ledger, stitch_id=stitch_id)
    wrong_company = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/entity_stitches_confirm/{stitch_id}",
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
    """The 5 canonical L8 reject reasons all 200 OK."""
    canonical = [
        "false_positive",
        "low_value",
        "wrong_pairing",  # L8-specific (distinct from L6's wrong_level)
        "out_of_scope",
        "other",
    ]
    company_id = tenant_to_uuid(TENANT_SLUG)
    for idx, reason in enumerate(canonical):
        stitch_id = f"stitch-reason-{idx}"
        await _seed_proposed_stitch(memory_ledger, stitch_id=stitch_id)
        resp = await client.post(
            f"/api/v1/write_actions/entity_stitches_reject/{stitch_id}",
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
