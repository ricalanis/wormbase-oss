"""Tests for v1.2 Task 2 production wire-ups in agent_gateway_construction.

Three items, three test groups:

  * Item #1 — CredentialBroker wired when env knobs are set; real
    ``BrokerExecutor`` + ``FederateIssuer`` flow through ``GatewayDeps``.
  * Item #2 — Stateful gate bundle wired when the 4 governance gates
    are passed to ``run_agent_gateway_build_smoke``; the chain composes
    inline + stateful gates.
  * Item #3 — ``data_products.list`` returns rows from a
    ``LedgerDataProductReader`` after wire-up.

Item #3 is the integration test: seed three data products via the
ledger, call the MCP tool through the FastMCP client, assert the tool
returns the seeded rows. This is the equivalent of v1.1 Task 6's
end-to-end round trip for the new ``data_products.*`` MCP surface.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastmcp import Client
from wormbase_agent_gateway.governance import StatefulGateBundle
from wormbase_agent_gateway.identity import AgentGrant
from wormbase_core.agent_gateway_construction import (
    _NotYetProductionBrokerExecutor,
    _NotYetProductionFederateIssuer,
    compose_production_agent_gateway_deps,
    run_agent_gateway_build_smoke,
)
from wormbase_governance import (
    InterjectionGate,
    KnowledgeGate,
    PIIGate,
    WarmupGate,
)
from wormbase_inference import AgentID, GovernanceContext
from wormbase_ledger import InMemoryLedger
from wormbase_ontology_seed import Loader

TEST_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000abc")


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


def _verify_pass(_e: dict[str, Any]) -> dict[str, Any]:
    return {"checks": [], "passed": True}


def _resolve_keep(_v: dict[str, Any]) -> dict[str, Any]:
    return {"outcome": "keep", "rationale": "ok"}


def _make_gates(
    ledger: InMemoryLedger,
    company_id: UUID,
) -> tuple[PIIGate, WarmupGate, InterjectionGate, KnowledgeGate]:
    """Construct the 4 stateful gates the same way ``build_worm_core`` does.

    Mirrors apps/worm-core/src/wormbase_core/service.py lines 129-143
    so the test reflects the production composition exactly.
    """
    seed_loader = Loader()
    pii = PIIGate(ledger, company_id, seed_loader)
    interjection = InterjectionGate(ledger, company_id)
    knowledge = KnowledgeGate(
        ontology_concepts=[],
        confirmed_concepts=[],
        ledger=ledger,
        company_id=company_id,
    )

    async def _ramp_reader(_cid: UUID) -> dict[str, Any]:
        # Match WormCore's wormbase_core.ramp output shape minimally.
        return {"schema_axis": 1.0, "concept_axis": 1.0}

    warmup = WarmupGate(_ramp_reader, ledger, company_id)
    return pii, warmup, interjection, knowledge


async def _emit_dp_proposed(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    data_product_id: UUID,
    name: str,
) -> None:
    args = {
        "data_product_id": str(data_product_id),
        "name": name,
        "kind": "report",
        "requested_by_person_id": str(uuid4()),
        "sources_required": [],
        "parameters": {},
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "data_product_proposed",
            "ref_id": str(data_product_id),
            "reason": f"propose {name!r}",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_data_product_proposed",
            "args": args,
            "result_ref": str(data_product_id),
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


# ---------------------------------------------------------------------------
# Item #1 — CredentialBroker wire-up
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateway_construction_no_broker_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no broker env knob set, no-op broker stubs ship."""
    monkeypatch.delenv("WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR", raising=False)
    monkeypatch.delenv("WORMBASE_AGENT_GATEWAY_BROKER_KIND", raising=False)
    ledger = InMemoryLedger()
    deps = compose_production_agent_gateway_deps(
        ledger=ledger,
        company_id=TEST_COMPANY_ID,
        install_id=str(TEST_COMPANY_ID),
    )
    assert isinstance(deps.broker_executor, _NotYetProductionBrokerExecutor)
    assert isinstance(deps.federate_issuer, _NotYetProductionFederateIssuer)


