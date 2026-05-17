"""L2 Sub-wave C — HTTP-endpoint tests for catalog_drifts_acknowledge/reject.

Exercises the bearer-authed POST endpoints against the in-memory
ledger via aiohttp's TestClient harness — same pattern as
``test_entity_stitch_endpoints.py`` and the L3-L8 + L1 endpoint suites.

The handlers follow the v2.A + L3 + L7 + L4 + L5 + L6 + L8 + L1 pattern:

  * Bearer token at the HTTP layer (401 on miss).
  * X-Tenant-Slug resolves to company_id; body ``company_id`` must
    agree (400 on mismatch).
  * ``drift_id`` must point at a prior ``catalog_drift_proposed``
    entry for the tenant (404 on unknown).
  * ``reason`` is a strict 5-value enum on the reject path (400 on
    unknown). The L2-specific 5th value is ``expected_change``.
  * Admin role enforcement lives at the dashboard server action layer
    (defense in depth) — the HTTP layer is bearer + tenant only.

L2-specific: uses ``acknowledge`` rather than ``confirm`` because the
drift was already observed by the catalog-mirror's W5a Reactivity;
acknowledgment is a no-op record (no downstream pipeline trigger,
no cross-axis effect).
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

API_TOKEN = "test-token-catalog-drift"
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


async def _seed_proposed_drift(
    memory_ledger: InMemoryLedger,
    *,
    drift_id: str,
    source_id: str = "src-A",
    table_id: str = "schema.table_a",
    drift_kind: str = "table_added",
    company_id: UUID | None = None,
) -> None:
    """Seed a ``catalog_drift_proposed`` execute entry for the tenant.

    The handlers walk the ledger for this exact tool to surface 404
    on unknown drifts; seeding a propose-cycle is the canonical
    setup. Same pattern as L8's ``_seed_proposed_stitch`` and L1's
    ``_seed_proposed_candidate``.
    """
    cid = company_id if company_id is not None else tenant_to_uuid(TENANT_SLUG)
    # Build a payload that satisfies the per-drift_kind invariants:
    # table_added → column=None, before=None, after={"table_id": ...}.
    after: dict[str, Any] | None
    before: dict[str, Any] | None
    column: str | None
    if drift_kind == "table_added":
        column = None
        before = None
        after = {"table_id": table_id}
    elif drift_kind == "table_removed":
        column = None
        before = {"table_id": table_id}
        after = None
    elif drift_kind == "column_added":
        column = "new_col"
        before = None
        after = {"name": "new_col"}
    elif drift_kind == "column_removed":
        column = "old_col"
        before = {"name": "old_col"}
        after = None
    else:  # column_type_changed
        column = "typed_col"
        before = {"type": "varchar"}
        after = {"type": "text"}

    args: dict[str, Any] = {
        "drift_id": drift_id,
        "source_id": source_id,
        "table_id": table_id,
        "column": column,
        "drift_kind": drift_kind,
        "before": before,
        "after": after,
        "strategy": "table_set",
        "reasoning": "test seed",
        "confidence": 0.9,
        "evidence": {"heuristic": "table_set_diff"},
    }
    await memory_ledger.write(
        company_id=cid,
        propose={
            "target_kind": "catalog_drift_proposed",
            "ref_id": drift_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_catalog_drift_proposed",
            "args": args,
            "result_ref": drift_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


# ---------------------------------------------------------------------------
# Auth + tenant + missing-id paths
# ---------------------------------------------------------------------------


async def test_acknowledge_missing_auth_returns_401(
    client: TestClient,
) -> None:
    """No bearer → 401 from the HTTP layer."""
    resp = await client.post(
        "/api/v1/write_actions/catalog_drifts_acknowledge/drift-1",
        json={"company_id": str(uuid4()), "acknowledged_by": str(uuid4())},
    )
    assert resp.status == 401


async def test_reject_missing_auth_returns_401(client: TestClient) -> None:
    """No bearer → 401 from the HTTP layer."""
    resp = await client.post(
        "/api/v1/write_actions/catalog_drifts_reject/drift-1",
        json={
            "company_id": str(uuid4()),
            "rejected_by": str(uuid4()),
            "reason": "expected_change",
        },
    )
    assert resp.status == 401


async def test_acknowledge_404_on_unknown_drift_id(
    client: TestClient,
) -> None:
    """Drift not in the ledger → 404 from the acknowledge handler."""
    company_id = tenant_to_uuid(TENANT_SLUG)
    resp = await client.post(
        "/api/v1/write_actions/catalog_drifts_acknowledge/unknown-drift",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "acknowledged_by": str(uuid4()),
        },
    )
    assert resp.status == 404, await resp.text()


async def test_reject_404_on_unknown_drift_id(client: TestClient) -> None:
    """Drift not in the ledger → 404 from the reject handler."""
    company_id = tenant_to_uuid(TENANT_SLUG)
    resp = await client.post(
        "/api/v1/write_actions/catalog_drifts_reject/unknown-drift",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(uuid4()),
            "reason": "expected_change",
        },
    )
    assert resp.status == 404, await resp.text()


async def test_acknowledge_company_id_mismatch_400(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Body ``company_id`` must match the X-Tenant-Slug header (400)."""
    drift_id = "drift-mismatch"
    await _seed_proposed_drift(memory_ledger, drift_id=drift_id)
    wrong_company = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/catalog_drifts_acknowledge/{drift_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(wrong_company),
            "acknowledged_by": str(uuid4()),
        },
    )
    assert resp.status == 400, await resp.text()


