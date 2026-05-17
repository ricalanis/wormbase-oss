"""v1.1 end-to-end: dashboard server action → worm-core endpoint → ledger entry → readback.

Verifies the 4 stub-now-real endpoints work all the way through. Uses an in-process
worm-core HTTP app (aiohttp test client) + InMemoryLedger seeded with test tenant.
Then re-reads the ledger via the production reader Protocols (LedgerDecisionReader /
LedgerProcessMapReader) and the dashboard accessor analogues to prove the round-trip
closes.

Coverage (≥6 tests):

  1. ``register_agent`` happy path — POST → 200 + agentId; ledger carries
     ``emit_agent_registered`` + 1+ ``emit_agent_grant`` execute rows.
  2. ``import_dbt_catalog`` happy path against jaffle_shop fixture —
     POST → 200 + sourceId; ledger carries ``emit_external_catalog_imported``
     + 1 ``emit_external_lineage_imported`` (8 edges) execute rows.
  3. ``import_snowflake_catalog`` env-gated against a live Snowflake account;
     skips cleanly when ``SNOWFLAKE_*`` env vars missing (CI default).
  4. ``promote_semantic_gap`` round-trip — seed
     ``semantic_gap_proposed``, POST → 200 + metricId, ledger carries
     ``emit_external_metric_imported`` with ``caused_by`` chain to the gap.
  5. Unauthenticated request (missing Bearer token) → 401.
  6. ``decisions.list`` MCP tool returns real ledger rows after the
     ``LedgerDecisionReader`` is wired into ``build_agent_gateway_mcp_server``
     (Part A construction site validation — works against in-memory ledger).
"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from fastmcp import Client as FastMCPClient
from wormbase_agent_gateway.identity import AgentGrant
from wormbase_agent_gateway.mcp_server import (
    GatewayDeps,
    build_agent_gateway_mcp_server,
)
from wormbase_core.agent_gateway_readers import (
    LedgerDecisionReader,
    LedgerProcessMapReader,
)
from wormbase_core.http_api import build_app
from wormbase_core.service import tenant_to_uuid
from wormbase_inference import AgentID, GovernanceContext
from wormbase_ledger import InMemoryLedger

pytestmark = pytest.mark.asyncio

API_TOKEN = "v1-1-rt-token"
TENANT_SLUG = "baseworm"
# jaffle_shop fixture (vendored from the catalog-mirror package); used to
# drive the dbt-manifest import branch with a known-good 8-edge graph.
JAFFLE_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "wormbase-catalog-mirror"
    / "tests"
    / "fixtures"
    / "jaffle_shop_manifest.json"
)


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "X-Tenant-Slug": TENANT_SLUG,
    }


def _company_id() -> UUID:
    return tenant_to_uuid(TENANT_SLUG)


@pytest_asyncio.fixture
async def memory_ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest_asyncio.fixture
async def client(memory_ledger: InMemoryLedger) -> AsyncIterator[TestClient]:
    """Aiohttp test client bound to a fresh InMemoryLedger.

    Mirrors the pattern in apps/worm-core/tests/test_register_agent_endpoint.py
    so the dashboard's PoSTs route through the same handler set the real
    deployment uses.
    """
    app = build_app(ledger=memory_ledger, api_token=API_TOKEN)
    server = TestServer(app)
    cli = TestClient(server)
    await cli.start_server()
    try:
        yield cli
    finally:
        await cli.close()


# ---------------------------------------------------------------------------
# Round-trip 1: register_agent
# ---------------------------------------------------------------------------


async def test_register_agent_round_trip(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Dashboard-style POST → 200 + agentId; ledger carries agent_registered + grant.

    Mirrors the dashboard server action at
    ``apps/dashboard/app/(app)/people/agents/new/actions.ts``: an admin
    role-holder posts an external_provider + display_name +
    domain_read_ids, the endpoint lands ``emit_agent_registered`` followed
    by N ``emit_agent_grant`` PEVR cycles.
    """
    domain_id = uuid4()
    admin_id = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/register_agent",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "external_provider": "claude",
            "display_name": "v1.1 Round-Trip Agent",
            "domain_read_ids": [str(domain_id)],
            "model_access_budget_usd": "12.50",
            "registered_by": str(admin_id),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    # Dashboard expects both snake_case and camelCase keys (round-trip
    # served both for migration window — verified in v1.1 Task 1).
    assert body["agent_id"] == body["agentId"]
    new_agent_id = UUID(body["agent_id"])

    rows = await memory_ledger.fetch(_company_id())
    execute_rows = [r for r in rows if r["kind"] == "execute"]
    tools = [r["payload"]["tool"] for r in execute_rows]
    # 1 register + 2 grants (domain.read + model.access).
    assert tools == [
        "emit_agent_registered",
        "emit_agent_grant",
        "emit_agent_grant",
    ]

    register_args = execute_rows[0]["payload"]["args"]
    assert register_args["external_provider"] == "claude"
    assert register_args["display_name"] == "v1.1 Round-Trip Agent"
    # The agent_id in the args matches the agentId in the response.
    assert UUID(register_args["agent_id"]) == new_agent_id

    # Read-back analog of dashboard accessor getAgents: walk
    # emit_agent_registered rows and find ours.
    seen_agents = [
        r["payload"]["args"]["agent_id"]
        for r in execute_rows
        if r["payload"]["tool"] == "emit_agent_registered"
    ]
    assert str(new_agent_id) in seen_agents