@pytest.mark.asyncio
async def test_gateway_construction_includes_real_credential_broker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With ``WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR`` set, broker_executor +
    federate_issuer are real instances backed by an EnvCredentialBroker.
    """
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    monkeypatch.setenv(
        "WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR", str(secrets_dir),
    )
    monkeypatch.setenv("WORMBASE_AGENT_GATEWAY_BROKER_KIND", "env")
    ledger = InMemoryLedger()

    deps = compose_production_agent_gateway_deps(
        ledger=ledger,
        company_id=TEST_COMPANY_ID,
        install_id=str(TEST_COMPANY_ID),
    )

    # Real BrokerExecutor + FederateIssuer (not the stubs)
    from wormbase_agent_gateway.router_query import (
        BrokerExecutor,
        FederateIssuer,
    )
    assert isinstance(deps.broker_executor, BrokerExecutor)
    assert isinstance(deps.federate_issuer, FederateIssuer)
    # The broker is the file-backed EnvCredentialBroker
    from wormbase_agent_gateway.credential_broker.env import (
        EnvCredentialBroker,
    )
    assert isinstance(deps.broker_executor.broker, EnvCredentialBroker)


@pytest.mark.asyncio
async def test_gateway_construction_unknown_broker_kind_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown broker kind logs a warning and ships the no-op stubs."""
    monkeypatch.setenv("WORMBASE_AGENT_GATEWAY_BROKER_KIND", "bogus")
    monkeypatch.delenv("WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR", raising=False)
    ledger = InMemoryLedger()
    deps = compose_production_agent_gateway_deps(
        ledger=ledger,
        company_id=TEST_COMPANY_ID,
        install_id=str(TEST_COMPANY_ID),
    )
    assert isinstance(deps.broker_executor, _NotYetProductionBrokerExecutor)


# ---------------------------------------------------------------------------
# Item #2 — Stateful gate bundle wire-up
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateway_construction_no_stateful_when_gates_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without governance gates, ``stateful_gate_bundle`` stays None."""
    monkeypatch.delenv("WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR", raising=False)
    ledger = InMemoryLedger()
    deps = compose_production_agent_gateway_deps(
        ledger=ledger,
        company_id=TEST_COMPANY_ID,
        install_id=str(TEST_COMPANY_ID),
    )
    assert deps.stateful_gate_bundle is None


@pytest.mark.asyncio
async def test_gateway_construction_includes_stateful_gate_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All 4 gates provided → bundle threaded through ``GatewayDeps``."""
    monkeypatch.delenv("WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR", raising=False)
    ledger = InMemoryLedger()
    pii, warmup, interjection, knowledge = _make_gates(
        ledger, TEST_COMPANY_ID,
    )

    deps = compose_production_agent_gateway_deps(
        ledger=ledger,
        company_id=TEST_COMPANY_ID,
        install_id=str(TEST_COMPANY_ID),
        pii_gate=pii,
        warmup_gate=warmup,
        interjection_gate=interjection,
        knowledge_gate=knowledge,
    )
    assert deps.stateful_gate_bundle is not None
    assert isinstance(deps.stateful_gate_bundle, StatefulGateBundle)


