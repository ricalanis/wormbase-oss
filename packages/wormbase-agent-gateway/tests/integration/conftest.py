"""Shared fixtures for agent-gateway MCP integration tests.

Provides:

- `InMemoryLedger` factory
- `EnvCredentialBroker` factory (seeded with a dummy snowflake account)
- `StubCatalogClient` carrying a fixture metric + a fixture table
- `StubCatalogReader` for projection_external_catalog / lineage reads
- `StubBrokerExecutor` driver that returns canned rows
- `gateway_deps_factory` — builds a GatewayDeps with all stubs wired
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Sequence
from uuid import UUID, uuid4

import pytest
from wormbase_inference import AgentID, GovernanceContext
from wormbase_ledger import InMemoryLedger

from wormbase_agent_gateway.credential_broker import (
    EnvCredentialBroker,
)
from wormbase_agent_gateway.identity import AgentGrant
from wormbase_agent_gateway.mcp_server import GatewayDeps
from wormbase_agent_gateway.router_query import BrokerExecutor, FederateIssuer


# ---------------------------------------------------------------------------
# CatalogClient stub
# ---------------------------------------------------------------------------


@dataclass
class StubCatalogClient:
    """In-memory CatalogClient — seeded by tests with metrics + tables."""

    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def get_metric(self, name: str) -> dict[str, Any] | None:
        return self.metrics.get(name)

    async def get_table(self, external_id: str) -> dict[str, Any] | None:
        return self.tables.get(external_id)

    async def list_tables(self) -> list[dict[str, Any]]:
        return list(self.tables.values())


# ---------------------------------------------------------------------------
# CatalogReader stub
# ---------------------------------------------------------------------------


@dataclass
class StubCatalogReader:
    """In-memory projection_external_catalog / _lineage reader."""

    catalog_rows: list[dict[str, Any]] = field(default_factory=list)
    lineage_rows: list[dict[str, Any]] = field(default_factory=list)
    classifications: dict[str, str] = field(default_factory=dict)

    async def list_tables(
        self, *, company_id: UUID, filter: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        rows = list(self.catalog_rows)
        if filter:
            kind = filter.get("source_kind")
            sid = filter.get("source_id")
            if kind is not None:
                rows = [r for r in rows if r.get("source_kind") == kind]
            if sid is not None:
                rows = [r for r in rows if str(r.get("source_id")) == str(sid)]
        return rows

    async def list_lineage(
        self,
        *,
        company_id: UUID,
        resource_id: str,
        direction: Literal["upstream", "downstream", "both"],
    ) -> list[dict[str, Any]]:
        if direction == "upstream":
            return [
                e for e in self.lineage_rows
                if e.get("downstream") == resource_id
            ]
        if direction == "downstream":
            return [
                e for e in self.lineage_rows
                if e.get("upstream") == resource_id
            ]
        return [
            e for e in self.lineage_rows
            if e.get("upstream") == resource_id
            or e.get("downstream") == resource_id
        ]

    async def get_resource_classification(self, resource_id: str) -> str | None:
        return self.classifications.get(resource_id)


# ---------------------------------------------------------------------------
# Gold-artifact reader stubs (Wave 3.2 Hole #3)
# ---------------------------------------------------------------------------


@dataclass
class StubDecisionReader:
    """In-memory decision_recorded reader.

    Tests seed ``rows`` with dicts shaped like the
    ``DecisionRecordedPayload`` schema (decision_id, decision_text,
    decision_at, channel_id, decided_by_persons, evidence_message_ids,
    confidence). Optional ``domain_id`` is honored by ``list``.
    """

    rows: list[dict[str, Any]] = field(default_factory=list)

    async def list_decisions(
        self, *, company_id: UUID, domain_id: str | None, limit: int,
    ) -> list[dict[str, Any]]:
        out = list(self.rows)
        if domain_id is not None:
            out = [r for r in out if r.get("domain_id") == domain_id]
        return out[:limit]

    async def get_decision(
        self, *, company_id: UUID, decision_id: str,
    ) -> dict[str, Any] | None:
        for r in self.rows:
            if str(r.get("decision_id")) == decision_id:
                return r
        return None

    async def search_decisions(
        self, *, company_id: UUID, nl_question: str, limit: int,
    ) -> list[dict[str, Any]]:
        q = (nl_question or "").lower()
        out = [
            r for r in self.rows
            if q in str(r.get("decision_text", "")).lower()
        ]
        return out[:limit]


@dataclass
class StubProcessMapReader:
    """In-memory process_map_proposed reader."""

    rows: list[dict[str, Any]] = field(default_factory=list)

    async def list_process_maps(
        self, *, company_id: UUID, domain_id: str | None, limit: int,
    ) -> list[dict[str, Any]]:
        out = list(self.rows)
        if domain_id is not None:
            out = [r for r in out if r.get("domain_id") == domain_id]
        return out[:limit]

    async def get_process_map(
        self, *, company_id: UUID, process_map_id: str,
    ) -> dict[str, Any] | None:
        for r in self.rows:
            if str(r.get("process_id")) == process_map_id:
                return r
        return None


@dataclass
class StubDataProductReader:
    """In-memory projection_data_products reader."""

    rows: list[dict[str, Any]] = field(default_factory=list)

    async def list_data_products(
        self,
        *,
        company_id: UUID,
        domain_id: str | None,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        out = list(self.rows)
        if domain_id is not None:
            out = [r for r in out if str(r.get("domain_id") or "") == domain_id]
        if status is not None:
            out = [r for r in out if r.get("status") == status]
        return out[:limit]

    async def get_data_product(
        self, *, company_id: UUID, data_product_id: str,
    ) -> dict[str, Any] | None:
        for r in self.rows:
            if str(r.get("data_product_id")) == data_product_id:
                return r
        return None


# ---------------------------------------------------------------------------
# Driver stub — runs alongside BrokerExecutor
# ---------------------------------------------------------------------------


@dataclass
class StubSnowflakeDriver:
    """Returns canned rows for any (account, sql, params) call.

    Tests reach in and set ``rows`` to control the response. The
    driver does not interpret SQL — it just returns what's been seeded.
    """

    rows: list[dict[str, Any]] = field(default_factory=list)
    last_call: dict[str, Any] | None = None

    async def query(
        self,
        *,
        account: dict[str, Any],
        sql: str,
        params: list[Any],
    ) -> list[dict[str, Any]]:
        self.last_call = {"account": account, "sql": sql, "params": params}
        return list(self.rows)


# ---------------------------------------------------------------------------
# Fixture factory
# ---------------------------------------------------------------------------


@dataclass
class GatewayHarness:
    """Bundle returned by the gateway_deps_factory fixture.

    Tests reach for sub-fields to seed catalogs + driver rows + grants
    before calling the MCP tools.
    """

    deps: GatewayDeps
    ledger: InMemoryLedger
    broker: EnvCredentialBroker
    catalog_client: StubCatalogClient
    catalog_reader: StubCatalogReader
    driver: StubSnowflakeDriver
    grants_by_agent: dict[str, list[AgentGrant]]
    agent_id: AgentID
    # Wave 3.2 Hole #3 — gold-artifact readers
    decision_reader: "StubDecisionReader"
    process_map_reader: "StubProcessMapReader"
    data_product_reader: "StubDataProductReader"


@pytest.fixture
def gateway_deps_factory(tmp_path: Path):
    """Returns a callable that builds a GatewayHarness with optional overrides."""

    def _factory(
        *,
        company_id: UUID | None = None,
        install_id: str = "install-test",
        agent_id_value: str = "test-agent",
        grants: Sequence[AgentGrant] | None = None,
        classification_ceiling: str = "internal",
    ) -> GatewayHarness:
        cid = company_id or UUID("00000000-0000-0000-0000-000000000123")
        ledger = InMemoryLedger()

        secrets = tmp_path / "secrets"
        broker = EnvCredentialBroker(secrets_dir=secrets)
        # Seed a dummy snowflake account so BrokerExecutor.hold_data_account succeeds.
        secret_path = secrets / "data" / "snowflake" / install_id
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        secret_path.write_text(json.dumps({"account": "stub", "user": "stub"}))

        catalog_client = StubCatalogClient()
        catalog_reader = StubCatalogReader()
        driver = StubSnowflakeDriver()
        executor = BrokerExecutor(broker=broker, install_id=install_id, driver=driver)
        federate = FederateIssuer(broker=broker)
        decision_reader = StubDecisionReader()
        process_map_reader = StubProcessMapReader()
        data_product_reader = StubDataProductReader()

        agent_id = AgentID(value=agent_id_value)
        grant_list: list[AgentGrant] = list(grants) if grants is not None else [
            # default: domain.read grant + a model.access grant with budget
            AgentGrant(
                id=str(uuid4()),
                agent_id=agent_id_value,
                grant_kind="domain.read",
                grant_target="00000000-0000-0000-0000-000000000aaa",
                status="active",
                granted_by="admin",
                granted_at=datetime.now(UTC),
            ),
            AgentGrant(
                id=str(uuid4()),
                agent_id=agent_id_value,
                grant_kind="model.access",
                grant_target="kimi",
                status="active",
                granted_by="admin",
                granted_at=datetime.now(UTC),
                budget_remaining_usd=Decimal("10.00"),
            ),
        ]
        grants_by_agent: dict[str, list[AgentGrant]] = {agent_id_value: grant_list}

        async def _grant_lookup(aid: AgentID) -> list[AgentGrant]:
            return grants_by_agent.get(aid.value, [])

        async def _agent_resolver() -> AgentID:
            return agent_id

        async def _governance_resolver(_a: AgentID) -> GovernanceContext:
            return GovernanceContext(
                classification_ceiling=classification_ceiling,  # type: ignore[arg-type]
                cost_budget_usd=Decimal("10.00"),
                pii_redaction=True,
                domain_id=None,
            )

        deps = GatewayDeps(
            ledger=ledger,
            company_id=cid,
            install_id=install_id,
            catalog_client=catalog_client,
            catalog_reader=catalog_reader,
            broker_executor=executor,
            federate_issuer=federate,
            grant_lookup=_grant_lookup,
            agent_id_resolver=_agent_resolver,
            governance_resolver=_governance_resolver,
            router=None,
            decision_reader=decision_reader,
            process_map_reader=process_map_reader,
            data_product_reader=data_product_reader,
        )
        return GatewayHarness(
            deps=deps,
            ledger=ledger,
            broker=broker,
            catalog_client=catalog_client,
            catalog_reader=catalog_reader,
            driver=driver,
            grants_by_agent=grants_by_agent,
            agent_id=agent_id,
            decision_reader=decision_reader,
            process_map_reader=process_map_reader,
            data_product_reader=data_product_reader,
        )

    return _factory
