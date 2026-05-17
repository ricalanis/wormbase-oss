"""POST /api/v1/write_actions/promote_semantic_gap — Wave 3 Task 5 → v1.1.

Backs the v1.1 production-hardening plan Task 4. The dashboard's
``/lake/metrics-proposed`` Promote button posts to the legacy alias
``/api/v1/lake/metrics-proposed/promote``; v1.1 wires both this
canonical path AND the legacy alias to the same handler so the
dashboard works whether it points at either.

Coverage:
- Happy path: gap entry exists → external_metric_imported lands with
  caused_by linking to the gap entry id.
- Non-gap entry id → 400 (the referenced entry isn't a
  semantic_gap_proposed cycle row).
- Unknown entry id → 400.
- Legacy alias path (/api/v1/lake/metrics-proposed/promote) also works.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from wormbase_core.http_api import build_app
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger

API_TOKEN = "test-token-promote-gap"
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


async def _seed_semantic_gap(
    memory_ledger: InMemoryLedger,
) -> str:
    """Write a semantic_gap_proposed PEVR cycle; return the execute entry id."""
    agent_id = uuid4()
    await memory_ledger.write(
        company_id=_company_id(),
        propose={
            "target_kind": "semantic_gap_proposed",
            "ref_id": str(agent_id),
            "reason": "test seed: agent cannot find a matching metric",
            "proposed_by": str(agent_id),
        },
        execute_fn=lambda: {
            "tool": "emit_semantic_gap_proposed",
            "args": {
                "agent_id": str(agent_id),
                "nl_question": "what was q3 net revenue?",
                "reason": "no_match",
                "proposed_metric_name": "net_revenue_quarterly",
            },
            "result_ref": str(agent_id),
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "gap seeded for test",
        },
        quadrant="active_deterministic",
    )

    rows = await memory_ledger.fetch(_company_id())
    # The execute row is the canonical reference target.
    execute_rows = [r for r in rows if r["kind"] == "execute"]
    return str(execute_rows[0]["entry_id"])


async def test_promote_semantic_gap_happy_path(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Gap entry id → external_metric_imported lands with caused_by chain."""
    gap_entry_id = await _seed_semantic_gap(memory_ledger)
    domain_id = uuid4()
    admin_id = uuid4()

    resp = await client.post(
        "/api/v1/write_actions/promote_semantic_gap",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "semantic_gap_entry_id": gap_entry_id,
            "metric_name": "net_revenue_quarterly",
            "metric_expression": "SUM(amount) WHERE quarter = ?",
            "domain_id": str(domain_id),
            "promoted_by": str(admin_id),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert UUID(body["metric_id"])
    assert body["metric_id"] == body["metricId"]

    rows = await memory_ledger.fetch(_company_id())
    # Original gap cycle = 4 entries; new metric cycle = 4 entries.
    assert len(rows) == 8

    propose_rows = [r for r in rows if r["kind"] == "propose"]
    # The 2nd propose is the metric-import propose with caused_by.
    metric_propose = propose_rows[-1]
    assert metric_propose["payload"]["target_kind"] == "external_metric_imported"
    assert metric_propose["payload"]["caused_by"] == gap_entry_id

    execute_rows = [r for r in rows if r["kind"] == "execute"]
    metric_execute = execute_rows[-1]
    assert metric_execute["payload"]["tool"] == "emit_external_metric_imported"
    metric_args = metric_execute["payload"]["args"]
    assert metric_args["name"] == "net_revenue_quarterly"
    assert metric_args["promoted_from_gap_id"] == gap_entry_id
    assert metric_args["promoted_by"] == str(admin_id)


async def test_promote_semantic_gap_legacy_alias_path(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """The legacy ``/api/v1/lake/metrics-proposed/promote`` alias works too."""
    gap_entry_id = await _seed_semantic_gap(memory_ledger)

    resp = await client.post(
        "/api/v1/lake/metrics-proposed/promote",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "semantic_gap_entry_id": gap_entry_id,
            "metric_name": "any_metric",
            "metric_expression": "1=1",
            "domain_id": str(uuid4()),
            "promoted_by": str(uuid4()),
        },
    )
    assert resp.status == 200, await resp.text()


async def test_promote_semantic_gap_non_gap_entry_returns_400(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Entry that isn't a semantic_gap_proposed cycle row → 400."""
    # Seed a non-gap entry (any other write_actions cycle works).
    await memory_ledger.write(
        company_id=_company_id(),
        propose={
            "target_kind": "person_proposed",
            "ref_id": str(uuid4()),
            "reason": "non-gap entry for negative test",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_person_proposed",
            "args": {"name": "x"},
            "result_ref": "x",
        },
        verify_fn=lambda _e: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "x"},
        quadrant="active_deterministic",
    )
    rows = await memory_ledger.fetch(_company_id())
    non_gap_execute_id = str(
        next(r for r in rows if r["kind"] == "execute")["entry_id"],
    )

    resp = await client.post(
        "/api/v1/write_actions/promote_semantic_gap",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "semantic_gap_entry_id": non_gap_execute_id,
            "metric_name": "x",
            "metric_expression": "x",
            "domain_id": str(uuid4()),
            "promoted_by": str(uuid4()),
        },
    )
    assert resp.status == 400, await resp.text()


async def test_promote_semantic_gap_unknown_entry_returns_400(
    client: TestClient,
) -> None:
    """Unknown ledger entry id → 400."""
    resp = await client.post(
        "/api/v1/write_actions/promote_semantic_gap",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "semantic_gap_entry_id": str(uuid4()),  # never written
            "metric_name": "x",
            "metric_expression": "x",
            "domain_id": str(uuid4()),
            "promoted_by": str(uuid4()),
        },
    )
    assert resp.status == 400, await resp.text()
