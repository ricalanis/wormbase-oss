"""L1 Sub-wave C — HTTP-endpoint tests for source_candidates_promote/reject.

Exercises the bearer-authed POST endpoints against the in-memory
ledger via aiohttp's TestClient harness — same pattern as
``test_entity_stitch_endpoints.py`` and the L3–L8 endpoint suites.

The handlers follow the v2.A + L3 + L7 + L4 + L5 + L6 + L8 pattern:

  * Bearer token at the HTTP layer (401 on miss).
  * X-Tenant-Slug resolves to company_id; body ``company_id`` must
    agree (400 on mismatch).
  * ``candidate_id`` must point at a prior ``source_candidate_proposed``
    entry for the tenant (404 on unknown).
  * ``reason`` is a strict 5-value enum on the reject path (400 on
    unknown). The L1-specific 5th value is ``duplicate``.
  * Admin role enforcement lives at the dashboard server action layer
    (defense in depth) — the HTTP layer is bearer + tenant only.

L1-specific: the promote handler dual-writes — it emits BOTH a
``source_candidate_promoted`` audit entry AND triggers the existing
:class:`SourceBuilder` flow to emit a downstream ``source_proposed``
entry. The handler threads the source-builder correlation_id back
into the L1 promote payload as ``downstream_source_proposed_id``.
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

API_TOKEN = "test-token-source-candidate"
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


async def _seed_proposed_candidate(
    memory_ledger: InMemoryLedger,
    *,
    candidate_id: str,
    proposed_kind: str = "csv_local",
    proposed_identifier: str = "s3://bucket/file.csv",
    company_id: UUID | None = None,
) -> None:
    """Seed a ``source_candidate_proposed`` execute entry for the tenant.

    The handlers walk the ledger for this exact tool to surface 404
    on unknown candidates; seeding a propose-cycle is the canonical
    setup. Same pattern as L8's ``_seed_proposed_stitch``.
    """
    cid = company_id if company_id is not None else tenant_to_uuid(TENANT_SLUG)
    args: dict[str, Any] = {
        "candidate_id": candidate_id,
        "proposed_kind": proposed_kind,
        "proposed_identifier": proposed_identifier,
        "domain_id_hint": None,
        "strategy": "kpi_gap",
        "reasoning": "test seed",
        "confidence": 0.7,
        "evidence": {"kpi_node_id": "k-1"},
    }
    await memory_ledger.write(
        company_id=cid,
        propose={
            "target_kind": "source_candidate_proposed",
            "ref_id": candidate_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_candidate_proposed",
            "args": args,
            "result_ref": candidate_id,
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


async def test_promote_missing_auth_returns_401(client: TestClient) -> None:
    """No bearer → 401 from the HTTP layer."""
    resp = await client.post(
        "/api/v1/write_actions/source_candidates_promote/cand-1",
        json={"company_id": str(uuid4()), "promoted_by": str(uuid4())},
    )
    assert resp.status == 401


async def test_reject_missing_auth_returns_401(client: TestClient) -> None:
    """No bearer → 401 from the HTTP layer."""
    resp = await client.post(
        "/api/v1/write_actions/source_candidates_reject/cand-1",
        json={
            "company_id": str(uuid4()),
            "rejected_by": str(uuid4()),
            "reason": "duplicate",
        },
    )
    assert resp.status == 401


async def test_promote_404_on_unknown_candidate_id(
    client: TestClient,
) -> None:
    """Candidate not in the ledger → 404 from the promote handler."""
    company_id = tenant_to_uuid(TENANT_SLUG)
    resp = await client.post(
        "/api/v1/write_actions/source_candidates_promote/unknown-cand",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "promoted_by": str(uuid4()),
        },
    )
    assert resp.status == 404, await resp.text()


async def test_reject_404_on_unknown_candidate_id(
    client: TestClient,
) -> None:
    """Candidate not in the ledger → 404 from the reject handler."""
    company_id = tenant_to_uuid(TENANT_SLUG)
    resp = await client.post(
        "/api/v1/write_actions/source_candidates_reject/unknown-cand",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(uuid4()),
            "reason": "duplicate",
        },
    )
    assert resp.status == 404, await resp.text()


async def test_promote_company_id_mismatch_400(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Body ``company_id`` must match the X-Tenant-Slug header (400)."""
    candidate_id = "cand-mismatch"
    await _seed_proposed_candidate(
        memory_ledger, candidate_id=candidate_id,
    )
    wrong_company = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/source_candidates_promote/{candidate_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(wrong_company),
            "promoted_by": str(uuid4()),
        },
    )
    assert resp.status == 400, await resp.text()


# ---------------------------------------------------------------------------
# Promote — dual-write verification
# ---------------------------------------------------------------------------