@pytest.mark.asyncio
async def test_build_smoke_reports_stateful_gates_wired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The smoke result reports stateful_gates_wired=True when gates flow."""
    monkeypatch.delenv("WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR", raising=False)
    ledger = InMemoryLedger()
    pii, warmup, interjection, knowledge = _make_gates(
        ledger, TEST_COMPANY_ID,
    )

    result = run_agent_gateway_build_smoke(
        ledger=ledger,
        company_id=TEST_COMPANY_ID,
        install_id=str(TEST_COMPANY_ID),
        pii_gate=pii,
        warmup_gate=warmup,
        interjection_gate=interjection,
        knowledge_gate=knowledge,
    )
    assert result.production_readers_wired is True
    assert result.stateful_gates_wired is True
    # gate chain on the server has the bundle attached
    assert result.server.gate_chain.stateful is not None
    # pending list no longer includes stateful_gate_bundle
    assert "stateful_gate_bundle" not in result.pending_deps


# ---------------------------------------------------------------------------
# Item #3 — LedgerDataProductReader end-to-end via data_products.list MCP tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_products_list_returns_real_rows_via_ledger_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seed two emit_data_product_proposed entries; ``data_products.list``
    returns them via the wired ``LedgerDataProductReader``.

    This proves the v1.2 Item #3 wire-up replaces the v1.1
    _EmptyDataProductReader fallback.
    """
    monkeypatch.delenv("WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR", raising=False)
    ledger = InMemoryLedger()
    dp_a = uuid4()
    dp_b = uuid4()
    await _emit_dp_proposed(
        ledger, company_id=TEST_COMPANY_ID,
        data_product_id=dp_a, name="DP A",
    )
    await _emit_dp_proposed(
        ledger, company_id=TEST_COMPANY_ID,
        data_product_id=dp_b, name="DP B",
    )

    # Build a permissive grant_lookup + resolvers so the MCP gate chain
    # admits the test agent. We replace the empty grant lookup the
    # construction site ships (which intentionally denies every call
    # until v1.3 wires projection_agent_grants).
    deps = compose_production_agent_gateway_deps(
        ledger=ledger,
        company_id=TEST_COMPANY_ID,
        install_id=str(TEST_COMPANY_ID),
    )

    test_agent = AgentID(value="test-agent-v1-2")

    async def _grant_lookup(_a: AgentID) -> list[AgentGrant]:
        # AgentAccessGate accepts any active ``domain.read`` /
        # ``resource.read`` / ``resource.maintainer`` grant for the new
        # gold-artifact MCP tools (see _TOOL_GRANT_KINDS in governance.py).
        return [
            AgentGrant(
                id=str(uuid4()),
                agent_id=test_agent.value,
                grant_kind="domain.read",
                grant_target="*",
                status="active",
                granted_by="test",
                granted_at=datetime.now(UTC),
            ),
        ]

    async def _agent_id_resolver() -> AgentID:
        return test_agent

    async def _governance_resolver(_a: AgentID) -> GovernanceContext:
        return GovernanceContext(
            classification_ceiling="confidential",  # type: ignore[arg-type]
            cost_budget_usd=Decimal("100.00"),
            pii_redaction=True,
            domain_id=None,
        )

    # Rebuild deps with permissive grants — the construction site
    # exports the wiring shape, this test overrides only the security
    # surfaces. The data_product_reader stays as the real
    # LedgerDataProductReader from compose_production_agent_gateway_deps.
    from dataclasses import replace
    permissive_deps = replace(
        deps,
        grant_lookup=_grant_lookup,
        agent_id_resolver=_agent_id_resolver,
        governance_resolver=_governance_resolver,
    )

    from wormbase_agent_gateway.mcp_server import (
        build_agent_gateway_mcp_server,
    )
    server = build_agent_gateway_mcp_server(permissive_deps)

    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "data_products.list",
            {"domain_id": None, "status": None, "limit": 50},
        )

    # The MCP response is a structured pydantic model serialized over the
    # fastmcp transport. fastmcp returns a CallToolResult — pull the
    # structured content via ``.data`` or ``.structured_content``.
    data = result.data if hasattr(result, "data") else result.structured_content
    # Either pydantic model or dict — normalize.
    if hasattr(data, "data_products"):
        rows = data.data_products
        row_count = data.row_count
    else:
        rows = data["data_products"]
        row_count = data["row_count"]
    assert row_count == 2, f"expected 2 rows, got {row_count}: {rows}"
    seen_ids = {
        (r.data_product_id if hasattr(r, "data_product_id") else r["data_product_id"])
        for r in rows
    }
    assert seen_ids == {str(dp_a), str(dp_b)}