# ---------------------------------------------------------------------------
# Round-trip 2: import_dbt_catalog (jaffle_shop fixture)
# ---------------------------------------------------------------------------


async def test_import_dbt_catalog_round_trip(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Dashboard-style POST against jaffle_shop fixture → 200 + sourceId;
    ledger carries external_catalog_imported + external_lineage_imported
    (8 edges, 8 tables).
    """
    assert JAFFLE_FIXTURE.exists(), f"missing fixture at {JAFFLE_FIXTURE}"
    domain_id = uuid4()
    admin_id = uuid4()

    resp = await client.post(
        "/api/v1/write_actions/import_dbt_catalog",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "manifest_uri": f"file://{JAFFLE_FIXTURE}",
            "domain_id": str(domain_id),
            "imported_by": str(admin_id),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["source_id"] == body["sourceId"]
    new_source_id = UUID(body["source_id"])

    rows = await memory_ledger.fetch(_company_id())
    execute_rows = [r for r in rows if r["kind"] == "execute"]
    tools = [r["payload"]["tool"] for r in execute_rows]
    assert tools[0] == "emit_external_catalog_imported"
    assert tools[1] == "emit_external_lineage_imported"

    catalog_args = execute_rows[0]["payload"]["args"]
    assert catalog_args["source_kind"] == "dbt"
    assert catalog_args["import_mode"] == "initial"
    assert catalog_args["edge_count"] == 8
    assert catalog_args["table_count"] == 8
    assert catalog_args["domain_id"] == str(domain_id)
    # source_id round-trip: response sourceId matches the args
    assert str(new_source_id) == catalog_args["source_id"]

    # Read-back analog of dashboard accessor getCatalogTables: walk
    # emit_external_catalog_imported rows and confirm jaffle_shop landed.
    lineage_args = execute_rows[1]["payload"]["args"]
    assert len(lineage_args["edges"]) == 8


# ---------------------------------------------------------------------------
# Round-trip 3: import_snowflake_catalog — env-gated live
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not all(
        os.environ.get(k)
        for k in (
            "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_WAREHOUSE",
            "SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA",
        )
    ),
    reason=(
        "live Snowflake round-trip — requires SNOWFLAKE_ACCOUNT / USER / "
        "WAREHOUSE / DATABASE / SCHEMA env vars + a password OR token "
        "wired through the CredentialBroker. Skips cleanly in CI / dev."
    ),
)
async def test_import_snowflake_catalog_round_trip_live(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Live round-trip against a real Snowflake account.

    Skipped by default. Set ``SNOWFLAKE_*`` env vars to exercise the
    full path through ``SnowflakeNativeCatalogSource``. Asserts the
    response contains a sourceId and the ledger carries the canonical
    chain (external_catalog_imported + N lineage entries).
    """
    domain_id = uuid4()
    admin_id = uuid4()

    body_payload: dict[str, str] = {
        "company_id": str(_company_id()),
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        "warehouse": os.environ["SNOWFLAKE_WAREHOUSE"],
        "database": os.environ["SNOWFLAKE_DATABASE"],
        "schema": os.environ["SNOWFLAKE_SCHEMA"],
        "domain_id": str(domain_id),
        "imported_by": str(admin_id),
    }
    if os.environ.get("SNOWFLAKE_ROLE"):
        body_payload["role"] = os.environ["SNOWFLAKE_ROLE"]

    resp = await client.post(
        "/api/v1/write_actions/import_snowflake_catalog",
        headers=_auth_headers(),
        json=body_payload,
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert UUID(body["source_id"])
    assert body["source_id"] == body["sourceId"]

    rows = await memory_ledger.fetch(_company_id())
    execute_rows = [r for r in rows if r["kind"] == "execute"]
    tools = [r["payload"]["tool"] for r in execute_rows]
    assert tools[0] == "emit_external_catalog_imported"
    primary_args = execute_rows[0]["payload"]["args"]
    assert primary_args["source_kind"] == "snowflake"


# ---------------------------------------------------------------------------
# Round-trip 4: promote_semantic_gap
# ---------------------------------------------------------------------------


async def _seed_semantic_gap(memory_ledger: InMemoryLedger) -> str:
    """Write a semantic_gap_proposed PEVR cycle; return the execute entry id.

    Mirrors apps/worm-core/tests/test_promote_semantic_gap_endpoint.py
    so the round-trip test exercises the same gap-seed shape the
    dashboard's /lake/metrics-proposed admin queue surfaces.
    """
    agent_id = uuid4()
    await memory_ledger.write(
        company_id=_company_id(),
        propose={
            "target_kind": "semantic_gap_proposed",
            "ref_id": str(agent_id),
            "reason": "v1.1 round-trip: agent cannot find a matching metric",
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
            "rationale": "gap seeded for round-trip test",
        },
        quadrant="active_deterministic",
    )
    rows = await memory_ledger.fetch(_company_id())
    execute_rows = [r for r in rows if r["kind"] == "execute"]
    return str(execute_rows[0]["entry_id"])


async def test_promote_semantic_gap_round_trip(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Seed gap → POST promote → external_metric_imported lands with caused_by.

    Read-back analog of getSemanticGaps: the gap entry is now resolved
    because a later ``emit_external_metric_imported`` row carries
    ``promoted_from_gap_id == gap_entry_id``.
    """
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
    propose_rows = [r for r in rows if r["kind"] == "propose"]
    # The most-recent propose is the metric-import propose with caused_by.
    metric_propose = propose_rows[-1]
    assert metric_propose["payload"]["target_kind"] == "external_metric_imported"
    assert metric_propose["payload"]["caused_by"] == gap_entry_id

    execute_rows = [r for r in rows if r["kind"] == "execute"]
    metric_execute = execute_rows[-1]
    assert metric_execute["payload"]["tool"] == "emit_external_metric_imported"
    metric_args = metric_execute["payload"]["args"]
    assert metric_args["promoted_from_gap_id"] == gap_entry_id
    assert metric_args["name"] == "net_revenue_quarterly"

    # Read-back: gaps the dashboard would render as "resolved" — i.e.
    # any semantic_gap_proposed row that has a downstream
    # external_metric_imported with promoted_from_gap_id matching.
    gap_ids_seen_as_resolved = {
        r["payload"]["args"]["promoted_from_gap_id"]
        for r in execute_rows
        if r["payload"]["tool"] == "emit_external_metric_imported"
    }
    assert gap_entry_id in gap_ids_seen_as_resolved


# ---------------------------------------------------------------------------
# Auth: unauthenticated request returns 401
# ---------------------------------------------------------------------------


async def test_unauthenticated_request_returns_401(client: TestClient) -> None:
    """Missing Bearer token on any of the 4 endpoints → 401, not 500.

    The dashboard always sends a Bearer header; this test pins the
    refusal contract so an in-the-clear request from elsewhere fails
    fast with an actionable status (not a server-side trace).
    """
    resp = await client.post(
        "/api/v1/write_actions/register_agent",
        headers={
            # No Authorization header — only the tenant slug.
            "X-Tenant-Slug": TENANT_SLUG,
        },
        json={
            "company_id": str(_company_id()),
            "external_provider": "claude",
            "display_name": "Anon",
            "domain_read_ids": [],
            "model_access_budget_usd": None,
            "registered_by": str(uuid4()),
        },
    )
    assert resp.status == 401, await resp.text()


# ---------------------------------------------------------------------------
# Round-trip 6: MCP decisions.list uses LedgerDecisionReader after wireup
# ---------------------------------------------------------------------------


async def _emit_decision(
    memory_ledger: InMemoryLedger,
    *,
    decision_text: str,
    domain_id: str | None = None,
) -> str:
    """Write an emit_decision_recorded PEVR cycle. Returns the decision_id."""
    decision_id = str(uuid4())
    args: dict = {
        "decision_id": decision_id,
        "decision_text": decision_text,
        "decision_at": datetime.now(UTC).isoformat(),
        "channel_id": "C-rt-test",
        "decided_by_persons": [str(uuid4())],
        "evidence_message_ids": ["msg-rt-1"],
        "confidence": 0.9,
    }
    if domain_id is not None:
        args["domain_id"] = domain_id

    await memory_ledger.write(
        company_id=_company_id(),
        propose={
            "target_kind": "decision_recorded",
            "ref_id": decision_id,
            "reason": "round-trip-test decision seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_decision_recorded",
            "args": args,
            "result_ref": decision_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seeded"},
        quadrant="active_deterministic",
    )
    return decision_id


def _stub_gateway_deps(
    *,
    ledger: InMemoryLedger,
    company_id: UUID,
) -> GatewayDeps:
    """Build a GatewayDeps wired with the v1.1 production readers.

    Mirrors what ``cli.py``'s gateway-construction site will pass at boot:
    LedgerDecisionReader + LedgerProcessMapReader (productionizable from
    the Ledger alone). The remaining deps (CatalogClient, CatalogReader,
    BrokerExecutor, FederateIssuer, etc.) are stubbed for this test —
    they don't participate in ``decisions.list``.

    The intent of this test is to prove that once Part A's construction
    site composes ``build_agent_gateway_mcp_server`` with the
    ledger-backed readers, a ``decisions.list`` MCP call returns real
    ledger rows (not the no-op stub rows the test-default stubs return).
    """

    class _StubCatalogClient:
        async def get_metric(self, name: str):
            return None

        async def get_table(self, external_id: str):
            return None

        async def list_tables(self):
            return []

    class _StubCatalogReader:
        async def list_tables(self, *, company_id, filter):
            return []

        async def list_lineage(self, *, company_id, resource_id, direction):
            return []

        async def get_resource_classification(self, resource_id: str):
            return None

    class _StubBrokerExecutor:
        async def execute(self, **_kwargs):  # pragma: no cover — unused
            raise NotImplementedError

    class _StubFederateIssuer:
        async def issue(self, **_kwargs):  # pragma: no cover — unused
            raise NotImplementedError

    agent_value = "rt-test-agent"
    aid = AgentID(value=agent_value)
    grants = [
        AgentGrant(
            id=str(uuid4()),
            agent_id=agent_value,
            grant_kind="domain.read",
            grant_target="*",
            status="active",
            granted_by="rt-test",
            granted_at=datetime.now(UTC),
        ),
    ]

    async def _grant_lookup(_a: AgentID):
        return grants

    async def _agent_resolver() -> AgentID:
        return aid

    async def _governance_resolver(_a: AgentID) -> GovernanceContext:
        return GovernanceContext(
            classification_ceiling="internal",  # type: ignore[arg-type]
            cost_budget_usd=Decimal("1.00"),
            pii_redaction=True,
            domain_id=None,
        )

    return GatewayDeps(
        ledger=ledger,
        company_id=company_id,
        install_id="rt-test-install",
        catalog_client=_StubCatalogClient(),
        catalog_reader=_StubCatalogReader(),
        broker_executor=_StubBrokerExecutor(),
        federate_issuer=_StubFederateIssuer(),
        grant_lookup=_grant_lookup,
        agent_id_resolver=_agent_resolver,
        governance_resolver=_governance_resolver,
        router=None,
        decision_reader=LedgerDecisionReader(ledger=ledger),
        process_map_reader=LedgerProcessMapReader(ledger=ledger),
        # data_product_reader stays None — v1.1 carries no production
        # impl yet (flagged as a v1.2 follow-up in Part A docs). The
        # _EmptyDataProductReader fallback installs automatically.
        data_product_reader=None,
    )


async def test_mcp_decisions_list_uses_ledger_reader_after_wireup(
    memory_ledger: InMemoryLedger,
) -> None:
    """Once Part A wires LedgerDecisionReader into build_agent_gateway_mcp_server,
    a decisions.list call returns real rows from the ledger (not stub rows).

    Construct the gateway server with the v1.1 production readers + an
    in-memory ledger seeded with a real emit_decision_recorded entry.
    The MCP tool should return that decision (verifying the reader is
    actually consulted by the running tool, not the no-op fallback).
    """
    company_id = _company_id()
    seeded_id = await _emit_decision(
        memory_ledger,
        decision_text="v1.1 round-trip: defer Q4 audit to Jan",
    )

    deps = _stub_gateway_deps(ledger=memory_ledger, company_id=company_id)
    server = build_agent_gateway_mcp_server(deps)
    async with FastMCPClient(server.mcp) as fmc:
        result = await fmc.call_tool("decisions.list", {"limit": 10})

    assert not result.is_error, f"decisions.list failed: {result}"
    # FastMCP wraps union-return-type tools as ``{"result": {...}}`` in
    # ``structured_content``; non-union returns are flat dicts. Mirror
    # the helper at packages/wormbase-agent-gateway/tests/integration/_helpers.py
    # so this test stays robust to the return-shape choice.
    sc = result.structured_content
    if sc is None:
        if getattr(result, "data", None) is not None:
            try:
                data = result.data.model_dump()
            except AttributeError:
                data = dict(result.data)
        else:
            text_payload = result.content[0].text  # type: ignore[index]
            data = json.loads(text_payload)
    elif isinstance(sc, dict) and set(sc.keys()) == {"result"}:
        data = sc["result"]
    else:
        data = sc

    decisions = data["decisions"]
    assert any(
        d["decision_id"] == seeded_id for d in decisions
    ), (
        f"decisions.list did not surface the seeded ledger row "
        f"{seeded_id!r}; got {[d['decision_id'] for d in decisions]}. "
        "If this fails, build_agent_gateway_mcp_server is using the "
        "_EmptyDecisionReader fallback — the LedgerDecisionReader was "
        "NOT wired through GatewayDeps."
    )