async def test_promote_writes_audit_entry(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Successful promote emits a ``source_candidate_promoted`` entry."""
    candidate_id = "cand-promote-1"
    await _seed_proposed_candidate(
        memory_ledger, candidate_id=candidate_id,
    )
    company_id = tenant_to_uuid(TENANT_SLUG)
    admin = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/source_candidates_promote/{candidate_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "promoted_by": str(admin),
            "notes": "approved",
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["promoted"] is True
    assert body["candidate_id"] == candidate_id
    assert body["candidateId"] == candidate_id

    entries = await memory_ledger.fetch(company_id)
    tools = [
        (e.get("payload") or {}).get("tool")
        for e in entries
        if e.get("kind") == "execute"
    ]
    assert "emit_source_candidate_promoted" in tools


async def test_promote_dual_writes_downstream_source_proposed(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Successful promote ALSO emits a downstream ``source_proposed``.

    Dual-write verification per spec §8 + plan dispatch step 4 — the
    promote handler invokes :class:`SourceBuilder.propose` to seed
    the existing source-pipeline flow, and threads the resulting
    correlation_id back into the ``source_candidate_promoted``
    payload as ``downstream_source_proposed_id``.
    """
    candidate_id = "cand-dual-1"
    await _seed_proposed_candidate(
        memory_ledger,
        candidate_id=candidate_id,
        proposed_kind="postgres",
        proposed_identifier="postgres://demo.db",
    )
    company_id = tenant_to_uuid(TENANT_SLUG)
    admin = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/source_candidates_promote/{candidate_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "promoted_by": str(admin),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    # downstream link is populated when the dual-write step-2 succeeds
    assert body["downstream_source_proposed_id"] is not None
    assert body["downstreamSourceProposedId"] == (
        body["downstream_source_proposed_id"]
    )

    entries = await memory_ledger.fetch(company_id)
    tools = [
        (e.get("payload") or {}).get("tool")
        for e in entries
        if e.get("kind") == "execute"
    ]
    # Both entries land — promote audit + downstream source_proposed
    assert "emit_source_candidate_promoted" in tools
    assert "emit_source_proposed" in tools

    # The promote payload threads the downstream correlation id
    promoted_args = next(
        (e.get("payload") or {}).get("args")
        for e in entries
        if e.get("kind") == "execute"
        and (e.get("payload") or {}).get("tool")
        == "emit_source_candidate_promoted"
    )
    assert promoted_args is not None
    assert promoted_args.get("downstream_source_proposed_id") == (
        body["downstream_source_proposed_id"]
    )


# ---------------------------------------------------------------------------
# Reject — 5-value enum + happy path
# ---------------------------------------------------------------------------


async def test_reject_writes_ledger_entry(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Successful reject emits a ``source_candidate_rejected`` entry."""
    candidate_id = "cand-reject-1"
    await _seed_proposed_candidate(
        memory_ledger, candidate_id=candidate_id,
    )
    company_id = tenant_to_uuid(TENANT_SLUG)
    admin = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/source_candidates_reject/{candidate_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(admin),
            "reason": "duplicate",
            "notes": "already have it",
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["rejected"] is True
    assert body["candidate_id"] == candidate_id
    assert body["reason"] == "duplicate"

    entries = await memory_ledger.fetch(company_id)
    tools = [
        (e.get("payload") or {}).get("tool")
        for e in entries
        if e.get("kind") == "execute"
    ]
    assert "emit_source_candidate_rejected" in tools


async def test_reject_400_on_invalid_reason(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Invalid reject ``reason`` → 400.

    L4's ``already_handled``, L7's ``wrong_threshold``, L5's
    ``wrong_type``, L6's ``wrong_level`` and L8's ``wrong_pairing``
    are NOT valid L1 reasons — verifies the L1-specific 5-value enum
    is enforced (canonical L1-specific value is ``duplicate``).
    """
    candidate_id = "cand-reject-bad-reason"
    await _seed_proposed_candidate(
        memory_ledger, candidate_id=candidate_id,
    )
    company_id = tenant_to_uuid(TENANT_SLUG)

    resp = await client.post(
        f"/api/v1/write_actions/source_candidates_reject/{candidate_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(company_id),
            "rejected_by": str(uuid4()),
            "reason": "wrong_pairing",  # L8 reason, not L1
        },
    )
    assert resp.status == 400, await resp.text()


async def test_reject_accepts_all_5_canonical_reasons(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """The 5 canonical L1 reject reasons all 200 OK.

    L1's 5-value enum: {duplicate, false_positive, low_value,
    out_of_scope, other}. ``duplicate`` is L1-specific (replaces
    L8's ``wrong_pairing``).
    """
    canonical = [
        "duplicate",  # L1-specific
        "false_positive",
        "low_value",
        "out_of_scope",
        "other",
    ]
    company_id = tenant_to_uuid(TENANT_SLUG)
    for idx, reason in enumerate(canonical):
        candidate_id = f"cand-reason-{idx}"
        await _seed_proposed_candidate(
            memory_ledger, candidate_id=candidate_id,
        )
        resp = await client.post(
            f"/api/v1/write_actions/source_candidates_reject/{candidate_id}",
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


async def test_reject_company_id_mismatch_400(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Body ``company_id`` must match X-Tenant-Slug (400)."""
    candidate_id = "cand-reject-mismatch"
    await _seed_proposed_candidate(
        memory_ledger, candidate_id=candidate_id,
    )
    wrong_company = uuid4()

    resp = await client.post(
        f"/api/v1/write_actions/source_candidates_reject/{candidate_id}",
        headers=_auth_headers(),
        json={
            "company_id": str(wrong_company),
            "rejected_by": str(uuid4()),
            "reason": "duplicate",
        },
    )
    assert resp.status == 400, await resp.text()