async def test_reject_company_id_mismatch_400(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Body ``company_id`` must match X-Tenant-Slug (400)."""
    drift_id = "drift-reject-mismatch"
    await _seed_proposed_drift(memory_ledger, drift_id=drift_id)
    wrong_company = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/catalog_drifts_reject/{drift_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(wrong_company),
            "rejected_by": str(uuid4()),
            "reason": "expected_change",
        },
    )
    assert resp.status == 400, await resp.text()


# ---------------------------------------------------------------------------
# Acknowledge happy path
# ---------------------------------------------------------------------------


async def test_acknowledge_writes_audit_entry(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Successful acknowledge emits a ``catalog_drift_acknowledged`` entry."""
    drift_id = "drift-ack-1"
    await _seed_proposed_drift(memory_ledger, drift_id=drift_id)
    company_id = tenant_to_uuid(TENANT_SLUG)
    admin = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/catalog_drifts_acknowledge/{drift_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "acknowledged_by": str(admin),
            "notes": "known migration",
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["acknowledged"] is True
    assert body["drift_id"] == drift_id
    assert body["driftId"] == drift_id

    entries = await memory_ledger.fetch(company_id)
    tools = [
        (e.get("payload") or {}).get("tool")
        for e in entries
        if e.get("kind") == "execute"
    ]
    assert "emit_catalog_drift_acknowledged" in tools


async def test_acknowledge_url_uses_acknowledge_not_confirm(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """URL path uses ``acknowledge``, not ``confirm`` — L2 doctrine.

    L2 diverges from L3-L8's ``confirm`` because acknowledgment is a
    no-op record (the drift was already observed by catalog-mirror).
    The ``acknowledge`` verb in the URL path is load-bearing.
    """
    # The ``confirm`` URL must NOT exist on the L2 catalog-drift
    # router. Hitting it must return 404 from the router (no route
    # match), not from the handler.
    drift_id = "drift-verb-1"
    await _seed_proposed_drift(memory_ledger, drift_id=drift_id)
    company_id = tenant_to_uuid(TENANT_SLUG)

    # The acknowledge route exists and 200s with the right body.
    ok_resp = await client.post(
        f"/api/v1/write_actions/catalog_drifts_acknowledge/{drift_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "acknowledged_by": str(uuid4()),
        },
    )
    assert ok_resp.status == 200, await ok_resp.text()

    # The confirm route does NOT exist (router-level 404).
    bad_resp = await client.post(
        f"/api/v1/write_actions/catalog_drifts_confirm/{drift_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "acknowledged_by": str(uuid4()),
        },
    )
    assert bad_resp.status == 404


# ---------------------------------------------------------------------------
# Reject — 5-value enum + happy path
# ---------------------------------------------------------------------------


async def test_reject_writes_ledger_entry(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Successful reject emits a ``catalog_drift_rejected`` entry."""
    drift_id = "drift-reject-1"
    await _seed_proposed_drift(memory_ledger, drift_id=drift_id)
    company_id = tenant_to_uuid(TENANT_SLUG)
    admin = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/catalog_drifts_reject/{drift_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(admin),
            "reason": "expected_change",
            "notes": "planned schema migration",
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["rejected"] is True
    assert body["drift_id"] == drift_id
    assert body["reason"] == "expected_change"

    entries = await memory_ledger.fetch(company_id)
    tools = [
        (e.get("payload") or {}).get("tool")
        for e in entries
        if e.get("kind") == "execute"
    ]
    assert "emit_catalog_drift_rejected" in tools


async def test_reject_400_on_invalid_reason(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Invalid reject ``reason`` → 400.

    L4's ``already_handled``, L7's ``wrong_threshold``, L5's
    ``wrong_type``, L6's ``wrong_level``, L8's ``wrong_pairing``,
    and L1's ``duplicate`` are NOT valid L2 reasons — verifies the
    L2-specific 5-value enum is enforced (canonical L2-specific
    value is ``expected_change``).
    """
    drift_id = "drift-reject-bad-reason"
    await _seed_proposed_drift(memory_ledger, drift_id=drift_id)
    company_id = tenant_to_uuid(TENANT_SLUG)

    resp = await client.post(
        f"/api/v1/write_actions/catalog_drifts_reject/{drift_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(uuid4()),
            "reason": "duplicate",  # L1 reason, not L2
        },
    )
    assert resp.status == 400, await resp.text()


async def test_reject_accepts_all_5_canonical_reasons(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """The 5 canonical L2 reject reasons all 200 OK.

    L2's 5-value enum: {false_positive, inconsequential,
    expected_change, out_of_scope, other}. ``expected_change`` is
    L2-specific (distinct from L1's ``duplicate``, L8's
    ``wrong_pairing``, etc).
    """
    canonical = [
        "false_positive",
        "inconsequential",
        "expected_change",  # L2-specific
        "out_of_scope",
        "other",
    ]
    company_id = tenant_to_uuid(TENANT_SLUG)
    for idx, reason in enumerate(canonical):
        drift_id = f"drift-reason-{idx}"
        await _seed_proposed_drift(memory_ledger, drift_id=drift_id)
        resp = await client.post(
            f"/api/v1/write_actions/catalog_drifts_reject/{drift_id}",
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


async def test_acknowledge_then_reject_writes_both_entries(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Forward-only re-disposition is supported (additive entries)."""
    drift_id = "drift-ack-then-reject"
    await _seed_proposed_drift(memory_ledger, drift_id=drift_id)
    company_id = tenant_to_uuid(TENANT_SLUG)
    admin = uuid4()

    ack_resp = await client.post(
        f"/api/v1/write_actions/catalog_drifts_acknowledge/{drift_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "acknowledged_by": str(admin),
        },
    )
    assert ack_resp.status == 200

    reject_resp = await client.post(
        f"/api/v1/write_actions/catalog_drifts_reject/{drift_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(admin),
            "reason": "false_positive",
        },
    )
    assert reject_resp.status == 200

    entries = await memory_ledger.fetch(company_id)
    tools = [
        (e.get("payload") or {}).get("tool")
        for e in entries
        if e.get("kind") == "execute"
    ]
    # Forward-only: both audit entries land additively.
    assert "emit_catalog_drift_acknowledged" in tools
    assert "emit_catalog_drift_rejected" in tools
