"""HTTP API integration tests for /research approve/reject + /mcp tokens (W2.A9).

Two integration tests at module scope cover the wire-level acceptance:

  1. ``test_post_experiment_approve_writes_emit_experiment_resolved_keep``
     drives ``POST /api/v1/experiments/{id}/approve`` against an
     InMemoryLedger and asserts a full PEVR cycle of
     ``emit_experiment_resolved`` with ``outcome=keep`` lands. Reject
     mirrors the same shape with ``outcome=discard``.

  2. ``test_mcp_token_issuance_authorizes_query_ledger`` drives
     ``POST /api/v1/mcp/tokens`` to mint a Person-scoped bearer, then
     decodes it via ``mcp_tools.auth.authorize_caller`` to confirm it
     would authenticate a Claude Desktop client calling the live MCP
     server. This is the testable form of the acceptance criterion
     "Connect Claude Desktop generates a working bearer that, when
     pasted into Claude Desktop config, produces successful
     query_ledger calls against this server."

Uses aiohttp's TestClient + InMemoryLedger so the suite stays
container-free; hash-chain semantics are byte-for-byte identical to
the production DB-backed Ledger (see test_http_api.py module docstring).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import MagicMock
from uuid import uuid4

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core.http_api import build_app
from wormbase_core.mcp_tools.auth import (
    authorize_caller,
    decode_compact_token,
)
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.hash_chain import verify_chain


API_TOKEN = "test-token-w2a9"
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


def _auth() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "X-Tenant-Slug": TENANT_SLUG,
    }


# ---------------------------------------------------------------------------
# /research approve + reject
# ---------------------------------------------------------------------------


async def test_post_experiment_approve_no_auth_returns_401(
    client: TestClient,
) -> None:
    eid = uuid4()
    resp = await client.post(
        f"/api/v1/experiments/{eid}/approve",
        json={"resolved_by": str(uuid4())},
    )
    assert resp.status == 401


async def test_post_experiment_approve_writes_emit_experiment_resolved_keep(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    eid = uuid4()
    resolver = uuid4()
    resp = await client.post(
        f"/api/v1/experiments/{eid}/approve",
        headers=_auth(),
        json={
            "resolved_by": str(resolver),
            "rationale": "operator approved via /research",
            "observed_delta": 0.42,
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["experiment_id"] == str(eid)
    assert body["outcome"] == "keep"
    assert body["rationale"] == "operator approved via /research"
    assert len(body["entry_ids"]) == 4

    # The ledger should now hold a clean PEVR cycle for this entry.
    company_id = tenant_to_uuid(TENANT_SLUG)
    rows = await memory_ledger.fetch(company_id)
    assert len(rows) == 4
    ok, _ = verify_chain(rows)
    assert ok

    execute_rows = [r for r in rows if r["kind"] == "execute"]
    assert len(execute_rows) == 1
    exe = execute_rows[0]
    assert exe["payload"]["tool"] == "emit_experiment_resolved"
    assert exe["payload"]["args"]["outcome"] == "keep"
    assert exe["payload"]["args"]["experiment_id"] == str(eid)
    assert exe["payload"]["args"]["observed_delta"] == 0.42


async def test_post_experiment_reject_writes_outcome_discard(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    eid = uuid4()
    resp = await client.post(
        f"/api/v1/experiments/{eid}/reject",
        headers=_auth(),
        json={"resolved_by": str(uuid4())},
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["outcome"] == "discard"

    company_id = tenant_to_uuid(TENANT_SLUG)
    rows = await memory_ledger.fetch(company_id)
    execute_rows = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_experiment_resolved"
    ]
    assert len(execute_rows) == 1
    assert execute_rows[0]["payload"]["args"]["outcome"] == "discard"


async def test_post_experiment_approve_default_rationale(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Empty / missing rationale falls back to a deterministic phrase."""
    eid = uuid4()
    resolver = uuid4()
    resp = await client.post(
        f"/api/v1/experiments/{eid}/approve",
        headers=_auth(),
        json={"resolved_by": str(resolver)},
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["rationale"].startswith("manual keep from /research")
    assert str(resolver) in body["rationale"]


async def test_post_experiment_approve_bad_uuid_in_path(
    client: TestClient,
) -> None:
    resp = await client.post(
        "/api/v1/experiments/not-a-uuid/approve",
        headers=_auth(),
        json={"resolved_by": str(uuid4())},
    )
    assert resp.status == 400


async def test_post_experiment_approve_validation_error(
    client: TestClient,
) -> None:
    eid = uuid4()
    resp = await client.post(
        f"/api/v1/experiments/{eid}/approve",
        headers=_auth(),
        json={},
    )
    assert resp.status == 422


# ---------------------------------------------------------------------------
# /mcp tokens
# ---------------------------------------------------------------------------


async def test_post_mcp_tokens_no_auth_returns_401(client: TestClient) -> None:
    resp = await client.post(
        "/api/v1/mcp/tokens",
        json={"person_id": str(uuid4())},
    )
    assert resp.status == 401


async def test_post_mcp_tokens_issues_decodable_compact_token(
    client: TestClient,
) -> None:
    person_id = uuid4()
    resp = await client.post(
        "/api/v1/mcp/tokens",
        headers=_auth(),
        json={
            "person_id": str(person_id),
            "ttl_seconds": 3600,
            "label": "Carol's MacBook",
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()

    assert body["person_id"] == str(person_id)
    assert body["tenant_slug"] == TENANT_SLUG
    assert body["ttl_seconds"] == 3600
    assert body["label"] == "Carol's MacBook"
    assert "issued_at" in body and "expires_at" in body

    token = body["token"]
    assert isinstance(token, str) and "." in token

    claims = decode_compact_token(token, secret=API_TOKEN)
    assert claims is not None
    assert claims["person_id"] == str(person_id)
    assert claims["tenant_slug"] == TENANT_SLUG


async def test_post_mcp_tokens_audits_issuance_to_ledger(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    person_id = uuid4()
    resp = await client.post(
        "/api/v1/mcp/tokens",
        headers=_auth(),
        json={"person_id": str(person_id), "label": "demo"},
    )
    assert resp.status == 200, await resp.text()

    company_id = tenant_to_uuid(TENANT_SLUG)
    rows = await memory_ledger.fetch(company_id)
    issuance_rows = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_mcp_call_received"
        and r["payload"].get("args", {}).get("tool_name")
        == "emit_mcp_token_issued"
    ]
    assert len(issuance_rows) == 1
    args = issuance_rows[0]["payload"]["args"]
    assert args["caller_person_id"] == str(person_id)
    assert args["outcome"] == "ok"


async def test_post_mcp_tokens_default_ttl_is_30_days(
    client: TestClient,
) -> None:
    """Acceptance: default TTL is 30 days when not explicitly supplied."""
    resp = await client.post(
        "/api/v1/mcp/tokens",
        headers=_auth(),
        json={"person_id": str(uuid4())},
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["ttl_seconds"] == 30 * 24 * 60 * 60


async def test_mcp_token_issuance_authorizes_query_ledger(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Acceptance: a token issued by /api/v1/mcp/tokens authorizes
    against the same ``authorize_caller`` Claude Desktop's MCP path uses.

    This is the wire-level form of the acceptance criterion. We exercise
    the same compact-token verification path that ``mcp_server.py``
    would use for an inbound MCP request, so a copy-paste of this token
    into Claude Desktop's config produces a successful ``query_ledger``
    call against worm-core.
    """
    person_id = uuid4()
    # Phase 1B.F: seed the Person row so authorize_caller's binding gate
    # accepts the issued token. The test exercises the wire-level form
    # of the issuance + verification round-trip, but the gate now
    # requires a real Person row in projection_persons for the bound
    # tenant (see apps/worm-core/src/wormbase_core/mcp_tools/auth.py).
    await memory_ledger.write(
        company_id=tenant_to_uuid(TENANT_SLUG),
        propose={
            "target_kind": "person_proposed",
            "ref_id": str(person_id),
            "reason": "seed person row for 1B.F gate",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_person_proposed",
            "args": {
                "person_id": str(person_id),
                "tenant_id": str(tenant_to_uuid(TENANT_SLUG)),
                "name": "Test Person",
                "email": f"{person_id}@test.invalid",
                "proposed_by": "test",
            },
            "result_ref": str(person_id),
        },
        verify_fn=lambda _ep: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )

    resp = await client.post(
        "/api/v1/mcp/tokens",
        headers=_auth(),
        json={"person_id": str(person_id)},
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    token = body["token"]

    # Simulate an inbound MCP request carrying our token. ``Context`` is
    # the FastMCP-side handle into the Starlette request; we mock just
    # the surface ``mcp_tools.auth`` reads (headers via request_context).
    mock_headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Slug": TENANT_SLUG,
    }
    mock_request = MagicMock()
    mock_request.headers = mock_headers
    mock_request_context = MagicMock()
    mock_request_context.request = mock_request
    mock_ctx = MagicMock()
    type(mock_ctx).request_context = property(lambda _self: mock_request_context)

    caller_ctx = await authorize_caller(
        mock_ctx,
        ledger=memory_ledger,
        api_token=API_TOKEN,
        fallback_company_id=None,
    )
    assert caller_ctx["caller_person_id"] == person_id
    assert caller_ctx["tenant_slug"] == TENANT_SLUG
    # The token was accepted (no PermissionError raised) and the
    # caller's company resolved to the tenant the token was scoped to.
    # That's the wire-level "this token would authorize a query_ledger
    # call from Claude Desktop" check — role-fold is downstream.
    assert caller_ctx["company_id"] == tenant_to_uuid(TENANT_SLUG)


# ---------------------------------------------------------------------------
# /mcp Add MCP server wizard → preset registration
# ---------------------------------------------------------------------------


async def test_post_mcp_preset_writes_source_proposed_with_mcp_kind(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    proposer = uuid4()
    resp = await client.post(
        "/api/v1/mcp/presets",
        headers=_auth(),
        json={
            "kind": "notion",
            "server_url": "https://mcp.notion.com/mcp",
            "description": "Notion MCP server",
            "suggested_domain": "knowledge",
            "suggested_classification": "internal",
            "proposed_by": str(proposer),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["source_kind"] == "mcp:notion"
    assert body["uri"] == "https://mcp.notion.com/mcp"
    assert len(body["entry_ids"]) == 4

    company_id = tenant_to_uuid(TENANT_SLUG)
    rows = await memory_ledger.fetch(company_id)
    proposed = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_source_proposed"
    ]
    assert len(proposed) == 1
    args = proposed[0]["payload"]["args"]
    assert args["source_kind"] == "mcp:notion"
    assert args["added_via_flow"] == "dashboard_form"
    assert args["suggested_domain"] == "knowledge"
    assert args["suggested_classification"] == "internal"


async def test_post_mcp_preset_idempotent_kind_prefix(
    client: TestClient,
) -> None:
    """Caller may pass kind already prefixed with ``mcp:``; we don't double-prefix."""
    resp = await client.post(
        "/api/v1/mcp/presets",
        headers=_auth(),
        json={
            "kind": "mcp:atlassian",
            "server_url": "https://mcp.atlassian.com/v1/sse",
            "proposed_by": str(uuid4()),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["source_kind"] == "mcp:atlassian"
