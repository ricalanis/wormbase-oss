"""Production gateway-construction site for the agent-gateway MCP server.

v1.1 Task 6 (Part A) closed the gap between
``build_agent_gateway_mcp_server`` and the worm-core boot path. v1.2
Task 2 lifted the in-test deps construction into the live boot
wire-up. v1.3 Task 1 ships three production-operationalization
follow-ups: a real :class:`LedgerAgentGrantReader` for
``grant_lookup``, a runtime MCP listener (stdio default; HTTP opt-in
for single-tenant deployments), and a Vault-first default for the
credential broker when ``VAULT_ADDR`` + ``VAULT_TOKEN`` are present in
the environment.

Design — graduated readiness (post-v1.3)
----------------------------------------

The 17-tool MCP surface composes from these deps:

  * ``ledger`` + ``company_id``       — productionizable today
  * ``decision_reader``               — productionizable today
    (``LedgerDecisionReader`` — v1.1 Task 2)
  * ``process_map_reader``            — productionizable today
    (``LedgerProcessMapReader`` — v1.1 Task 3)
  * ``data_product_reader``           — productionizable today
    (``LedgerDataProductReader`` — v1.2 Task 2 Item #3)
  * ``broker_executor`` + ``federate_issuer``
                                       — productionizable today via
    ``EnvCredentialBroker`` OR ``VaultCredentialBroker``. v1.3 inverts
    the default: when ``VAULT_ADDR`` + ``VAULT_TOKEN`` are set and the
    broker-kind env knob is unset, Vault is used; an explicit
    ``WORMBASE_AGENT_GATEWAY_BROKER_KIND`` always wins.
  * ``stateful`` gate bundle          — productionizable today
    (v1.2 Task 2 Item #2; reuses ``WormCore``'s already-constructed
    PIIGate / WarmupGate / InterjectionGate / KnowledgeGate)
  * ``grant_lookup``                  — productionizable today
    (``LedgerAgentGrantReader`` — v1.3 Task 1 follow-up #1)
  * ``catalog_client``                — NOT productionizable today
    (no production ``CatalogClient`` — projection-mirror only)
  * ``catalog_reader``                — NOT productionizable today
    (projection table walker — v1.3 follow-up #4)
  * ``agent_id_resolver``             — NOT productionizable today
    (requires HTTP transport / Authorization-header parsing)
  * ``governance_resolver``           — NOT productionizable today
    (requires per-install classification ceiling lookup)

This module exposes :func:`compose_production_agent_gateway_deps`, which
returns a ``GatewayDeps`` with the productionizable readers + broker +
stateful gate bundle + grant reader wired and no-op stubs for the
remaining slots, and :func:`run_agent_gateway_mcp_listener`, which
binds a runtime listener after the boot-time build smoke completes.

Production deployment expectations (v1.3)
-----------------------------------------

* For Claude Desktop and other local-MCP-client integrations the worm
  ships ``WORMBASE_AGENT_GATEWAY_MCP_TRANSPORT=stdio`` (default).
* For hosted single-tenant deployments set
  ``WORMBASE_AGENT_GATEWAY_MCP_TRANSPORT=http`` + an explicit
  ``WORMBASE_AGENT_GATEWAY_MCP_PORT`` (default 8911). HTTP transport
  defaults to single-tenant: the listener binds to ONE company_id
  (the boot-time ``install_id``) and trusts the local network
  perimeter.
* For multi-tenant SaaS deployments add
  ``WORMBASE_MULTI_TENANT_MCP=true`` (Path 4, 2026-05-21). The
  HTTP listener then resolves the inbound ``X-Tenant-Slug`` header
  per request via the :class:`TenantRouter` and enforces per-tenant
  rate-limits + 24h quotas. Default OFF preserves byte-identical
  single-tenant behavior. Deploy behind an authenticating reverse
  proxy for any non-trusted ingress.
* Vault is the production-default credential broker when
  ``VAULT_ADDR`` + ``VAULT_TOKEN`` are set. An explicit
  ``WORMBASE_AGENT_GATEWAY_BROKER_KIND`` always wins.

Env knobs
---------

* ``WORMBASE_AGENT_GATEWAY_MCP_BUILD_SMOKE`` — default ``"1"``; toggle
  the boot-time build smoke.

* ``WORMBASE_AGENT_GATEWAY_BROKER_KIND`` — ``"env" | "vault"``;
  unset → Vault if ``VAULT_ADDR`` + ``VAULT_TOKEN`` are set, else
  ``env`` (with a warning logged). Honored verbatim when set.

* ``WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR`` — file-based secrets
  directory for ``EnvCredentialBroker``. When unset (and broker_kind
  resolves to ``env``), broker construction is skipped and the no-op
  stubs ship (with a loud warning).

* ``WORMBASE_AGENT_GATEWAY_INSTALL_ID`` — overrides the install_id
  threaded into ``BrokerExecutor``. Defaults to the worm-core
  ``install_id`` argument (which is the company_id in v1).

* ``VAULT_ADDR`` / ``VAULT_TOKEN`` — Vault connection params. Required
  when ``WORMBASE_AGENT_GATEWAY_BROKER_KIND=vault`` AND used for
  default inference when the broker-kind env knob is unset.

* ``WORMBASE_AGENT_GATEWAY_FEDERATE_CALLBACK_URL`` — the public URL the
  federate-mode agent POSTs its result hash to. Defaults to a
  ``.invalid`` placeholder which fails fast in production but keeps
  unit tests + smoke construction happy.

* ``WORMBASE_AGENT_GATEWAY_MCP_TRANSPORT`` — ``"stdio" | "http"``;
  default ``"stdio"``. Selects the runtime listener mode.

* ``WORMBASE_AGENT_GATEWAY_MCP_PORT`` — int; default ``8911``. Only
  consumed when transport is ``http``.

* ``WORMBASE_AGENT_GATEWAY_MCP_HOST`` — str; default ``"127.0.0.1"``.
  Only consumed when transport is ``http``. Bind to ``0.0.0.0`` only
  if the deploy is fronted by an authenticating reverse proxy.

* ``WORMBASE_AGENT_GATEWAY_MCP_LISTENER_ENABLED`` — default ``"0"``;
  flip to ``"1"`` to start the runtime listener after the boot-time
  build smoke. Kept opt-in for v1.3 so existing deploys do not
  inadvertently start a previously-absent network surface.

* ``WORMBASE_AGENT_GATEWAY_TICK_S`` — int; unset by default. When set
  to a positive integer (e.g. ``3600`` for hourly), a
  :class:`wormbase_reactivities.clock_tick_emitter.ClockTickEmitter`
  is started alongside the ReactivityRunner. Drives the gap-escalation
  axis (``agent_gateway.gap_to_escalation``) via a cadence-driven
  ``clock_tick`` ledger entry instead of new-gap traffic — v2.B
  Phase 3 (2026-05-12) swap that lets a freshly-installed worm
  escalate prior gaps without waiting for a second gap to land.
  Default off preserves byte-identical boot behavior.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from wormbase_agent_gateway.governance import (
    StatefulGateBundle,
    make_stateful_gate_bundle,
)
from wormbase_agent_gateway.identity import AgentGrant
from wormbase_agent_gateway.lineage import (
    CompositeLineageInferenceService,
    DbtManifestStrategy,
    NamingHeuristicStrategy,
    SampleOverlapStrategy,
)
from wormbase_agent_gateway.mcp_server import (
    AgentGatewayMCPServer,
    GatewayDeps,
    build_agent_gateway_mcp_server,
)
from wormbase_agent_gateway.quality import (
    CompositeQualityProposalService,
    DbtTestsStrategy,
    HistoricalStatsStrategy,
    SchemaPatternStrategy,
    SemanticTypeQualityCheckStrategy,
)
from wormbase_agent_gateway.column_classification import (
    DomainDefaultClassificationStrategy,
    NamingPatternClassificationStrategy,
    ProposedColumnClassification,
    SemanticTypeClassificationStrategy,
    make_composite_column_classification_service,
)
from wormbase_agent_gateway.entity_stitch import (
    NameMatchEntityStrategy,
    ProposedEntityStitch,
    SampleOverlapEntityStrategy,
    SchemaShapeEntityStrategy,
    make_composite_entity_stitch_service,
)
from wormbase_agent_gateway.source_candidates import (
    ChannelMentionAcquisitionStrategy,
    ComplementaritySourceStrategy,
    KpiGapAcquisitionStrategy,
    ProposedSourceCandidate,
    make_composite_source_candidate_service,
)
from wormbase_agent_gateway.catalog_drift import (
    ColumnSetDriftStrategy,
    ColumnTypeDriftStrategy,
    ProposedCatalogDrift,
    TableSetDriftStrategy,
    make_composite_catalog_drift_service,
)
from wormbase_agent_gateway.lake_loop import LakeLoopComposite
from wormbase_agent_gateway.reactivities import (
    Compounding,
    make_catalog_drift_discovery_reactivity,
    make_column_classification_discovery_reactivity,
    make_entity_stitch_discovery_reactivity,
    make_fingerprint_discovery_reactivity,
    make_lineage_discovery_reactivity,
    make_quality_discovery_reactivity,
    make_schema_impact_discovery_reactivity,
    make_source_candidate_discovery_reactivity,
)
from wormbase_agent_gateway.schema_impact import (
    AcknowledgedDriftImpactStrategy,
    CompositeSchemaImpactService,
    DbtTestImpactStrategy,
    GovernanceClassificationImpactStrategy,
    LineageEdgeImpactStrategy,
    SemanticTypeImpactStrategy,
    TypeCoercionImpactStrategy,
)
from wormbase_agent_gateway.semantic_type import (
    ColumnNameFingerprintStrategy,
    DistributionFingerprintStrategy,
    ProposedSemanticType,
    ValuePatternFingerprintStrategy,
    make_composite_semantic_type_service,
)
from wormbase_agent_gateway.router_query import (
    BrokerExecutor,
    FederateIssuer,
)
from wormbase_agent_gateway.subscriptions import (
    StreamRegistry,
    SubscriptionDispatcherDeps,
    WebhookTransport,
)
from wormbase_agent_gateway.subscriptions.mcp_tools import SubscriptionToolDeps
from wormbase_agent_gateway.subscriptions.stream_transport import (
    build_stream_transport_from_env,
)
from wormbase_agent_gateway.tenancy import (
    InMemoryQuotaTracker,
    InMemoryRateLimiter,
    InMemoryTenantRouter,
    LedgerQuotaTracker,
    QuotaConsumedEmitter,
    QuotaTracker,
    TenantRouter,
    is_multi_tenant_mcp_enabled,
    is_tenant_quota_ledger_emission_enabled,
    resolve_default_quota_count_threshold,
    resolve_default_quota_per_day,
    resolve_default_quota_time_threshold_seconds,
    resolve_default_rate_limit_per_min,
)
from wormbase_inference import AgentID, GovernanceContext
from wormbase_inference.embedding import (
    EmbeddingService,
    build_default_embedding_service,
)
from wormbase_reactivities import ClockTickEmitter

from wormbase_core.connector_sampler import ConnectorSampler
from wormbase_core.lineage_catalog_reader import (
    LedgerCatalogReader,
    LedgerDbtManifestReader,
    NoopSampler,
)
from wormbase_core.source_handle_provider import LedgerSourceHandleProvider
from wormbase_core.quality_catalog_reader import (
    LedgerDbtTestReader,
    NoopHistoricalStatsReader,
)
from wormbase_core.schema_impact_lineage_reader import (
    LedgerLineageEdgeReader,
)
from wormbase_core.catalog_drift_acknowledged_reader import (
    LedgerAcknowledgedDriftReader,
)
from wormbase_core.column_classification_governance_reader import (
    LedgerConfirmedClassificationReader,
)
from wormbase_core.column_classification_semantic_reader import (
    LedgerConfirmedSemanticTypeReader,
)
from wormbase_core.column_classification_domain_reader import (
    LedgerDomainDefaultReader,
)
from wormbase_core.source_candidate_readers import (
    LedgerConnectedSourceReader,
    LedgerKpiNodeReader,
    LedgerSilverConversationReader,
)
from wormbase_core.catalog_drift_snapshot_reader import (
    LedgerCatalogSnapshotReader,
)
from wormbase_core.agent_gateway_readers import (
    LedgerAgentGrantReader,
    LedgerDataProductReader,
    LedgerDecisionReader,
    LedgerProcessMapReader,
    LedgerSubscriptionReader,
)
from wormbase_core.optional_effect import OptionalEffectGuard

logger = logging.getLogger("wormbase_core.agent_gateway_construction")


# ---------------------------------------------------------------------------
# No-op stubs for v1.3-pending deps
#
# Each stub is named after the Protocol it satisfies (so logs / stack
# traces stay readable) and explicitly returns empty / NotImplementedError
# so a real call to one of them surfaces as a clear error rather than
# silently doing nothing.
# ---------------------------------------------------------------------------


class _NotYetProductionCatalogClient:
    """Pending: no production CatalogClient impl in v1.2.

    Used by the ``lake.semantic.metric`` / ``lake.semantic.query_spec``
    tools to look up registered metric definitions. v1.3 wires the
    catalog-mirror projection reader.
    """

    async def get_metric(self, name: str) -> dict[str, Any] | None:
        return None

    async def get_table(self, external_id: str) -> dict[str, Any] | None:
        return None

    async def list_tables(self) -> list[dict[str, Any]]:
        return []


class _NotYetProductionCatalogReader:
    """Pending: no production CatalogReader impl in v1.2.

    Used by ``lake.catalog.tables`` and ``lake.lineage``. v1.3 will
    walk the catalog-mirror projection tables directly.
    """

    async def list_tables(
        self, *, company_id: UUID, filter: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        return []

    async def list_lineage(
        self,
        *,
        company_id: UUID,
        resource_id: str,
        direction: str,
    ) -> list[dict[str, Any]]:
        return []

    async def get_resource_classification(
        self, resource_id: str,
    ) -> str | None:
        return None


class _NotYetProductionBrokerExecutor:
    """Pending: no CredentialBroker wired (env knob unset).

    Used by ``lake.query`` to execute SQL against the upstream
    warehouse via a ``CredentialBroker``-issued scoped account.
    Constructed when ``WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR`` (or the
    Vault knobs) is unset. Calls raise so a real invocation surfaces
    the gap loudly.
    """

    async def execute(self, **_kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError(
            "BrokerExecutor not yet productionized; set "
            "WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR (or "
            "WORMBASE_AGENT_GATEWAY_BROKER_KIND=vault) to enable.",
        )


class _NotYetProductionFederateIssuer:
    """Pending: no CredentialBroker wired (env knob unset).

    Used by the ``lake.query`` federate path. Constructed when no
    broker is available; calls raise so a real invocation surfaces
    the gap loudly.
    """

    async def issue(self, **_kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError(
            "FederateIssuer not yet productionized; set "
            "WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR (or "
            "WORMBASE_AGENT_GATEWAY_BROKER_KIND=vault) to enable.",
        )


async def _empty_grant_lookup(_a: AgentID) -> Sequence[AgentGrant]:
    """Legacy v1.2-and-earlier empty grant_lookup.

    Returns an empty grant list so every agent appears unprivileged; the
    AgentAccessGate denies every call. Kept in the module for tests that
    explicitly want a deny-all surface; production paths use
    :func:`_make_grant_lookup` (v1.3) instead.
    """
    return ()


def _make_grant_lookup(
    *, reader: LedgerAgentGrantReader, company_id: UUID,
) -> Any:
    """Return a tenant-bound ``grant_lookup`` callable from a reader.

    The gate chain's ``grant_lookup`` signature is
    ``Callable[[AgentID], Awaitable[Sequence[AgentGrant]]]``. The
    reader needs both a ``company_id`` and an ``AgentID``; production
    construction sites resolve the company_id once at install time and
    close over it here so the gate chain stays single-arg.

    The closure also degrades gracefully — if the ledger fetch raises,
    we log loudly and return ``()`` so the gate denies the call rather
    than crashing the MCP tool wrapper. Operators see the failure in
    logs but the gateway surface stays up.
    """

    async def grant_lookup(agent_id: AgentID) -> Sequence[AgentGrant]:
        try:
            return await reader.list_active_grants(
                company_id=company_id, agent_id=agent_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "LedgerAgentGrantReader failed for agent_id=%r: %s — "
                "denying request as a safety fallback",
                agent_id.value, exc,
            )
            return ()

    return grant_lookup


async def _default_agent_id_resolver() -> AgentID:
    """Pending: no HTTP-transport agent_id resolution at boot.

    The MCP server is constructed but not started as an HTTP listener
    in v1.2; this resolver returns a sentinel AgentID so the construction
    smoke succeeds. When the listener lifts into boot, the
    Authorization-header parser replaces this.
    """
    return AgentID(value="boot-smoke-agent")


async def _default_governance_resolver(_a: AgentID) -> GovernanceContext:
    """Pending: no per-install classification ceiling lookup at boot.

    Returns a conservative "internal" ceiling + zero budget so any call
    that escapes the agent-access gate still hits a cost wall. Replaced
    in v1.3.
    """
    return GovernanceContext(
        classification_ceiling="internal",  # type: ignore[arg-type]
        cost_budget_usd=Decimal("0.00"),
        pii_redaction=True,
        domain_id=None,
    )


# ---------------------------------------------------------------------------
# Item #1 — CredentialBroker construction from env
# ---------------------------------------------------------------------------


def _resolve_broker_kind_from_env() -> str:
    """Return the broker kind to use, resolving the v1.3 Vault-first default.

    Decision table:

    +-----------------------------------+--------------------------+
    | Env state                         | Resolved kind            |
    +===================================+==========================+
    | BROKER_KIND set explicitly        | honored verbatim         |
    +-----------------------------------+--------------------------+
    | BROKER_KIND unset                 | "vault" if VAULT_ADDR    |
    | AND VAULT_ADDR + VAULT_TOKEN set  | + VAULT_TOKEN are set    |
    +-----------------------------------+--------------------------+
    | BROKER_KIND unset                 | "env" + WARN logged      |
    | AND Vault env not set             |                          |
    +-----------------------------------+--------------------------+

    The function intentionally returns "env" in the fall-through case
    rather than refusing to start — :func:`_build_credential_broker_from_env`
    layers a second warning on top if the env-broker secrets dir is
    also unset, which is the louder warning the close-out brief asks for.
    """
    explicit = os.environ.get(
        "WORMBASE_AGENT_GATEWAY_BROKER_KIND", "",
    ).strip().lower()
    if explicit:
        return explicit

    vault_addr = os.environ.get("VAULT_ADDR", "").strip()
    vault_token = os.environ.get("VAULT_TOKEN", "").strip()
    if vault_addr and vault_token:
        logger.info(
            "WORMBASE_AGENT_GATEWAY_BROKER_KIND unset; VAULT_ADDR + "
            "VAULT_TOKEN present — defaulting to vault (v1.3 Item #3 "
            "production-default flip)",
        )
        return "vault"

    logger.warning(
        "WORMBASE_AGENT_GATEWAY_BROKER_KIND unset and no Vault env "
        "(VAULT_ADDR / VAULT_TOKEN) detected — falling back to 'env' "
        "broker; production deploys should set VAULT_ADDR + VAULT_TOKEN "
        "or an explicit BROKER_KIND",
    )
    return "env"


def _build_credential_broker_from_env() -> tuple[Any | None, str | None]:
    """Return ``(broker, install_id)`` from env, or ``(None, None)``.

    Knobs:

      - ``WORMBASE_AGENT_GATEWAY_BROKER_KIND`` — ``"env"`` or ``"vault"``;
        when unset, v1.3 :func:`_resolve_broker_kind_from_env` picks the
        Vault-first default if ``VAULT_ADDR`` + ``VAULT_TOKEN`` are set.
      - ``WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR`` — required for the
        ``env`` kind.
      - ``VAULT_ADDR`` + ``VAULT_TOKEN`` — required for the ``vault``
        kind (existing Wave 2 spike pattern).
      - ``WORMBASE_AGENT_GATEWAY_INSTALL_ID`` — overrides the install_id
        threaded into the resulting ``BrokerExecutor``. Defaults to
        ``None`` so the caller's ``install_id`` argument flows through.

    Returns ``(None, None)`` on any failure (missing env, import
    failure, Vault auth failure) so the no-op stubs ship and the rest
    of boot proceeds. The fallback raises loudly on use, so a real MCP
    call surfaces the gap.
    """
    kind = _resolve_broker_kind_from_env()
    install_id_override = (
        os.environ.get("WORMBASE_AGENT_GATEWAY_INSTALL_ID", "").strip()
        or None
    )

    if kind == "env":
        secrets_dir = os.environ.get(
            "WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR", "",
        ).strip()
        if not secrets_dir:
            # v1.3 Item #3: louder warning when neither Vault env nor
            # the env-broker secrets dir is configured. This is the
            # "no production credential plumbing" path — every
            # broker-backed MCP call will raise NotImplementedError
            # from _NotYetProductionBrokerExecutor.
            logger.warning(
                "no CredentialBroker wired: BROKER_KIND resolved to "
                "'env' but WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR is "
                "unset. Falls back to _NotYetProductionBrokerExecutor "
                "stub — any broker-backed MCP tool (lake.query) will "
                "raise NotImplementedError until a broker is wired.",
            )
            return None, install_id_override
        try:
            from wormbase_agent_gateway.credential_broker.env import (
                EnvCredentialBroker,
            )
            broker = EnvCredentialBroker(secrets_dir=Path(secrets_dir))
        except Exception as exc:
            logger.warning(
                "EnvCredentialBroker construction failed at %s: %s — "
                "falling back to no-op stubs",
                secrets_dir, exc,
            )
            return None, install_id_override
        return broker, install_id_override

    if kind == "vault":
        addr = os.environ.get("VAULT_ADDR", "").strip()
        token = os.environ.get("VAULT_TOKEN", "").strip()
        if not addr or not token:
            logger.warning(
                "VaultCredentialBroker requested "
                "(WORMBASE_AGENT_GATEWAY_BROKER_KIND=vault) but "
                "VAULT_ADDR or VAULT_TOKEN is unset — falling back to "
                "no-op stubs",
            )
            return None, install_id_override
        try:
            from wormbase_agent_gateway.credential_broker.vault import (
                VaultCredentialBroker,
            )
            broker = VaultCredentialBroker(addr=addr, token=token)
        except Exception as exc:
            logger.warning(
                "VaultCredentialBroker construction failed against %s: "
                "%s — falling back to no-op stubs", addr, exc,
            )
            return None, install_id_override
        return broker, install_id_override

    logger.warning(
        "unknown WORMBASE_AGENT_GATEWAY_BROKER_KIND=%r — expected "
        "'env' or 'vault'; falling back to no-op stubs", kind,
    )
    return None, install_id_override


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class GatewayBuildSmokeResult:
    """Outcome of the build-smoke call. Returned for log + test consumption.

    Fields:
        server: the constructed AgentGatewayMCPServer instance (held in
            memory; not started as an HTTP listener in v1.2). In v1.3
            it can be passed to :func:`run_agent_gateway_mcp_listener`
            to start the runtime listener.
        production_readers_wired: True iff the four production-ready
            readers (decision, process map, data product) AND
            optionally the broker + stateful gate bundle were
            successfully constructed.
        broker_wired: True iff a ``CredentialBroker`` was constructed
            and the ``BrokerExecutor`` + ``FederateIssuer`` are real
            instances (not the no-op stubs).
        stateful_gates_wired: True iff a non-None
            ``StatefulGateBundle`` was passed through to the gate
            chain.
        grant_lookup_wired: True iff the v1.3 LedgerAgentGrantReader
            is wired (replaces the v1.2 _empty_grant_lookup that
            denied every MCP call).
        pending_deps: list of dep slot names that still ship a no-op
            stub. Logged at INFO at boot.
    """

    server: AgentGatewayMCPServer
    production_readers_wired: bool
    broker_wired: bool
    stateful_gates_wired: bool
    grant_lookup_wired: bool
    pending_deps: tuple[str, ...]
    # v2.A Batch B Task 5: True iff WORMBASE_SUBSCRIPTIONS_ENABLED=true
    # and the SubscriptionToolDeps + SubscriptionDispatcherDeps were
    # successfully constructed. False default preserves byte-identical
    # smoke output on pre-v2.A deploys.
    subscriptions_wired: bool = False
    # v1.4 #3: the resolved CredentialBroker (or None when the env
    # didn't yield one). Exposed so cli.py can bind it into the
    # LazyWebhookSecretResolver that the subscription dispatcher
    # composed earlier — closing the v2.A webhook-resolution gap.
    broker: Any | None = None
    # v2.B Phase 3b: True iff WORMBASE_EMBEDDING_ENABLED=true and the
    # OllamaCloudEmbeddingService was constructed. False default
    # preserves byte-identical smoke output on pre-3b deploys.
    embedding_wired: bool = False
    # Path 4 (2026-05-21 overnight roadmap): True iff
    # WORMBASE_MULTI_TENANT_MCP=true and the InMemoryTenantRouter was
    # successfully constructed. False default preserves byte-identical
    # smoke output on pre-Path-4 deploys.
    multi_tenant_wired: bool = False


def compose_production_agent_gateway_deps(
    *,
    ledger: Any,
    company_id: UUID,
    install_id: str,
    pii_gate: Any | None = None,
    warmup_gate: Any | None = None,
    interjection_gate: Any | None = None,
    knowledge_gate: Any | None = None,
) -> GatewayDeps:
    """Build a ``GatewayDeps`` with v1.2's productionizable wiring.

    Wires (production today):

      * ``decision_reader=LedgerDecisionReader(ledger=ledger)``
        (v1.1 Task 2)
      * ``process_map_reader=LedgerProcessMapReader(ledger=ledger)``
        (v1.1 Task 3)
      * ``data_product_reader=LedgerDataProductReader(ledger=ledger)``
        (v1.2 Task 2 Item #3)
      * ``broker_executor=BrokerExecutor(broker=...)`` and
        ``federate_issuer=FederateIssuer(broker=...)`` when the broker
        env knobs are set (v1.2 Task 2 Item #1)
      * ``stateful_gate_bundle=make_stateful_gate_bundle(...)`` when
        all 4 governance gates are provided (v1.2 Task 2 Item #2)

    Wires (stubs):

      * ``catalog_client`` / ``catalog_reader`` / ``grant_lookup`` /
        ``agent_id_resolver`` / ``governance_resolver`` — pending v1.3.

    The four governance gate kwargs (``pii_gate``, ``warmup_gate``,
    ``interjection_gate``, ``knowledge_gate``) default to ``None`` so
    callers that don't have them (tests, future surfaces) can keep
    using the inline-only chain. When ALL four are provided, the
    stateful bundle is constructed and threaded through ``GatewayDeps``.

    The broker env knobs are read inside this function so callers
    don't need to know about them; if the knobs are unset, no-op
    broker stubs ship.
    """
    broker, install_id_override = _build_credential_broker_from_env()
    resolved_install_id = install_id_override or install_id
    # v1.4 #3: stash the resolved broker on a function attribute so
    # ``run_agent_gateway_build_smoke`` can surface it back to the
    # caller and bind it into the LazyWebhookSecretResolver. Same
    # module-level handoff pattern as ``_last_dispatcher_deps``.
    compose_production_agent_gateway_deps._last_broker = broker  # type: ignore[attr-defined]

    if broker is not None:
        broker_executor: Any = BrokerExecutor(
            broker=broker, install_id=resolved_install_id,
        )
        federate_callback = os.environ.get(
            "WORMBASE_AGENT_GATEWAY_FEDERATE_CALLBACK_URL",
            "https://gateway.example.invalid/federate/callback",
        ).strip() or "https://gateway.example.invalid/federate/callback"
        federate_issuer: Any = FederateIssuer(
            broker=broker, callback_base_url=federate_callback,
        )
    else:
        broker_executor = _NotYetProductionBrokerExecutor()
        federate_issuer = _NotYetProductionFederateIssuer()

    stateful_bundle: StatefulGateBundle | None = None
    if (
        pii_gate is not None
        and warmup_gate is not None
        and interjection_gate is not None
        and knowledge_gate is not None
    ):
        stateful_bundle = make_stateful_gate_bundle(
            pii_gate=pii_gate,
            warmup_gate=warmup_gate,
            interjection_gate=interjection_gate,
            knowledge_gate=knowledge_gate,
        )

    # v1.3 Item #1: real grant_lookup backed by ledger-walked
    # emit_agent_grant entries, replaces the v1.2 _empty_grant_lookup
    # that denied every MCP call.
    grant_reader = LedgerAgentGrantReader(ledger=ledger)
    grant_lookup = _make_grant_lookup(
        reader=grant_reader, company_id=company_id,
    )

    # v2.A Batch B Task 5: optional subscription deps. When
    # WORMBASE_SUBSCRIPTIONS_ENABLED=true, wire the dispatcher inputs +
    # the MCP-tool deps so the 4 agent.subscriptions.* tools become
    # functional (default-off: tools register but return "not configured"
    # denials). The dispatcher itself is registered via
    # wire_agent_gateway_for_install when this returns non-None;
    # composition happens in cli.py.
    subscription_tool_deps: SubscriptionToolDeps | None = None
    if is_subscriptions_enabled():
        subscription_reader = LedgerSubscriptionReader(ledger=ledger)
        stream_registry = StreamRegistry()
        webhook_transport = WebhookTransport(
            secret_resolver=_make_webhook_secret_resolver(broker),
            max_retries=resolve_subscription_webhook_max_retries(),
            request_timeout_s=float(
                resolve_subscription_webhook_timeout_s(),
            ),
        )
        # Path 3 (2026-05-21 overnight roadmap) — optional SSE transport
        # via env knob WORMBASE_MCP_SSE_TRANSPORT. Default is
        # ListModeTransport, byte-identical to the pre-Path-3 inline
        # wrapper. Case 6 of the Optional-Effect Injection doctrine
        # (``docs/superpowers/specs/2026-05-21-optional-effect-injection-doctrine.md``).
        stream_transport = build_stream_transport_from_env()
        subscription_tool_deps = SubscriptionToolDeps(
            ledger=ledger,
            company_id=company_id,
            subscription_reader=subscription_reader,
            stream_registry=stream_registry,
            stream_transport=stream_transport,
        )
        # Stash the dispatcher deps on a private attribute so cli.py /
        # wire_agent_gateway_for_install can pick them up without
        # duplicating env reads. Constructed lazily inside the
        # ``make_subscription_dispatcher_deps`` helper.
        compose_production_agent_gateway_deps._last_dispatcher_deps = (  # type: ignore[attr-defined]
            SubscriptionDispatcherDeps(
                subscription_reader=subscription_reader,
                webhook_transport=webhook_transport,
                stream_registry=stream_registry,
                ledger=ledger,
            )
        )
    else:
        compose_production_agent_gateway_deps._last_dispatcher_deps = None  # type: ignore[attr-defined]

    # v2.B Phase 3b — optional EmbeddingService wiring (opt-in via
    # WORMBASE_EMBEDDING_ENABLED). When enabled, the §4.5 record-outcome
    # MCP tool computes a 768-dim embedding over the NL question at
    # write time and stamps it onto QueryOutcomeRecordedPayload.
    # When disabled (default), the payload's embedding field stays None
    # and downstream axes 1+3 cluster via substring fallback.
    embedding_service: EmbeddingService | None = None
    if is_embedding_enabled():
        embedding_service = build_default_embedding_service()

    # Path 4 (2026-05-21 overnight roadmap) — optional TenantRouter
    # wiring (opt-in via WORMBASE_MULTI_TENANT_MCP). When enabled,
    # every MCP tool handler resolves the inbound ``X-Tenant-Slug``
    # header to a TenantContext, overrides ``company_id`` per request,
    # and enforces per-tenant rate-limits + 24h quotas. When disabled
    # (default), the server runs single-tenant — byte-identical to the
    # Phase 1-3c behavior — and ``company_id`` is taken verbatim from
    # this deps bundle.
    #
    # This is Case 5 of the Optional-Effect Injection doctrine
    # (``docs/superpowers/specs/2026-05-21-optional-effect-injection-doctrine.md``
    # §9.1). The boot-time install_id is registered as the default
    # tenant so existing single-install deployments that flip the env
    # knob can still address themselves; explicit tenant registration
    # for SaaS deployments happens via :func:`register_tenants_from_env`
    # OR by the operator calling ``router.register(...)`` post-boot.
    tenant_router: TenantRouter | None = build_tenant_router_from_env(
        install_id=resolved_install_id,
        ledger=ledger,
        company_id=company_id,
    )

    return GatewayDeps(
        ledger=ledger,
        company_id=company_id,
        install_id=resolved_install_id,
        catalog_client=_NotYetProductionCatalogClient(),
        catalog_reader=_NotYetProductionCatalogReader(),
        broker_executor=broker_executor,
        federate_issuer=federate_issuer,
        grant_lookup=grant_lookup,
        agent_id_resolver=_default_agent_id_resolver,
        governance_resolver=_default_governance_resolver,
        router=None,
        decision_reader=LedgerDecisionReader(ledger=ledger),
        process_map_reader=LedgerProcessMapReader(ledger=ledger),
        data_product_reader=LedgerDataProductReader(ledger=ledger),
        stateful_gate_bundle=stateful_bundle,
        subscription_tool_deps=subscription_tool_deps,
        embedding_service=embedding_service,
        tenant_router=tenant_router,
    )


# ---------------------------------------------------------------------------
# v2.A Batch B Task 5 — subscription env knobs + helpers
# ---------------------------------------------------------------------------


def is_subscriptions_enabled() -> bool:
    """Return True iff ``WORMBASE_SUBSCRIPTIONS_ENABLED`` is truthy.

    Default off (env knob unset → no dispatcher constructed). Truthy
    values: ``"1"``, ``"true"``, ``"yes"`` (case-insensitive). Anything
    else (including empty / unset) → off.

    Per the v2.A plan §Task 5: opt-in by design so existing deploys
    don't inadvertently add a 6th Reactivity to their boot graph and
    a 4-tool MCP surface change without operator consent.
    """
    return os.environ.get(
        "WORMBASE_SUBSCRIPTIONS_ENABLED", "0",
    ).strip().lower() in ("1", "true", "yes")


def is_embedding_enabled() -> bool:
    """Return True iff ``WORMBASE_EMBEDDING_ENABLED`` is truthy.

    v2.B Phase 3b — gates the write-time embedding wire on the §4.5
    ``lake.query.record_outcome`` path. Default OFF preserves
    byte-identical behaviour: payloads ship with ``embedding=None``
    and axes 1+3 cluster via the substring fallback.

    Flipping to true requires:

      * ``OLLAMA_API_KEY`` configured (same bearer as Kimi);
      * Postgres production: v018 migration applied (Vector(768) shape).

    Truthy values: ``"1"``, ``"true"``, ``"yes"`` (case-insensitive).
    """
    return os.environ.get(
        "WORMBASE_EMBEDDING_ENABLED", "0",
    ).strip().lower() in ("1", "true", "yes")


def build_tenant_router_from_env(
    *,
    install_id: str,
    ledger: Any | None = None,
    company_id: UUID | None = None,
) -> TenantRouter | None:
    """Construct an :class:`InMemoryTenantRouter` from env, or return None.

    Path 4 (2026-05-21 overnight roadmap) — opt-in multi-tenant MCP
    routing wire. Returns:

      * ``None`` when ``WORMBASE_MULTI_TENANT_MCP`` is unset / falsy.
        The MCP server runs single-tenant — byte-identical to the
        Phase 1-3c behavior.
      * An :class:`InMemoryTenantRouter` with the install's own
        ``install_id`` pre-registered as a tenant (so an existing
        single-install deployment that flips the env knob can address
        itself), plus any additional tenants enumerated by
        ``WORMBASE_MULTI_TENANT_SLUGS`` (comma-separated).

    The router shares the package-default ``tenant_to_uuid`` resolver
    (uuid5-stable) so the slug→company_id mapping is identical to the
    worm-core HTTP write API's :func:`tenant_to_uuid` — required for
    cross-surface tenant ID parity.

    Optional-Effect Injection doctrine §3 Rule 1: default None
    preserves byte-identical behavior.

    Env knobs (Path 4):

      * ``WORMBASE_MULTI_TENANT_MCP`` — primary capability gate.
        Default OFF. Only canonical ``"true"`` is honored.
      * ``WORMBASE_MULTI_TENANT_SLUGS`` — comma-separated additional
        tenant slugs to pre-register. Unset → only the install's own
        slug.
      * ``WORMBASE_MULTI_TENANT_RATE_LIMIT_PER_MIN`` — per-tenant
        rate limit. Default 100.
      * ``WORMBASE_MULTI_TENANT_QUOTA_PER_DAY`` — per-tenant 24h
        call quota. Default 100_000.

    Tenant-policy ledger emission knobs (final-wave item #7,
    2026-05-13; Optional-Effect Injection doctrine §6.4 Case 7):

      * ``WORMBASE_TENANT_QUOTA_LEDGER`` — opt-in audit-trail wrapper.
        Default OFF: in-memory quota tracking is byte-identical to
        Path 4. When ON (and ``ledger`` + ``company_id`` are passed),
        the quota tracker becomes :class:`LedgerQuotaTracker` which
        emits ``tenant_quota_consumed`` ledger entries at cadence
        (100 requests OR 5 minutes per tenant, whichever first;
        immediate on quota_exhausted).
      * ``WORMBASE_TENANT_QUOTA_LEDGER_COUNT_THRESHOLD`` — emission
        cadence count threshold. Default 100.
      * ``WORMBASE_TENANT_QUOTA_LEDGER_TIME_THRESHOLD_SECONDS`` —
        emission cadence time threshold (seconds). Default 300.
    """
    if not is_multi_tenant_mcp_enabled():
        return None

    rate_limit = resolve_default_rate_limit_per_min()
    quota = resolve_default_quota_per_day()

    rate_limiter = InMemoryRateLimiter(capacity_per_min=rate_limit)
    in_memory_quota = InMemoryQuotaTracker(capacity_per_day=quota)

    # Optional-Effect Injection Case 7 (doctrine Addendum 2): the
    # audit-emission capability is the optional dependency. Present iff
    # WORMBASE_TENANT_QUOTA_LEDGER=true AND a ledger + company_id were
    # threaded through. The "service" wrapped in the guard is the
    # (ledger, company_id) pair; absent → bare InMemoryQuotaTracker
    # (byte-identical to pre-final-wave Path 4); present → wrap in
    # LedgerQuotaTracker for the audit-trail emission.
    emission_capability: tuple[Any, UUID] | None
    if (
        is_tenant_quota_ledger_emission_enabled()
        and ledger is not None
        and company_id is not None
    ):
        emission_capability = (ledger, company_id)
    else:
        emission_capability = None
        if (
            is_tenant_quota_ledger_emission_enabled()
            and (ledger is None or company_id is None)
        ):
            logger.warning(
                "WORMBASE_TENANT_QUOTA_LEDGER=true but ledger / company_id "
                "not provided to build_tenant_router_from_env; falling "
                "back to in-memory quota tracking",
            )

    quota_emission_guard: OptionalEffectGuard[tuple[Any, UUID]] = (
        OptionalEffectGuard("ledger_quota_tracker", emission_capability)
    )

    def _wrap_with_emission(cap: tuple[Any, UUID]) -> QuotaTracker:
        ledger_obj, company_uuid = cap
        emit = _build_tenant_quota_consumed_emitter(
            ledger=ledger_obj, company_id=company_uuid,
        )
        return LedgerQuotaTracker(
            in_memory_quota,
            emit,
            count_threshold=resolve_default_quota_count_threshold(),
            time_threshold_seconds=(
                resolve_default_quota_time_threshold_seconds()
            ),
        )

    def _bare_in_memory() -> QuotaTracker:
        return in_memory_quota

    quota_tracker: QuotaTracker = quota_emission_guard.take_path_sync(
        with_present=_wrap_with_emission,
        without=_bare_in_memory,
    )
    ledger_emission_active = quota_emission_guard.metrics()[
        "present_path_count"
    ] > 0
    # Stash the guard on the function for inspection (parity with
    # ``compose_production_agent_gateway_deps._last_broker``). Tests +
    # operators can read the per-path counters via
    # ``build_tenant_router_from_env._last_quota_emission_guard.metrics()``.
    build_tenant_router_from_env._last_quota_emission_guard = (  # type: ignore[attr-defined]
        quota_emission_guard
    )

    # Compose the router with the worm-core slug resolver. That
    # function (tenant_to_uuid) is defined in wormbase_core.service
    # and uses the same uuid5 namespace as the package-default
    # resolver, so the company_ids agree byte-for-byte.
    from wormbase_core.service import tenant_to_uuid

    router = InMemoryTenantRouter(
        slug_resolver=tenant_to_uuid,
        rate_limiter=rate_limiter,
        quota_tracker=quota_tracker,
    )

    # Pre-register the install's own slug. For deployments that ran
    # single-tenant before, this keeps the install reachable under
    # multi-tenant mode using its existing identifier.
    try:
        router.register(tenant_slug=install_id)
    except ValueError:
        # Empty install_id — skip the auto-registration; the operator
        # must enumerate slugs explicitly.
        logger.warning(
            "WORMBASE_MULTI_TENANT_MCP=true but install_id is empty — "
            "auto-registration skipped",
        )

    # Pre-register any slugs listed in WORMBASE_MULTI_TENANT_SLUGS.
    extra = os.environ.get("WORMBASE_MULTI_TENANT_SLUGS", "").strip()
    if extra:
        for raw_slug in extra.split(","):
            slug = raw_slug.strip()
            if not slug:
                continue
            try:
                router.register(tenant_slug=slug)
            except ValueError:
                logger.warning(
                    "WORMBASE_MULTI_TENANT_SLUGS includes invalid "
                    "entry %r — skipped",
                    raw_slug,
                )

    logger.info(
        "TenantRouter wired (Path 4 multi-tenant MCP): tenants=%s "
        "rate_limit_per_min=%d quota_per_day=%d quota_ledger_emission=%s",
        sorted(router._tenants.keys()),  # type: ignore[attr-defined]
        rate_limit, quota, ledger_emission_active,
    )
    return router


def _build_tenant_quota_consumed_emitter(
    *, ledger: Any, company_id: UUID,
) -> QuotaConsumedEmitter:
    """Construct the :class:`QuotaConsumedEmitter` callable for the wire.

    Encapsulates the PEVR write for ``tenant_quota_consumed``. Kept
    local so the agent-gateway package stays free of ledger imports.

    Final-wave item #7 (2026-05-13) — Optional-Effect Injection §6.4
    Case 7. The callable accepts the payload dict produced by
    :class:`LedgerQuotaTracker`, validates it through the Pydantic
    model, and writes a PEVR cycle pinned to
    ``target_kind="tenant_quota_consumed"`` on the resolve leg.

    Failure handling: emission errors are logged but NOT re-raised —
    the MCP request path must not fail because the audit-trail
    emission did. Quota enforcement already happened in the wrapped
    :class:`InMemoryQuotaTracker.consume`; this callable is pure
    side-effect.
    """
    from wormbase_ledger.entries import TenantQuotaConsumedPayload

    from wormbase_core.service import tenant_to_uuid
    from wormbase_core.write_actions import _pevr

    async def _emit(payload: dict[str, Any]) -> None:
        try:
            validated = TenantQuotaConsumedPayload.model_validate(payload)
            args = validated.model_dump(mode="json")
            tenant_slug = validated.tenant_slug
            # Derive a stable UUID from the slug for the PEVR ref_id
            # contract. uuid5-based, same namespace as the rest of the
            # tenant routing surface — replay determinism preserved.
            slug_ref = tenant_to_uuid(tenant_slug)
            await _pevr(
                ledger=ledger,
                company_id=company_id,
                target_kind="tenant_quota_consumed",
                ref_id=slug_ref,
                reason=(
                    f"tenant quota consumption cadence ({validated.triggered_by}) "
                    f"for tenant {tenant_slug}: {validated.consumption_count} "
                    f"requests in window"
                ),
                proposed_by="tenant-quota-tracker",
                tool="emit_tenant_quota_consumed",
                args=args,
                result_ref=tenant_slug,
                payload_cls=TenantQuotaConsumedPayload,
                rationale="periodic tenant-quota audit emission (SOC-2)",
            )
        except Exception:  # pragma: no cover — best-effort emission
            logger.exception(
                "tenant_quota_consumed emission failed for tenant_slug=%r "
                "(quota enforcement unaffected)",
                payload.get("tenant_slug"),
            )

    return _emit


def is_gather_via_projection_enabled() -> bool:
    """Return True iff ``WORMBASE_GATHER_VIA_PROJECTION`` is truthy.

    v2.B Phase 3c — gates the projection-promoted gather wire on axes
    1 (template promotion) + 3 (bad-pattern). Default OFF preserves
    byte-identical behaviour: axes 1+3 use the existing ledger-scan
    gather (``_make_gather_lookback_outcomes``).

    When ON, axes 1+3 swap to the projection-table read path: a
    ``projection_query_outcomes`` SELECT with the pgvector cosine
    TopK pre-filter (Postgres) or a Python cosine rank (SQLite). The
    reader still honours the same day-window + multi-tenant
    isolation contracts; only the gather mechanism changes.

    Flipping to true requires:

      * Postgres production: v016 + v018 migrations applied; pgvector
        ≥ 0.6 extension installed.
      * Phase 3b's ``WORMBASE_EMBEDDING_ENABLED=true`` recommended so
        the projection rows actually carry embeddings; otherwise the
        reader falls back to non-vector windowed SELECTs (still
        cheaper than a full ledger scan).

    Truthy values: ``"1"``, ``"true"``, ``"yes"`` (case-insensitive).
    """
    return os.environ.get(
        "WORMBASE_GATHER_VIA_PROJECTION", "0",
    ).strip().lower() in ("1", "true", "yes")


def is_gather_via_projection_force_enabled() -> bool:
    """Return True iff ``WORMBASE_GATHER_VIA_PROJECTION_FORCE`` is truthy.

    Carry-forward #1 (2026-05-12) — documented escape hatch for the
    SQLite runtime guard installed by
    :func:`build_projection_reader_from_ledger`. The 2026-05-27
    benchmarks (``docs/superpowers/notes/2026-05-27-perf-baseline.md``)
    measured Path B (projection-promoted gather) on SQLite at ~7.3s for
    N=5000 entries — **2000× slower** than the Path A ledger-scan
    (3.4ms). The guard refuses ``WORMBASE_GATHER_VIA_PROJECTION=true``
    against SQLite engines by default so operators don't silently
    regress 2000×.

    Set this knob to ``true`` only when intentionally bypassing the
    guard — primarily for the benchmark suite itself
    (``tests/perf/test_gather_paths.py``), which measures the SQLite
    cosine path on purpose. Forcing it is logged at WARNING level so
    audit trails capture the override decision.

    Default OFF. Truthy values: ``"1"``, ``"true"``, ``"yes"``
    (case-insensitive).
    """
    return os.environ.get(
        "WORMBASE_GATHER_VIA_PROJECTION_FORCE", "0",
    ).strip().lower() in ("1", "true", "yes")


class GatherViaProjectionUnavailableError(RuntimeError):
    """Raised when ``WORMBASE_GATHER_VIA_PROJECTION=true`` is set against
    a non-Postgres ledger engine.

    Carry-forward #1 (2026-05-12) — operator footgun fix. The 2026-05-27
    benchmarks (``docs/superpowers/notes/2026-05-27-perf-baseline.md``)
    measured Path B (projection-promoted gather) on SQLite at ~7.3s
    for N=5000 entries vs Path A (ledger-scan) at 3.4ms — a 2000×
    regression. The opt-in env knob is safe on Postgres + the v019
    HNSW index, catastrophic on SQLite. This exception fires at
    gateway-composition time so the install refuses to boot rather
    than silently shipping the regressed gather wire.

    Bypass via ``WORMBASE_GATHER_VIA_PROJECTION_FORCE=true`` (logged
    at WARNING) only when the regression is intentional (e.g. the
    benchmark suite itself).
    """


def build_projection_reader_from_ledger(
    ledger: Any,
) -> Any | None:
    """Construct a :class:`QueryOutcomeProjectionReader` for ``ledger``.

    v2.B Phase 3c — opt-in projection-gather wire. Returns:

      * a ``PostgresQueryOutcomeProjectionReader`` (pgvector) when the
        ledger exposes a Postgres ``AsyncEngine``;
      * a ``SqliteQueryOutcomeProjectionReader`` (Python cosine) when
        the ledger exposes a SQLite engine **AND**
        ``WORMBASE_GATHER_VIA_PROJECTION_FORCE=true`` is set
        (escape hatch — see below);
      * ``None`` when the ledger has no engine (e.g. ``InMemoryLedger``).
        The ``InMemoryLedger`` path keeps the ledger-scan gather; the
        projection table doesn't exist there.

    The dialect-aware factory lives in :mod:`wormbase_core.projection_readers`
    so the runtime decision (Postgres vs SQLite) is encapsulated.

    Runtime guard (carry-forward #1, 2026-05-12)
    --------------------------------------------

    When the caller has set ``WORMBASE_GATHER_VIA_PROJECTION=true``
    (checked at the construction site via
    :func:`is_gather_via_projection_enabled`) and the ledger's engine
    dialect is not Postgres, this function raises
    :class:`GatherViaProjectionUnavailableError`. The 2026-05-27
    benchmarks documented at
    ``docs/superpowers/notes/2026-05-27-perf-baseline.md`` measured
    Path B (projection-promoted gather) on SQLite at ~7.3s for
    N=5000 entries — 2000× slower than the default Path A
    ledger-scan (3.4ms). An operator setting the knob against
    SQLite would be silently regressing; refusing the boot is the
    only safe default.

    Operators can bypass the guard by also setting
    ``WORMBASE_GATHER_VIA_PROJECTION_FORCE=true``. The force-override
    emits a WARNING log line so audit trails capture the decision.
    The benchmark suite (``tests/perf/test_gather_paths.py``) is the
    canonical legitimate use case for the override.
    """
    engine = getattr(ledger, "engine", None)
    if engine is None:
        return None
    dialect_name = ""
    try:
        dialect_name = str(getattr(engine.dialect, "name", "") or "")
    except Exception:
        dialect_name = ""
    is_postgres = dialect_name.startswith("postgres")
    if not is_postgres and is_gather_via_projection_enabled():
        if is_gather_via_projection_force_enabled():
            logger.warning(
                "WORMBASE_GATHER_VIA_PROJECTION=true against non-Postgres "
                "ledger (dialect=%r) — guard bypassed via "
                "WORMBASE_GATHER_VIA_PROJECTION_FORCE=true. Path B is "
                "measurably 2000x slower than Path A on SQLite "
                "(see docs/superpowers/notes/2026-05-27-perf-baseline.md). "
                "Proceeding under operator-explicit override.",
                dialect_name or "<unknown>",
            )
        else:
            raise GatherViaProjectionUnavailableError(
                "WORMBASE_GATHER_VIA_PROJECTION=true requires a Postgres "
                "engine with the v019 HNSW index. The current ledger uses "
                f"{dialect_name or '<unknown>'!s}, where projection-promoted "
                "gather is measurably 2000x slower than the default "
                "ledger-scan path (see "
                "docs/superpowers/notes/2026-05-27-perf-baseline.md). "
                "To bypass this guard, unset the env knob "
                "(WORMBASE_GATHER_VIA_PROJECTION) or migrate to Postgres "
                "+ run `make migrate-projection`. For intentional "
                "SQLite measurement (e.g. the benchmark suite itself), "
                "set WORMBASE_GATHER_VIA_PROJECTION_FORCE=true to bypass "
                "this guard; the override is logged at WARNING level."
            )
    from wormbase_core.projection_readers import (
        make_projection_reader_for_engine,
    )
    return make_projection_reader_for_engine(engine)


def resolve_subscription_webhook_timeout_s() -> int:
    """Return webhook request timeout (seconds). Default 10."""
    raw = os.environ.get(
        "WORMBASE_SUBSCRIPTIONS_WEBHOOK_TIMEOUT_S", "",
    ).strip()
    if not raw:
        return 10
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning(
            "WORMBASE_SUBSCRIPTIONS_WEBHOOK_TIMEOUT_S=%r is not an int; "
            "using 10",
            raw,
        )
        return 10


def resolve_subscription_webhook_max_retries() -> int:
    """Return webhook max retries (in addition to the first attempt). Default 3."""
    raw = os.environ.get(
        "WORMBASE_SUBSCRIPTIONS_WEBHOOK_MAX_RETRIES", "",
    ).strip()
    if not raw:
        return 3
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning(
            "WORMBASE_SUBSCRIPTIONS_WEBHOOK_MAX_RETRIES=%r is not an int; "
            "using 3",
            raw,
        )
        return 3


def _make_webhook_secret_resolver(
    broker: Any | None,
) -> Any:
    """Return a secret-resolver callable for WebhookTransport.

    v1.4 #3: defers to the same scheme-aware async resolver that the
    cli-level dispatcher uses. ``env://NAME`` is resolved from the
    host environment; ``vault://path`` reads the ``secret`` key out
    of the broker's KV (EnvCredentialBroker file-store or
    VaultCredentialBroker hvac client). When ``broker`` is None,
    only ``env://`` refs succeed; ``vault://`` refs raise with a
    descriptive error that surfaces as
    ``delivery_status=failed`` on the ledger.

    This dispatcher_deps path is currently a parallel construction
    inside the build smoke (used for test inspection — the wired
    dispatcher in cli.py uses the LazyWebhookSecretResolver
    singleton). Both paths now resolve the same scheme grammar, so
    test seams stay coherent.
    """
    from wormbase_core.webhook_secret_resolver import (
        LazyWebhookSecretResolver,
    )

    resolver = LazyWebhookSecretResolver()
    if broker is not None:
        resolver.bind_broker(broker)
    return resolver


def get_last_dispatcher_deps() -> SubscriptionDispatcherDeps | None:
    """Return the dispatcher deps composed by the most recent
    ``compose_production_agent_gateway_deps`` call.

    cli.py reads this after composing the gateway deps to decide
    whether to pass ``subscription_dispatcher_deps`` to
    ``wire_agent_gateway_for_install``. Same-process posture: one
    composition per boot, so a module-level handoff is sufficient.

    Returns ``None`` when subscriptions were not enabled.
    """
    return getattr(
        compose_production_agent_gateway_deps,
        "_last_dispatcher_deps",
        None,
    )


def is_build_smoke_enabled() -> bool:
    """Return True iff the boot-time build smoke is on. Default ``"1"``.

    Disable via ``WORMBASE_AGENT_GATEWAY_MCP_BUILD_SMOKE=0``.
    """
    return os.environ.get(
        "WORMBASE_AGENT_GATEWAY_MCP_BUILD_SMOKE", "1",
    ).strip().lower() not in ("0", "false", "no", "")


def run_agent_gateway_build_smoke(
    *,
    ledger: Any,
    company_id: UUID,
    install_id: str,
    pii_gate: Any | None = None,
    warmup_gate: Any | None = None,
    interjection_gate: Any | None = None,
    knowledge_gate: Any | None = None,
) -> GatewayBuildSmokeResult:
    """Construct the agent-gateway MCP server at boot.

    The four governance gate kwargs are the v1.2 Item #2 wire-up: when
    cli.py has already built a ``WormCore`` (which constructs PII /
    Warmup / Interjection / Knowledge gates inside
    ``build_worm_core``), it threads them in here so the agent-gateway
    MCP path composes with the same gate instances chat-presence uses.

    Returns :class:`GatewayBuildSmokeResult` so callers can log + test
    the outcome. Raises if construction fails — a failing smoke means
    the worm-core boot is on a code path where the agent-gateway
    package's contract has drifted from the readers, and the install
    should refuse to start rather than silently ship a degraded MCP
    surface.
    """
    deps = compose_production_agent_gateway_deps(
        ledger=ledger,
        company_id=company_id,
        install_id=install_id,
        pii_gate=pii_gate,
        warmup_gate=warmup_gate,
        interjection_gate=interjection_gate,
        knowledge_gate=knowledge_gate,
    )
    server = build_agent_gateway_mcp_server(deps)

    broker_wired = not isinstance(
        deps.broker_executor, _NotYetProductionBrokerExecutor,
    )
    stateful_gates_wired = deps.stateful_gate_bundle is not None
    # v1.3 Item #1: grant_lookup is wired when it is no longer the
    # legacy _empty_grant_lookup. Comparison is by-reference since
    # _make_grant_lookup builds a fresh closure each time.
    grant_lookup_wired = deps.grant_lookup is not _empty_grant_lookup
    # v2.A Batch B Task 5: subscriptions are wired when the env knob
    # was set AND the deps composed successfully.
    subscriptions_wired = deps.subscription_tool_deps is not None
    # v2.B Phase 3b: embedding service is wired when the env knob was
    # set AND the OllamaCloudEmbeddingService was constructed.
    embedding_wired = deps.embedding_service is not None
    # Path 4: tenant_router is wired when the env knob was set AND
    # the InMemoryTenantRouter composed successfully.
    multi_tenant_wired = deps.tenant_router is not None

    pending: list[str] = [
        "catalog_client",
        "catalog_reader",
        "agent_id_resolver",
        "governance_resolver",
    ]
    if not broker_wired:
        pending.extend(["broker_executor", "federate_issuer"])
    if not stateful_gates_wired:
        pending.append("stateful_gate_bundle")
    if not grant_lookup_wired:
        pending.append("grant_lookup")
    if not subscriptions_wired:
        # Not "pending" in the v1.x sense — subscriptions are opt-in by
        # design. Add to the list only so operators see one consolidated
        # boot-status surface (and so the v2.A Batch B 'enabled' state
        # is visible in logs).
        pending.append("subscriptions[opt-in: WORMBASE_SUBSCRIPTIONS_ENABLED]")
    if not embedding_wired:
        # Same opt-in convention as subscriptions — visible in boot
        # logs without being "pending" in the v1.x sense.
        pending.append("embedding[opt-in: WORMBASE_EMBEDDING_ENABLED]")
    if not multi_tenant_wired:
        # Same opt-in convention — single-tenant default.
        pending.append("multi_tenant_mcp[opt-in: WORMBASE_MULTI_TENANT_MCP]")

    resolved_broker = getattr(
        compose_production_agent_gateway_deps, "_last_broker", None,
    )
    return GatewayBuildSmokeResult(
        server=server,
        production_readers_wired=True,
        broker_wired=broker_wired,
        stateful_gates_wired=stateful_gates_wired,
        grant_lookup_wired=grant_lookup_wired,
        pending_deps=tuple(pending),
        subscriptions_wired=subscriptions_wired,
        broker=resolved_broker,
        embedding_wired=embedding_wired,
        multi_tenant_wired=multi_tenant_wired,
    )


# ---------------------------------------------------------------------------
# Item #2 — MCP listener binding (v1.3)
# ---------------------------------------------------------------------------


def is_listener_enabled() -> bool:
    """Return True iff the runtime MCP listener should be started.

    Opt-in via ``WORMBASE_AGENT_GATEWAY_MCP_LISTENER_ENABLED=1`` so
    existing deploys don't inadvertently start a previously-absent
    network surface. The build smoke (``is_build_smoke_enabled``)
    remains the construction-time check; this is the runtime-bind
    check.
    """
    return os.environ.get(
        "WORMBASE_AGENT_GATEWAY_MCP_LISTENER_ENABLED", "0",
    ).strip().lower() in ("1", "true", "yes")


def resolve_listener_transport() -> str:
    """Return ``"stdio"`` or ``"http"`` from the env knob.

    Defaults to ``"stdio"`` — the production path for Claude Desktop
    and other local-MCP-client integrations. HTTP is opt-in via
    ``WORMBASE_AGENT_GATEWAY_MCP_TRANSPORT=http``. The HTTP listener
    is single-tenant by default; multi-tenant routing engages when
    ``WORMBASE_MULTI_TENANT_MCP=true`` (Path 4, 2026-05-21).

    Unknown transport values are coerced to ``"stdio"`` with a warning
    so a typo doesn't crash boot.
    """
    raw = os.environ.get(
        "WORMBASE_AGENT_GATEWAY_MCP_TRANSPORT", "stdio",
    ).strip().lower() or "stdio"
    if raw not in ("stdio", "http"):
        logger.warning(
            "unknown WORMBASE_AGENT_GATEWAY_MCP_TRANSPORT=%r — expected "
            "'stdio' or 'http'; defaulting to 'stdio'", raw,
        )
        return "stdio"
    return raw


def resolve_listener_http_port() -> int:
    """Return the HTTP port for the runtime listener.

    Defaults to 8911 (deliberately distinct from worm-core's MCP
    write-API port 9911 + the HTTP write API). Non-int values warn
    and fall back to the default.
    """
    raw = os.environ.get("WORMBASE_AGENT_GATEWAY_MCP_PORT", "").strip()
    if not raw:
        return 8911
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "WORMBASE_AGENT_GATEWAY_MCP_PORT=%r is not an int; using 8911",
            raw,
        )
        return 8911


def resolve_listener_http_host() -> str:
    """Return the HTTP bind host. Defaults to 127.0.0.1.

    Single-tenant deployment posture: HTTP transport trusts the local
    network perimeter. Set to ``0.0.0.0`` only when the deploy is
    fronted by an authenticating reverse proxy (the v1.3 listener
    itself implements no Authorization-header parsing — that's a v2
    multi-tenant routing concern).
    """
    return os.environ.get(
        "WORMBASE_AGENT_GATEWAY_MCP_HOST", "127.0.0.1",
    ).strip() or "127.0.0.1"


async def run_agent_gateway_mcp_listener(
    server: AgentGatewayMCPServer,
    *,
    transport: str | None = None,
    host: str | None = None,
    port: int | None = None,
) -> None:
    """Run the agent-gateway MCP server as a runtime listener.

    Transport modes (v1.3):

      * ``stdio`` (default) — FastMCP stdio loop for Claude Desktop and
        other local-MCP-client integrations.
      * ``http`` — FastMCP HTTP listener on ``host:port`` (default
        ``127.0.0.1:8911``). Single-tenant by default (the listener
        binds to ONE company_id), OR multi-tenant when
        ``WORMBASE_MULTI_TENANT_MCP=true`` and the
        :class:`TenantRouter` is composed at boot (Path 4, 2026-05-21).
        Deploy behind an authenticating reverse proxy for any
        non-trusted ingress.

    Designed to be wrapped in ``asyncio.create_task`` from cli.py so
    listener failure is isolated from the rest of boot. Any exception
    raised by FastMCP's underlying runner is caught + logged here; the
    coroutine returns cleanly so ``asyncio.gather`` does not propagate
    a hard failure into the worm-core lifecycle.

    Constraints:

      * Single-tenant by default; multi-tenant via Path 4 opt-in
        (``WORMBASE_MULTI_TENANT_MCP=true``). The HTTP path's
        authentication trust model is "local-perimeter or
        reverse-proxy gated".
      * Listener failure does NOT crash worm-core boot. The HTTP
        write API + MCP query_ledger + reactivities loop continue to
        run.
    """
    resolved_transport = transport or resolve_listener_transport()
    try:
        if resolved_transport == "stdio":
            logger.info(
                "agent-gateway MCP listener starting on stdio transport",
            )
            await server.mcp.run_stdio_async(show_banner=False)
        elif resolved_transport == "http":
            resolved_host = host or resolve_listener_http_host()
            resolved_port = port if port is not None else resolve_listener_http_port()
            logger.info(
                "agent-gateway MCP listener starting on http://%s:%d "
                "(single-tenant; install_id=%s)",
                resolved_host, resolved_port, server.deps.install_id,
            )
            await server.mcp.run_http_async(
                show_banner=False,
                host=resolved_host,
                port=resolved_port,
            )
        else:  # defensive — resolve_listener_transport already coerces
            logger.error(
                "agent-gateway MCP listener got unknown transport=%r; "
                "not starting",
                resolved_transport,
            )
    except asyncio.CancelledError:
        # Normal shutdown — re-raise so the surrounding task ends
        # cleanly. asyncio.gather treats CancelledError as a
        # cancellation signal rather than a failure.
        logger.info(
            "agent-gateway MCP listener cancelled (%s) — clean shutdown",
            resolved_transport,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        # Listener failure is failure-isolated per Item #2 contract:
        # log loudly, return cleanly, do NOT propagate. The rest of
        # worm-core (HTTP write API, MCP query_ledger, reactivities)
        # keeps running.
        logger.error(
            "agent-gateway MCP listener (%s) crashed: %s — worm-core "
            "boot continues; restart worm-core to retry listener",
            resolved_transport, exc,
        )


# ---------------------------------------------------------------------------
# v2.B Phase 3 — ClockTickEmitter wiring (opt-in periodic tick daemon)
# ---------------------------------------------------------------------------
#
# Drives the gap-escalation axis (``agent_gateway.gap_to_escalation``)
# via a real cadence-driven tick — Phase 3 swap moved that axis from
# ``EntryKind("semantic_gap_proposed")`` to ``Periodic(every_seconds=N)``
# so escalation does not depend on new-gap traffic.
#
# Default OFF (``WORMBASE_AGENT_GATEWAY_TICK_S`` unset → no emitter
# started). Preserves byte-identical boot behavior on deployments that
# don't configure the env knob.
#
# Multi-tenant note: this construction site runs per-install (one
# emitter per ``company_id``). Multi-tenant orchestration is v2 per
# spec §11; a multi-cadence single-process v2 will compose multiple
# emitters by passing different ``tick_interval_s`` values from
# distinct env knobs.


def resolve_clock_tick_interval_s() -> int | None:
    """Return the configured tick interval in seconds, or ``None`` if disabled.

    Read from ``WORMBASE_AGENT_GATEWAY_TICK_S``. Unset / empty / non-int
    / non-positive values yield ``None`` (emitter not started). A valid
    positive integer (e.g. ``3600`` for hourly) opts into the daemon.

    The Reactivity factory's default (``3600``) is intentionally
    decoupled from this env knob — the factory always carries a
    sane default for tests + in-process construction; the env knob
    governs the production-boot path.
    """
    raw = os.environ.get("WORMBASE_AGENT_GATEWAY_TICK_S", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "WORMBASE_AGENT_GATEWAY_TICK_S=%r is not an int; "
            "ClockTickEmitter will not start",
            raw,
        )
        return None
    if value <= 0:
        logger.warning(
            "WORMBASE_AGENT_GATEWAY_TICK_S=%d is non-positive; "
            "ClockTickEmitter will not start",
            value,
        )
        return None
    return value


def make_clock_tick_emitter_if_configured(
    *,
    ledger: Any,
    company_id: UUID,
    tick_interval_s: int | None = None,
) -> ClockTickEmitter | None:
    """Construct a ``ClockTickEmitter`` if the env knob is set.

    Opt-in by design: when ``tick_interval_s`` is ``None`` (default)
    and ``WORMBASE_AGENT_GATEWAY_TICK_S`` is unset, returns ``None`` so
    callers can no-op the daemon-task wiring without branching.

    Pass ``tick_interval_s`` explicitly to override the env knob (used
    by tests or in-process construction where env-knob-driven boot is
    inappropriate). Tests should not start the emitter daemon
    automatically — call :meth:`ClockTickEmitter.tick_once` directly
    to drive the cadence deterministically.

    Returns the constructed emitter; the caller is responsible for
    spawning ``asyncio.create_task(emitter.run_forever())`` if the
    daemon should run continuously. Following the listener pattern,
    cli.py owns task management — this function is wiring only.
    """
    resolved = (
        tick_interval_s
        if tick_interval_s is not None
        else resolve_clock_tick_interval_s()
    )
    if resolved is None:
        return None
    emitter = ClockTickEmitter(
        ledger=ledger,
        company_id=company_id,
        tick_interval_s=resolved,
    )
    logger.info(
        "ClockTickEmitter constructed: company_id=%s tick_interval_s=%d "
        "(drives agent_gateway.gap_to_escalation axis)",
        company_id, resolved,
    )
    return emitter


# ---------------------------------------------------------------------------
# L3 Sub-wave C — lake-side lineage-discovery wiring
# ---------------------------------------------------------------------------
#
# Wires the Sub-wave B Compounding factory through to the
# ReactivityRegistry at install boot. Default OFF preserves byte-
# identical pre-L3 behaviour: the lineage Reactivity is NOT added to
# the registry. Flipping ``WORMBASE_LINEAGE_DISCOVERY_ENABLED=true``
# composes the inference service + catalog reader and registers a 6th
# (or 7th with subscriptions) Reactivity.
#
# Env knobs (defaults preserve byte-identical pre-L3 behaviour):
#
#   * ``WORMBASE_LINEAGE_DISCOVERY_ENABLED`` (default false) — master
#     switch. When unset / falsy, no inference service is constructed
#     and the lineage Reactivity is not registered.
#   * ``WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED`` (default false) —
#     expensive-strategy gate. When unset / falsy, SampleOverlapStrategy
#     is None on the composite. When true, SampleOverlapStrategy is
#     wired with the NoopSampler honest-stub (real sampling lands in a
#     future wave).
#   * ``WORMBASE_LINEAGE_NAMING_EDIT_DISTANCE_MAX`` (default 2) — edit-
#     distance cap on NamingHeuristicStrategy.
#   * ``WORMBASE_LINEAGE_SAMPLE_OVERLAP_THRESHOLD`` (default 0.5) —
#     Jaccard threshold for SampleOverlapStrategy.
#   * ``WORMBASE_LINEAGE_PROPOSE_WINDOW_SECONDS`` (default 86400) —
#     idempotency dedup window in seconds.
#   * ``WORMBASE_LINEAGE_DAYS_LOOKBACK`` (default 7) — gather_fn
#     window for source_connected / external_catalog_imported scans.


def _is_truthy(raw: str | None) -> bool:
    """Standard truthy check across worm-core env knobs."""
    if not raw:
        return False
    return raw.strip().lower() in ("1", "true", "yes")


def _env_int(name: str, default: int) -> int:
    """Read an int env knob; fall back to ``default`` on absent / invalid."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "%s=%r is not an int; using default %d", name, raw, default,
        )
        return default


def _env_float(name: str, default: float) -> float:
    """Read a float env knob; fall back to ``default`` on absent / invalid."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "%s=%r is not a float; using default %f", name, raw, default,
        )
        return default


def is_sampler_activation_enabled() -> bool:
    """Return True iff ``WORMBASE_SAMPLER_ACTIVATION_ENABLED`` is truthy.

    Default OFF preserves byte-identical pre-Sampler-activation behaviour:
    L3 + L5 + L8 strategies see :class:`NoopSampler` (empty samples, zero
    table sizes) exactly as today. When truthy, the construction sites
    swap in :class:`ConnectorSampler` backed by
    :class:`LedgerSourceHandleProvider`, and per-source sampling becomes
    live against the connector registry.

    Per-source honest-stub posture is preserved: when a source has no
    handle (proposed-but-not-connected / opaque-secret connector kind),
    :class:`ConnectorSampler` returns empty for that source only —
    matches today's per-strategy "no samples" handling rather than
    crashing or globally falling back.
    """
    return _is_truthy(os.environ.get("WORMBASE_SAMPLER_ACTIVATION_ENABLED"))


def _build_credential_broker_for_sampler() -> Any | None:
    """Build a :class:`CredentialBroker` for the sampler path, or return ``None``.

    Sampler-path knob (added 2026-06-10, alongside the CredentialBroker
    integration bundle): ``WORMBASE_CREDENTIAL_BROKER_KIND``
    ∈ ``{vault, env, none}`` (default ``none``).

    Distinct from ``WORMBASE_AGENT_GATEWAY_BROKER_KIND`` (which configures
    the agent-gateway MCP broker executor) on purpose: opaque-secret
    sampler unblock can ship independently of agent-gateway broker
    configuration, and operators may want sampler-only or
    gateway-only broker wiring. When unset / "none", opaque-secret
    connectors stay honest-empty (preserves Sampler activation default-OFF
    byte-identity).

    Env knobs honored:

      * ``WORMBASE_CREDENTIAL_BROKER_KIND`` —
        ``"vault"`` | ``"env"`` | ``"none"`` (default ``"none"``).
      * ``WORMBASE_VAULT_ADDR`` / ``VAULT_ADDR`` —
        required when kind is ``vault``.
      * ``WORMBASE_VAULT_TOKEN`` / ``VAULT_TOKEN`` —
        required when kind is ``vault``.
      * ``WORMBASE_CREDENTIAL_ENV_PREFIX`` — secrets_dir for env kind;
        falls back to ``WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR`` (shared
        with the agent-gateway env-broker knob).

    Returns ``None`` on:
      * kind unset / ``none`` / unknown
      * import failure
      * Vault auth failure
      * env-broker secrets_dir missing

    A debug log records the broker class shipped (or None) so operators
    can verify the wire is up.
    """
    kind = os.environ.get("WORMBASE_CREDENTIAL_BROKER_KIND", "").strip().lower()
    if not kind or kind == "none":
        return None

    if kind == "vault":
        addr = (
            os.environ.get("WORMBASE_VAULT_ADDR")
            or os.environ.get("VAULT_ADDR", "")
        ).strip()
        token = (
            os.environ.get("WORMBASE_VAULT_TOKEN")
            or os.environ.get("VAULT_TOKEN", "")
        ).strip()
        if not addr or not token:
            logger.warning(
                "WORMBASE_CREDENTIAL_BROKER_KIND=vault but "
                "VAULT_ADDR / VAULT_TOKEN are unset; sampler-path "
                "broker defaults to None and opaque-secret connectors "
                "stay honest-empty.",
            )
            return None
        try:
            from wormbase_agent_gateway.credential_broker.vault import (
                VaultCredentialBroker,
            )
            broker = VaultCredentialBroker(addr=addr, token=token)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "sampler-path VaultCredentialBroker construction failed "
                "against %s: %s; defaulting to None", addr, exc,
            )
            return None
        logger.debug("sampler-path CredentialBroker=vault wired")
        return broker

    if kind == "env":
        secrets_dir = (
            os.environ.get("WORMBASE_CREDENTIAL_ENV_PREFIX")
            or os.environ.get("WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR", "")
        ).strip()
        if not secrets_dir:
            logger.warning(
                "WORMBASE_CREDENTIAL_BROKER_KIND=env but "
                "WORMBASE_CREDENTIAL_ENV_PREFIX / "
                "WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR are unset; "
                "sampler-path broker defaults to None.",
            )
            return None
        try:
            from wormbase_agent_gateway.credential_broker.env import (
                EnvCredentialBroker,
            )
            broker = EnvCredentialBroker(secrets_dir=Path(secrets_dir))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "sampler-path EnvCredentialBroker construction failed at "
                "%s: %s; defaulting to None", secrets_dir, exc,
            )
            return None
        logger.debug("sampler-path CredentialBroker=env wired")
        return broker

    logger.warning(
        "unknown WORMBASE_CREDENTIAL_BROKER_KIND=%r (expected 'vault' / "
        "'env' / 'none'); sampler-path broker defaults to None", kind,
    )
    return None


def _build_active_sampler_if_enabled(
    *, ledger: Any, company_id: UUID,
) -> Any:
    """Return :class:`ConnectorSampler` when env-on, else :class:`NoopSampler`.

    Single construction site for the env-knob gate. Called by L3 / L5 /
    L8 compose functions so the policy stays in one place. When the env
    knob is unset the returned NoopSampler is byte-identical to the
    pre-activation default — strategies see empty samples + zero sizes
    exactly as before.

    Tenant scope: the ConnectorSampler instance carries
    ``company_id`` bound at construction time so all subsequent
    ``sample_column`` calls scope ledger reads to this tenant.

    Opaque-secret connector unblock (2026-06-10): when
    ``WORMBASE_CREDENTIAL_BROKER_KIND`` ∈ ``{vault, env}`` is set, a
    :class:`CredentialBroker` is constructed and threaded into
    :class:`LedgerSourceHandleProvider`. Opaque-secret connector kinds
    (stripe, salesforce, hubspot, gsheets) then resolve their handles
    via the broker when ``source_connected.credential_ref`` is set.
    Default-OFF (knob unset / ``none``) preserves byte-identical Sampler
    activation behavior.
    """
    if not is_sampler_activation_enabled():
        return NoopSampler()
    broker = _build_credential_broker_for_sampler()
    install_id = os.environ.get(
        "WORMBASE_CREDENTIAL_BROKER_INSTALL_ID", "",
    ).strip() or None
    handle_provider = LedgerSourceHandleProvider(
        ledger=ledger,
        credential_broker=broker,
        install_id=install_id,
    )
    return ConnectorSampler(
        handle_provider=handle_provider,
        company_id=company_id,
    )


def is_lineage_discovery_enabled() -> bool:
    """Return True iff ``WORMBASE_LINEAGE_DISCOVERY_ENABLED`` is truthy.

    Default OFF preserves byte-identical pre-L3 boot:
    no lineage reactivity is added to the registry.
    """
    return _is_truthy(os.environ.get("WORMBASE_LINEAGE_DISCOVERY_ENABLED"))


def is_lineage_sample_overlap_enabled() -> bool:
    """Return True iff ``WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED`` is truthy."""
    return _is_truthy(
        os.environ.get("WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED"),
    )


def build_lineage_inference_service_from_env() -> (
    CompositeLineageInferenceService | None
):
    """Build the composite per env knobs. Returns None when L3 disabled.

    Env-knob mapping:

      * ``WORMBASE_LINEAGE_DISCOVERY_ENABLED`` — master switch. When
        unset / falsy returns ``None``. The Sub-wave C wire reads this
        return-value to decide whether to register the Compounding
        Reactivity at all.
      * ``WORMBASE_LINEAGE_SAMPLE_OVERLAP_ENABLED`` — when truthy,
        composes :class:`SampleOverlapStrategy` with the NoopSampler
        honest-stub (returns empty samples; strategy yields no edges
        until a real connector-backed sampler lands).
      * ``WORMBASE_LINEAGE_NAMING_EDIT_DISTANCE_MAX`` — edit-distance
        cap on NamingHeuristicStrategy. Default 2.
      * ``WORMBASE_LINEAGE_SAMPLE_OVERLAP_THRESHOLD`` — Jaccard
        threshold for SampleOverlapStrategy. Default 0.5.

    The composite is wired with NamingHeuristic + DbtManifest by
    default (cheap, metadata-only strategies); SampleOverlap is opt-in
    via the second env knob because real sampling has a non-trivial
    cost surface.
    """
    if not is_lineage_discovery_enabled():
        return None

    naming = NamingHeuristicStrategy(
        edit_distance_max=_env_int(
            "WORMBASE_LINEAGE_NAMING_EDIT_DISTANCE_MAX", 2,
        ),
    )

    sample_overlap: SampleOverlapStrategy | None = None
    if is_lineage_sample_overlap_enabled():
        # NoopSampler is the env-build-time default; the
        # ``compose_lineage_reactivity_if_enabled`` wire upgrades the
        # sampler to :class:`ConnectorSampler` when
        # ``WORMBASE_SAMPLER_ACTIVATION_ENABLED=true`` (needs ledger +
        # company_id, which env-build-time doesn't carry). Default-OFF
        # keeps byte-identical pre-activation behaviour: NoopSampler
        # returns empty sets, strategy emits no edges.
        sample_overlap = SampleOverlapStrategy(
            sampler=NoopSampler(),
            jaccard_threshold=_env_float(
                "WORMBASE_LINEAGE_SAMPLE_OVERLAP_THRESHOLD", 0.5,
            ),
        )

    # DbtManifestReader is constructed inside compose_lineage_reactivity_if_enabled
    # because it needs ``ledger`` + ``company_id`` — the strategy is wired
    # at compose-time, not at build-from-env-time, because the env knobs
    # don't carry the tenant identity.
    return CompositeLineageInferenceService(
        naming=naming,
        sample_overlap=sample_overlap,
        # Threaded post-construction by compose_lineage_reactivity_if_enabled.
        dbt_manifest=None,
    )


def compose_lineage_reactivity_if_enabled(
    *,
    ledger: Any,
    company_id: UUID,
) -> Compounding | None:
    """Compose the L3 lineage-discovery Reactivity, or ``None`` if disabled.

    Wires (when ``WORMBASE_LINEAGE_DISCOVERY_ENABLED=true``):

      * :class:`CompositeLineageInferenceService` from env (built via
        :func:`build_lineage_inference_service_from_env`).
      * :class:`DbtManifestStrategy` composed onto the inference service
        post-build (needs ``ledger`` + ``company_id`` for tenant-scoped
        reads — those don't fit the env-only build helper).
      * :class:`LedgerCatalogReader` for table enumeration.
      * ``days_lookback`` + ``propose_window_seconds`` env knobs.

    Default OFF: returns ``None``. Callers (cli.py wire_agent_gateway
    composition) check the return value and only register the
    Reactivity when it is non-None, preserving byte-identical pre-L3
    reactivity count + behaviour.

    Tenant isolation: ``company_id`` is captured in the
    LedgerDbtManifestReader so the strategy's ledger fetches are
    tenant-scoped. The LedgerCatalogReader takes company_id per-call
    via the lineage Protocol's signature.
    """
    inference_service = build_lineage_inference_service_from_env()
    if inference_service is None:
        return None

    # Wire DbtManifestStrategy onto the composite. Done here (not in
    # build_lineage_inference_service_from_env) because the
    # DbtManifestReader needs ``ledger`` + ``company_id`` for tenant-
    # scoped reads.
    manifest_reader = LedgerDbtManifestReader(
        ledger=ledger, company_id=company_id,
    )
    inference_service.dbt_manifest = DbtManifestStrategy(
        manifest_reader=manifest_reader,
    )

    # Sampler activation Wave: when ``WORMBASE_SAMPLER_ACTIVATION_ENABLED=true``,
    # swap the SampleOverlapStrategy's NoopSampler for a tenant-scoped
    # ConnectorSampler. Default-OFF: the NoopSampler from
    # build_lineage_inference_service_from_env stays in place →
    # byte-identical pre-activation behaviour.
    if (
        inference_service.sample_overlap is not None
        and is_sampler_activation_enabled()
    ):
        inference_service.sample_overlap.sampler = (
            _build_active_sampler_if_enabled(
                ledger=ledger, company_id=company_id,
            )
        )

    catalog_reader = LedgerCatalogReader(ledger=ledger)

    propose_window_s = _env_int(
        "WORMBASE_LINEAGE_PROPOSE_WINDOW_SECONDS", 86400,
    )
    days_lookback = _env_int("WORMBASE_LINEAGE_DAYS_LOOKBACK", 7)

    reactivity = make_lineage_discovery_reactivity(
        inference_service=inference_service,
        catalog_reader=catalog_reader,
        days_lookback=days_lookback,
        propose_window_seconds=propose_window_s,
    )
    logger.info(
        "L3 lineage-discovery composed: naming=on dbt_manifest=on "
        "sample_overlap=%s days_lookback=%d propose_window_s=%d",
        "on(noop_sampler)" if inference_service.sample_overlap else "off",
        days_lookback,
        propose_window_s,
    )
    return reactivity


# ---------------------------------------------------------------------------
# L7 lake-side quality-check discovery — env-driven construction (Sub-wave C).
#
# Mirrors the L3 lake-side lineage-discovery construction site. The
# Compounding factory composes a CompositeQualityProposalService over
# any subset of three strategies (SchemaPattern, DbtTests,
# HistoricalStats) via Optional-Effect Injection (doctrine case 10).
#
# Default OFF (``WORMBASE_QUALITY_DISCOVERY_ENABLED`` unset / falsy)
# preserves byte-identical pre-L7 boot: no inference service is
# constructed, no Reactivity is added to the registry, reactivity
# count + behaviour unchanged.
#
# When enabled the composite adds one more Reactivity to the registry —
# yielding 6 default + lineage (L3 if enabled) + quality (L7) = 7
# default, or up to 9 when L3 + L7 + subscriptions are all enabled.
#
# Env knobs (defaults per spec §3.9):
#
#   * ``WORMBASE_QUALITY_DISCOVERY_ENABLED`` (default false) — master
#     switch. When unset / falsy, no inference service is constructed
#     and the quality Reactivity is not registered.
#   * ``WORMBASE_QUALITY_HISTORICAL_STATS_ENABLED`` (default false) —
#     stubbed-strategy gate. When unset / falsy,
#     HistoricalStatsStrategy is None on the composite. When true,
#     HistoricalStatsStrategy is wired with the
#     NoopHistoricalStatsReader honest-stub (real column-level stats
#     reading requires a future catalog-mirror payload).
#   * ``WORMBASE_QUALITY_FRESHNESS_DEFAULT_HOURS`` (default 24) —
#     default freshness threshold for SchemaPattern proposals
#     (config = ``{"max_age_hours": <N>}``).
#   * ``WORMBASE_QUALITY_PROPOSE_WINDOW_SECONDS`` (default 86400) —
#     idempotency dedup window in seconds.
#   * ``WORMBASE_QUALITY_LOW_CARDINALITY_MAX`` (default 10) — max
#     distinct values for enum_membership proposals.


def is_quality_discovery_enabled() -> bool:
    """Return True iff ``WORMBASE_QUALITY_DISCOVERY_ENABLED`` is truthy.

    Default OFF preserves byte-identical pre-L7 boot:
    no quality reactivity is added to the registry.
    """
    return _is_truthy(os.environ.get("WORMBASE_QUALITY_DISCOVERY_ENABLED"))


def is_quality_historical_stats_enabled() -> bool:
    """Return True iff ``WORMBASE_QUALITY_HISTORICAL_STATS_ENABLED`` is truthy.

    Default OFF wires the composite WITHOUT HistoricalStatsStrategy —
    the strategy is structurally complete but its underlying catalog-
    mirror stats payload is Wave-1-future, so opt-in only.
    """
    return _is_truthy(
        os.environ.get("WORMBASE_QUALITY_HISTORICAL_STATS_ENABLED"),
    )


def is_quality_semantic_type_enabled() -> bool:
    """Return True iff ``WORMBASE_QUALITY_SEMANTIC_TYPE_ENABLED`` is truthy.

    Default OFF wires the composite WITHOUT
    :class:`SemanticTypeQualityCheckStrategy` — the cross-axis L5→L7
    strategy is opt-in so the L7 axis stays byte-identical to its
    pre-cross-axis behaviour until operators flip the sub-knob.

    The L5→L7 cross-axis chain is the **4th** in the lake-side stack
    (after L4→L3, L6→L5, L8→L5). It reads L5's confirmed semantic
    types via the **reused** L6
    :class:`ConfirmedSemanticTypeReader` Protocol (3rd consumer of the
    same Protocol — L6 is 1st, L8 is 2nd, L7 is 3rd) and proposes
    canonical not_null + unique checks based on the semantic type
    (``email`` / ``uuid`` / ``business_id`` → not_null+unique;
    ``phone`` / ``pii_name`` → not_null only).
    """
    return _is_truthy(
        os.environ.get("WORMBASE_QUALITY_SEMANTIC_TYPE_ENABLED"),
    )


def build_quality_proposal_service_from_env() -> (
    CompositeQualityProposalService | None
):
    """Build the composite per env knobs. Returns None when L7 disabled.

    Env-knob mapping:

      * ``WORMBASE_QUALITY_DISCOVERY_ENABLED`` — master switch. When
        unset / falsy returns ``None``. The
        :func:`compose_quality_reactivity_if_enabled` wire reads this
        return-value to decide whether to register the Compounding
        Reactivity at all (byte-identical pre-L7 boot when disabled).
      * ``WORMBASE_QUALITY_HISTORICAL_STATS_ENABLED`` — when truthy,
        composes :class:`HistoricalStatsStrategy` with the
        :class:`NoopHistoricalStatsReader` honest-stub (returns empty
        snapshot lists; strategy yields no checks until a real
        catalog-mirror stats payload lands in a future wave).
      * ``WORMBASE_QUALITY_FRESHNESS_DEFAULT_HOURS`` — freshness
        default for SchemaPattern. Default 24.
      * ``WORMBASE_QUALITY_LOW_CARDINALITY_MAX`` — max distinct values
        for enum_membership proposals from SchemaPattern. Default 10.

    The composite is wired with SchemaPattern + DbtTests by default
    (cheap, metadata-only strategies); HistoricalStats is opt-in via
    the second env knob because its underlying catalog-mirror stats
    payload is not yet live (honest-stub posture is auditable per
    Rule 9).

    DbtTestsStrategy receives a sentinel
    :class:`LedgerDbtTestReader` placeholder here; the real reader
    needs ``ledger`` + ``company_id`` for tenant-scoped reads and is
    wired post-build in
    :func:`compose_quality_reactivity_if_enabled`. We pass a None-
    backed stub at build time and replace it at compose time. This
    mirrors the L3 DbtManifestStrategy pattern.
    """
    if not is_quality_discovery_enabled():
        return None

    schema_pattern = SchemaPatternStrategy(
        freshness_default_hours=_env_int(
            "WORMBASE_QUALITY_FRESHNESS_DEFAULT_HOURS", 24,
        ),
        low_cardinality_max=_env_int(
            "WORMBASE_QUALITY_LOW_CARDINALITY_MAX", 10,
        ),
    )

    # DbtTestsStrategy needs a DbtTestReader; that requires ledger +
    # company_id which the env-only build helper doesn't carry. We
    # construct the strategy with a None-backed placeholder here and
    # replace it in compose_quality_reactivity_if_enabled — same
    # pattern as DbtManifestStrategy in L3.
    dbt_tests: DbtTestsStrategy | None = None  # threaded at compose-time.

    historical_stats: HistoricalStatsStrategy | None = None
    if is_quality_historical_stats_enabled():
        # NoopHistoricalStatsReader is the honest-stub today; real
        # historical-stats reading requires the Wave 1 catalog mirror
        # to emit column-level statistical snapshots (future wave).
        # Operators see the strategy fire telemetry counter but no
        # checks materialise until then.
        historical_stats = HistoricalStatsStrategy(
            reader=NoopHistoricalStatsReader(),
        )

    return CompositeQualityProposalService(
        schema_pattern=schema_pattern,
        # Threaded post-construction by compose_quality_reactivity_if_enabled.
        dbt_tests=dbt_tests,
        historical_stats=historical_stats,
    )


def compose_quality_reactivity_if_enabled(
    *,
    ledger: Any,
    company_id: UUID,
) -> Compounding | None:
    """Compose the L7 quality-discovery Reactivity, or ``None`` if disabled.

    Wires (when ``WORMBASE_QUALITY_DISCOVERY_ENABLED=true``):

      * :class:`CompositeQualityProposalService` from env (built via
        :func:`build_quality_proposal_service_from_env`).
      * :class:`DbtTestsStrategy` composed onto the inference service
        post-build (needs ``ledger`` + ``company_id`` for tenant-
        scoped reads — those don't fit the env-only build helper).
      * :class:`LedgerCatalogReader` for table enumeration (reused
        from L3 — both axes consume the same catalog reader
        Protocol, so we instantiate once).
      * ``propose_window_seconds`` env knob.

    Default OFF: returns ``None``. Callers (cli.py wire_agent_gateway
    composition) check the return value and only register the
    Reactivity when it is non-None, preserving byte-identical pre-L7
    reactivity count + behaviour.

    Reactivity ordering: this is composed + registered AFTER L3 in
    ``cli._run_async`` so telemetry counters indexing by Reactivity
    position stay stable. When L7 is enabled and L3 is also enabled,
    the registry holds 6 default + L3 + L7 = 8 Reactivities (or 9
    with subscriptions).

    Tenant isolation: ``company_id`` is captured in the
    :class:`LedgerDbtTestReader` so the strategy's ledger fetches are
    tenant-scoped. The :class:`LedgerCatalogReader` takes company_id
    per-call via the Compounding factory's gather_fn signature.
    """
    proposal_service = build_quality_proposal_service_from_env()
    if proposal_service is None:
        return None

    # Wire DbtTestsStrategy onto the composite. Done here (not in
    # build_quality_proposal_service_from_env) because the
    # DbtTestReader needs ``ledger`` + ``company_id`` for tenant-
    # scoped reads.
    test_reader = LedgerDbtTestReader(
        ledger=ledger, company_id=company_id,
    )
    proposal_service.dbt_tests = DbtTestsStrategy(
        manifest_reader=test_reader,
    )

    # L5→L7 cross-axis chain — 4th cross-axis chain in the lake-side
    # stack (after L4→L3, L6→L5, L8→L5). Wired at compose-time (not
    # env-build-time) because the reader needs ``ledger`` for the
    # cross-axis read into L5's projection_semantic_types.
    #
    # **Reuses** :class:`LedgerConfirmedSemanticTypeReader` (added by
    # L6 Sub-wave C, reused by L8 Sub-wave C, reused by L7 here —
    # **3rd consumer** of the same concrete adapter; no new adapter
    # added). The reader is shared with the L6 column-classification
    # wire (constructed independently — instances may differ but the
    # Protocol surface is identical).
    if is_quality_semantic_type_enabled():
        semantic_type_reader = LedgerConfirmedSemanticTypeReader(
            ledger=ledger,
        )
        proposal_service.semantic_type = SemanticTypeQualityCheckStrategy(
            confirmed_semantic_type_reader=semantic_type_reader,
        )

    catalog_reader = LedgerCatalogReader(ledger=ledger)

    propose_window_s = _env_int(
        "WORMBASE_QUALITY_PROPOSE_WINDOW_SECONDS", 86400,
    )

    reactivity = make_quality_discovery_reactivity(
        proposal_service=proposal_service,
        catalog_reader=catalog_reader,
        propose_window_seconds=propose_window_s,
    )
    logger.info(
        "L7 quality-discovery composed: schema_pattern=on dbt_tests=on "
        "historical_stats=%s semantic_type=%s propose_window_s=%d",
        (
            "on(noop_stats_reader)"
            if proposal_service.historical_stats
            else "off"
        ),
        "on(L5_cross_axis)" if proposal_service.semantic_type else "off",
        propose_window_s,
    )
    return reactivity


# ---------------------------------------------------------------------------
# L4 Sub-wave C (2026-06-02) — lake-side schema-evolution-impact discovery —
# env-driven construction.
#
# Mirrors the L3 + L7 axis construction shape with two architectural
# additions:
#
#   * The composite consumes a NEW cross-axis Protocol —
#     :class:`LineageEdgeReader` (defined in
#     ``wormbase-agent-gateway/schema_impact/protocol.py``) — the first
#     instance of an axis reading another axis's projection. The
#     concrete impl is :class:`LedgerLineageEdgeReader` (in
#     ``schema_impact_lineage_reader.py``).
#   * A single shared LedgerLineageEdgeReader instance is constructed
#     here and threaded into BOTH the LineageEdgeImpactStrategy AND the
#     TypeCoercionImpactStrategy (Sub-wave B handoff concern #5).
#
# Default OFF (``WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED`` unset /
# falsy) preserves byte-identical pre-L4 boot: no inference service is
# constructed, no Reactivity is added to the registry, reactivity
# count + behaviour unchanged.
#
# When enabled the composite adds one more Reactivity to the registry —
# yielding 5 default + L3 (if on) + L7 (if on) + L4 = up to 8 default,
# or 9 with subscriptions.
#
# Env knobs (defaults per spec §3.7):
#
#   * ``WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED`` (default false) —
#     master switch. When unset / falsy, no inference service is
#     constructed and the schema-impact Reactivity is not registered.
#   * ``WORMBASE_SCHEMA_IMPACT_DBT_TEST_ENABLED`` (default false) —
#     stubbed-strategy gate. When unset / falsy,
#     DbtTestImpactStrategy is None on the composite. When true, the
#     strategy is wired with the L7 :class:`LedgerDbtTestReader`
#     (reused — the dbt-test signal surface is identical across L7
#     and L4). The reader stays honest-stub today (returns [] until
#     Wave 1 catalog mirror emits per-model dbt tests).
#   * ``WORMBASE_SCHEMA_IMPACT_PROPOSE_WINDOW_SECONDS`` (default 86400)
#     — per-impact dedup window in seconds.
#   * ``WORMBASE_SCHEMA_IMPACT_MIN_CONFIDENCE`` (default 0.5) — minimum
#     confidence floor for proposals (below this, the composite silently
#     skips); read here and stored for future composite filtering.
#   * ``WORMBASE_SCHEMA_IMPACT_INCLUDE_NAMING_LINEAGE`` (default false)
#     — whether to propagate impacts from naming-heuristic /
#     sample-overlap edges (in addition to dbt-manifest). Default off
#     keeps L4's false-positive rate low.


def is_schema_impact_discovery_enabled() -> bool:
    """Return True iff ``WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED`` is truthy.

    Default OFF preserves byte-identical pre-L4 boot: no schema-impact
    reactivity is added to the registry.
    """
    return _is_truthy(
        os.environ.get("WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED"),
    )


def is_schema_impact_dbt_test_enabled() -> bool:
    """Return True iff ``WORMBASE_SCHEMA_IMPACT_DBT_TEST_ENABLED`` is truthy.

    Default OFF wires the composite WITHOUT DbtTestImpactStrategy — the
    strategy is structurally complete but its underlying ledger-mirrored
    dbt-test payload is Wave-1-future, so opt-in only.
    """
    return _is_truthy(
        os.environ.get("WORMBASE_SCHEMA_IMPACT_DBT_TEST_ENABLED"),
    )


def is_schema_impact_naming_lineage_enabled() -> bool:
    """Return True iff ``WORMBASE_SCHEMA_IMPACT_INCLUDE_NAMING_LINEAGE`` is truthy.

    Default OFF: only dbt-manifest L3 edges feed L4 impact propagation.
    When true, naming-heuristic + sample-overlap edges also propagate
    (higher recall, higher false-positive rate).
    """
    return _is_truthy(
        os.environ.get("WORMBASE_SCHEMA_IMPACT_INCLUDE_NAMING_LINEAGE"),
    )


def is_schema_impact_governance_enabled() -> bool:
    """Return True iff ``WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED`` is truthy.

    Default OFF wires the composite WITHOUT
    :class:`GovernanceClassificationImpactStrategy` — the cross-axis L6→L4
    strategy is opt-in so the L4 axis stays byte-identical to its
    pre-cross-axis behaviour until operators flip the sub-knob.

    The L6→L4 cross-axis chain is the **5th** in the lake-side stack
    (after L4→L3, L6→L5, L8→L5, L5→L7). It reads L6's confirmed
    column-level classifications via the **NEW** L6-owned
    :class:`ConfirmedClassificationReader` Protocol (1st producer-side
    cross-axis Protocol — L6's :class:`ConfirmedSemanticTypeReader`
    Protocol is consumer-side on the L5 domain) and proposes
    severity-elevated impact entries when a schema change touches a
    column confirmed as ``regulated`` / ``pii`` / ``confidential``.

    Severity mapping (per spec):
      regulated   → critical (compliance review path)
      pii         → high (privacy review path)
      confidential → high (internal-only review path)
      internal    → no proposal (informational only)
      public      → no proposal (not governance-sensitive)
    """
    return _is_truthy(
        os.environ.get("WORMBASE_SCHEMA_IMPACT_GOVERNANCE_ENABLED"),
    )


def is_schema_impact_semantic_type_enabled() -> bool:
    """Return True iff ``WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED`` is truthy.

    Default OFF wires the composite WITHOUT
    :class:`SemanticTypeImpactStrategy` — the cross-axis L5→L4 strategy
    is opt-in so the L4 axis stays byte-identical to its pre-cross-axis
    behaviour until operators flip the sub-knob.

    The L5→L4 cross-axis chain is the **6th** in the lake-side stack
    (after L4→L3, L6→L5, L8→L5, L5→L7, L6→L4) and the **last of the
    three originally-foreshadowed peer-axis chains**. It reuses L6's
    :class:`ConfirmedSemanticTypeReader` Protocol (4th consumer after
    L6, L8, L7) and its concrete impl
    :class:`LedgerConfirmedSemanticTypeReader` (4th consumer of the
    same adapter) — 0 new Protocol, 0 new adapter, 0 KIND_REGISTRY
    entries.

    The strategy elevates impact severity to ``high`` (carried in
    ``evidence.semantic_type_severity``) whenever a schema change
    touches a column with an L5-confirmed semantic type. The strategy
    is type-agnostic in Wave 1 — any confirmed type triggers; the
    specific value (``email`` / ``uuid`` / ``phone`` / ``pii_name`` /
    custom) goes into ``evidence.semantic_type`` for the dashboard
    chip + cross-axis row link.
    """
    return _is_truthy(
        os.environ.get("WORMBASE_SCHEMA_IMPACT_SEMANTIC_TYPE_ENABLED"),
    )


def is_schema_impact_acknowledged_drift_enabled() -> bool:
    """Return True iff ``WORMBASE_SCHEMA_IMPACT_ACKNOWLEDGED_DRIFT_ENABLED`` is truthy.

    Default OFF wires the composite WITHOUT
    :class:`AcknowledgedDriftImpactStrategy` — the cross-axis L4↦L2
    strategy is opt-in so the L4 axis stays byte-identical to its pre-
    chain behaviour until operators flip the sub-knob.

    The L4↦L2 cross-axis chain is the **7th** in the lake-side stack
    (after L4→L3, L6→L5, L8→L5, L5→L7, L6→L4, L5→L4) and the **FIRST
    bidirectional chain**: L4 elevates impacts on L2-acknowledged
    drifts (forward — this strategy); the L2 dashboard surfaces
    downstream-impact roll-up counts per drift row (reverse — Half B,
    dashboard-only with no env knob required).

    Adds **1 NEW Protocol** on L2 (:class:`AcknowledgedDriftReader` —
    L2's first peer-axis producer-side Protocol; CatalogSnapshotReader
    was platform-substrate) AND **1 NEW Adapter** in worm-core
    (:class:`LedgerAcknowledgedDriftReader`). 0 new KIND_REGISTRY
    entries (reuses existing L2 catalog_drift_* kinds + L4
    schema_impact_* kinds).

    The strategy elevates impact severity to ``high`` (carried in
    ``evidence.acknowledged_drift_severity``) whenever a schema change
    touches a column with an L2-acknowledged catalog drift. The
    strategy is kind-agnostic in Wave 1 — any acknowledged drift
    triggers; the specific drift_kind (``column_added`` /
    ``column_type_changed`` / etc.) goes into ``evidence.drift_kind``
    for the dashboard chip + cross-axis row link.
    """
    return _is_truthy(
        os.environ.get("WORMBASE_SCHEMA_IMPACT_ACKNOWLEDGED_DRIFT_ENABLED"),
    )


def build_schema_impact_service_from_env(
    *, ledger: Any,
) -> CompositeSchemaImpactService | None:
    """Build the composite per env knobs. Returns None when L4 disabled.

    Env-knob mapping:

      * ``WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED`` — master switch.
        When unset / falsy returns ``None``. The
        :func:`compose_schema_impact_reactivity_if_enabled` wire reads
        this return-value to decide whether to register the Compounding
        Reactivity at all (byte-identical pre-L4 boot when disabled).
      * ``WORMBASE_SCHEMA_IMPACT_DBT_TEST_ENABLED`` — when truthy,
        composes :class:`DbtTestImpactStrategy` with the L7
        :class:`LedgerDbtTestReader` (reused — the dbt-test signal
        surface is identical across L7 and L4).
      * ``WORMBASE_SCHEMA_IMPACT_INCLUDE_NAMING_LINEAGE`` — controls
        whether the :class:`LineageEdgeImpactStrategy` propagates
        impacts from naming-heuristic / sample-overlap L3 edges
        (default false: dbt-manifest-only).

    The composite is wired with LineageEdge (always — primary productive
    strategy) + TypeCoercion (always — degrades to no-op without
    downstream targets); DbtTest is opt-in via the second env knob
    because its underlying catalog-mirror dbt-test payload is not yet
    live.

    Shared LineageEdgeReader (concern #5): a single
    :class:`LedgerLineageEdgeReader` instance is constructed here and
    threaded into BOTH the LineageEdge strategy AND the TypeCoercion
    strategy. Both strategies see the same cross-axis read surface; no
    duplicate construction. The reader is stateless across calls so
    sharing is safe.

    Tenant scope rides on company_id per-strategy-call (the Protocol's
    signature carries it), not on the reader's construction — same
    pattern as the L3 LedgerCatalogReader.
    """
    if not is_schema_impact_discovery_enabled():
        return None

    # Build the shared LineageEdgeReader instance ONCE; thread into both
    # cross-axis-reading strategies (concern #5).
    lineage_edge_reader = LedgerLineageEdgeReader(ledger=ledger)

    lineage_edge = LineageEdgeImpactStrategy(
        lineage_edge_reader=lineage_edge_reader,
        include_naming_lineage=is_schema_impact_naming_lineage_enabled(),
        # Default 0.85 per Sub-wave B; the
        # WORMBASE_SCHEMA_IMPACT_MIN_CONFIDENCE env knob applies a
        # composite-level floor at promotion time (read below for
        # future routing).
        min_edge_confidence=0.85,
    )

    dbt_test: DbtTestImpactStrategy | None = None
    if is_schema_impact_dbt_test_enabled():
        # Reuse L7's LedgerDbtTestReader. Tenant scope is captured at
        # construction time per the L7 reader's signature; we don't have
        # company_id here, so we defer dbt_test construction to compose
        # time (mirrors L7's dbt_tests pattern in
        # build_quality_proposal_service_from_env).
        # Sentinel here: actual construction happens in
        # compose_schema_impact_reactivity_if_enabled where company_id
        # is in scope.
        dbt_test = None  # threaded at compose-time

    type_coercion = TypeCoercionImpactStrategy(
        lineage_edge_reader=lineage_edge_reader,
    )

    # Capture min_confidence env knob; the Sub-wave B composite does
    # not currently consume a global min-confidence (strategies apply
    # their own confidence factors). The knob is read here for forward
    # compatibility — a future Sub-wave can extend the composite to
    # filter at promotion time.
    _ = _env_float("WORMBASE_SCHEMA_IMPACT_MIN_CONFIDENCE", 0.5)

    return CompositeSchemaImpactService(
        lineage_edge=lineage_edge,
        dbt_test=dbt_test,
        type_coercion=type_coercion,
    )


def compose_schema_impact_reactivity_if_enabled(
    *,
    ledger: Any,
    company_id: UUID,
) -> Compounding | None:
    """Compose the L4 schema-impact discovery Reactivity, or ``None`` if disabled.

    Wires (when ``WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED=true``):

      * :class:`CompositeSchemaImpactService` from env (built via
        :func:`build_schema_impact_service_from_env`).
      * :class:`DbtTestImpactStrategy` composed onto the inference
        service post-build when ``WORMBASE_SCHEMA_IMPACT_DBT_TEST_ENABLED``
        is true (needs ``ledger`` + ``company_id`` for tenant-scoped
        L7 :class:`LedgerDbtTestReader` reads).
      * :class:`LedgerCatalogReader` for catalog enumeration (reused
        from L3 — both L3 and L4 consume the same catalog reader
        Protocol structurally, so we instantiate once).
      * ``propose_window_seconds`` env knob.

    Default OFF: returns ``None``. Callers (cli.py wire_agent_gateway
    composition) check the return value and only register the
    Reactivity when it is non-None, preserving byte-identical pre-L4
    reactivity count + behaviour.

    Reactivity ordering: this is composed + registered AFTER L7 in
    ``cli._run_async`` (per Sub-wave B handoff concern) so telemetry
    counters indexing by Reactivity position stay stable. When L4 is
    enabled and L3 + L7 are also enabled, the registry holds 5 default
    + L3 + L7 + L4 = 8 Reactivities (or 9 with subscriptions).

    Tenant isolation: ``company_id`` is captured in the
    :class:`LedgerDbtTestReader` (when DBT_TEST is enabled) so the
    strategy's ledger fetches are tenant-scoped. The
    :class:`LedgerLineageEdgeReader` takes company_id per-call via the
    cross-axis Protocol's signature; the
    :class:`LedgerCatalogReader` takes company_id per-call via the
    Compounding factory's gather_fn signature.
    """
    impact_service = build_schema_impact_service_from_env(ledger=ledger)
    if impact_service is None:
        return None

    # Wire DbtTestImpactStrategy onto the composite when its env knob
    # is set. Done here (not in build_schema_impact_service_from_env)
    # because LedgerDbtTestReader needs ``ledger`` + ``company_id``
    # for tenant-scoped reads.
    if is_schema_impact_dbt_test_enabled():
        test_reader = LedgerDbtTestReader(
            ledger=ledger, company_id=company_id,
        )
        impact_service.dbt_test = DbtTestImpactStrategy(
            test_reader=test_reader,
        )

    # L6→L4 cross-axis chain — 5th cross-axis chain in the lake-side
    # stack (after L4→L3, L6→L5, L8→L5, L5→L7). Wired at compose-time
    # (not env-build-time) because the reader needs ``ledger`` for the
    # cross-axis read into L6's projection_column_classifications.
    #
    # Uses the **NEW** L6-owned :class:`ConfirmedClassificationReader`
    # Protocol — first producer-side cross-axis Protocol in the lake
    # stack (L6's :class:`ConfirmedSemanticTypeReader` is consumer-side
    # on the L5 domain). Concrete impl is
    # :class:`LedgerConfirmedClassificationReader` in worm-core.
    if is_schema_impact_governance_enabled():
        confirmed_classification_reader = LedgerConfirmedClassificationReader(
            ledger=ledger,
        )
        impact_service.governance_classification = (
            GovernanceClassificationImpactStrategy(
                confirmed_classification_reader=(
                    confirmed_classification_reader
                ),
            )
        )

    # L5→L4 cross-axis chain — 6th cross-axis chain in the lake-side
    # stack (after L4→L3, L6→L5, L8→L5, L5→L7, L6→L4), the **last of
    # the 3 originally-foreshadowed peer-axis chains**. Wired at
    # compose-time (not env-build-time) because the reader needs
    # ``ledger`` for the cross-axis read into L5's
    # projection_semantic_types.
    #
    # **Reuses** :class:`LedgerConfirmedSemanticTypeReader` (added by
    # L6 Sub-wave C, reused by L8 Sub-wave C, reused by L7 in the
    # L5→L7 chain — **4th consumer** of the same concrete adapter; no
    # new adapter added). 0 new Protocol, 0 new adapter, 0
    # KIND_REGISTRY entries. The reader instance constructed here is
    # independent from the L6 / L7 instances; the Protocol surface is
    # identical, so each wire constructs its own reader for clean
    # ownership.
    if is_schema_impact_semantic_type_enabled():
        confirmed_semantic_type_reader = LedgerConfirmedSemanticTypeReader(
            ledger=ledger,
        )
        impact_service.semantic_type = SemanticTypeImpactStrategy(
            confirmed_semantic_type_reader=confirmed_semantic_type_reader,
        )

    # L4↦L2 cross-axis chain — 7th cross-axis chain in the lake-side
    # stack (after L4→L3, L6→L5, L8→L5, L5→L7, L6→L4, L5→L4) and the
    # **FIRST bidirectional chain**: L4 elevates impacts on L2-
    # acknowledged drifts (forward — this strategy); the L2 dashboard
    # surfaces downstream-impact roll-up counts in reverse (Half B,
    # dashboard-only).
    #
    # Wired at compose-time (not env-build-time) because the reader
    # needs ``ledger`` for the cross-axis read into L2's
    # projection_catalog_drifts.
    #
    # Uses the **NEW** L2-owned :class:`AcknowledgedDriftReader`
    # Protocol — L2's first producer-side peer-axis Protocol
    # (CatalogSnapshotReader was platform-substrate). Concrete impl is
    # :class:`LedgerAcknowledgedDriftReader` in worm-core (NEW adapter).
    # 0 new KIND_REGISTRY entries (reuses L2 catalog_drift_* kinds + L4
    # schema_impact_* kinds).
    if is_schema_impact_acknowledged_drift_enabled():
        acknowledged_drift_reader = LedgerAcknowledgedDriftReader(
            ledger=ledger,
        )
        impact_service.acknowledged_drift = (
            AcknowledgedDriftImpactStrategy(
                acknowledged_drift_reader=acknowledged_drift_reader,
            )
        )

    # Reuse L3's LedgerCatalogReader for catalog enumeration. Both L3
    # and L4 consume the same catalog reader Protocol structurally;
    # one instance per boot wire avoids duplicate construction.
    catalog_reader = LedgerCatalogReader(ledger=ledger)

    propose_window_s = _env_int(
        "WORMBASE_SCHEMA_IMPACT_PROPOSE_WINDOW_SECONDS", 86400,
    )

    reactivity = make_schema_impact_discovery_reactivity(
        impact_service=impact_service,
        catalog_reader=catalog_reader,
        propose_window_seconds=propose_window_s,
    )
    logger.info(
        "L4 schema-impact discovery composed: lineage_edge=on "
        "dbt_test=%s type_coercion=on naming_lineage=%s "
        "governance_classification=%s semantic_type=%s "
        "acknowledged_drift=%s "
        "propose_window_s=%d",
        "on" if impact_service.dbt_test is not None else "off",
        "on" if is_schema_impact_naming_lineage_enabled() else "off",
        (
            "on(L6_cross_axis)"
            if impact_service.governance_classification is not None
            else "off"
        ),
        (
            "on(L5_cross_axis)"
            if impact_service.semantic_type is not None
            else "off"
        ),
        (
            "on(L2_cross_axis_bidirectional)"
            if impact_service.acknowledged_drift is not None
            else "off"
        ),
        propose_window_s,
    )
    return reactivity


# ---------------------------------------------------------------------------
# L5 Sub-wave C (2026-06-05) — lake-side semantic-type fingerprinting —
# env-driven construction.
#
# Mirrors the L3 + L7 + L4 axis construction shape. L5 is the **first
# lake-side axis to use :class:`LakeLoopComposite` from day one** — the
# composite is built via :func:`make_composite_semantic_type_service`,
# which returns a parameterised
# :class:`LakeLoopComposite[ProposedSemanticType]` instead of a custom
# composite class. No new reader Protocols are added; the data-reading
# strategies reuse L3's :class:`SamplerProtocol` (via
# :class:`NoopSampler`) and L7's :class:`HistoricalStatsReader` (via
# :class:`NoopHistoricalStatsReader`).
#
# Default OFF (``WORMBASE_FINGERPRINT_DISCOVERY_ENABLED`` unset /
# falsy) preserves byte-identical pre-L5 boot: no inference service is
# constructed, no Reactivity is added to the registry, reactivity
# count + behaviour unchanged.
#
# When enabled the composite adds one more Reactivity to the registry —
# yielding 5 default + L3 (if on) + L7 (if on) + L4 (if on) + L5 = up
# to 9 default, or 10 with subscriptions.
#
# Env knobs (defaults per spec §3.7):
#
#   * ``WORMBASE_FINGERPRINT_DISCOVERY_ENABLED`` (default false) —
#     master switch. When unset / falsy, no inference service is
#     constructed and the fingerprint Reactivity is not registered.
#   * ``WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED`` (default false) —
#     gates :class:`ValuePatternFingerprintStrategy`. Wired with
#     L3's :class:`NoopSampler` honest-stub today (returns ``[]`` until
#     Wave 1 connector-backed sampler lands; same gap L7 SampleOverlap
#     surfaces).
#   * ``WORMBASE_FINGERPRINT_DISTRIBUTION_ENABLED`` (default false) —
#     gates :class:`DistributionFingerprintStrategy`. Wired with L7's
#     :class:`NoopHistoricalStatsReader` honest-stub today (returns
#     ``[]`` until Wave 1 catalog mirror emits per-column stats; same
#     gap L7 HistoricalStats surfaces).
#   * ``WORMBASE_FINGERPRINT_PROPOSE_WINDOW_SECONDS`` (default 86400)
#     — per-fingerprint dedup window in seconds.
#   * ``WORMBASE_FINGERPRINT_MIN_CONFIDENCE`` (default 0.6) — minimum
#     confidence floor for proposals (below this, the composite silently
#     skips); read here and stored for future composite filtering.


def is_fingerprint_discovery_enabled() -> bool:
    """Return True iff ``WORMBASE_FINGERPRINT_DISCOVERY_ENABLED`` is truthy.

    Default OFF preserves byte-identical pre-L5 boot: no fingerprint
    reactivity is added to the registry.
    """
    return _is_truthy(
        os.environ.get("WORMBASE_FINGERPRINT_DISCOVERY_ENABLED"),
    )


def is_fingerprint_value_pattern_enabled() -> bool:
    """Return True iff ``WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED`` is truthy.

    Default OFF wires the composite WITHOUT
    :class:`ValuePatternFingerprintStrategy` — the strategy is
    structurally complete but its underlying sampler is honest-stub
    (returns ``[]`` until a real connector-backed sampler lands), so
    opt-in only.
    """
    return _is_truthy(
        os.environ.get("WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED"),
    )


def is_fingerprint_distribution_enabled() -> bool:
    """Return True iff ``WORMBASE_FINGERPRINT_DISTRIBUTION_ENABLED`` is truthy.

    Default OFF wires the composite WITHOUT
    :class:`DistributionFingerprintStrategy` — the strategy is
    structurally complete but its underlying historical-stats reader
    is honest-stub (returns ``[]`` until Wave 1 catalog mirror emits
    per-column stats), so opt-in only.
    """
    return _is_truthy(
        os.environ.get("WORMBASE_FINGERPRINT_DISTRIBUTION_ENABLED"),
    )


def build_fingerprint_service_from_env() -> (
    LakeLoopComposite[ProposedSemanticType] | None
):
    """Build the composite per env knobs. Returns None when L5 disabled.

    Env-knob mapping:

      * ``WORMBASE_FINGERPRINT_DISCOVERY_ENABLED`` — master switch.
        When unset / falsy returns ``None``. The
        :func:`compose_fingerprint_reactivity_if_enabled` wire reads
        this return-value to decide whether to register the Compounding
        Reactivity at all (byte-identical pre-L5 boot when disabled).
      * ``WORMBASE_FINGERPRINT_VALUE_PATTERN_ENABLED`` — when truthy,
        composes :class:`ValuePatternFingerprintStrategy` with L3's
        :class:`NoopSampler` honest-stub (returns ``[]`` until Wave 1
        connector-backed sampler lands).
      * ``WORMBASE_FINGERPRINT_DISTRIBUTION_ENABLED`` — when truthy,
        composes :class:`DistributionFingerprintStrategy` with L7's
        :class:`NoopHistoricalStatsReader` honest-stub (returns ``[]``
        until Wave 1 catalog mirror emits per-column stats).

    The composite is wired with ColumnName always (productive-today on
    bare column names — no upstream sampler / stats required); the
    other two strategies are opt-in via their env knobs because their
    underlying upstream sources are honest-stub today.

    Reuse policy (per Sub-wave B handoff): L5 does NOT define new
    reader Protocols. The two empty-upstream strategies reuse L3's
    :class:`NoopSampler` (from
    :mod:`wormbase_core.lineage_catalog_reader`) and L7's
    :class:`NoopHistoricalStatsReader` (from
    :mod:`wormbase_core.quality_catalog_reader`) — no new readers
    constructed here.

    Returns a :class:`LakeLoopComposite` parameterised over
    :class:`ProposedSemanticType` — the abstraction does the heavy
    lifting (per spec §3.6: ~15 LOC factory instead of ~250 LOC
    custom composite class). First lake-side axis to use the shared
    abstraction from day one.
    """
    if not is_fingerprint_discovery_enabled():
        return None

    column_name = ColumnNameFingerprintStrategy()

    value_pattern: ValuePatternFingerprintStrategy | None = None
    if is_fingerprint_value_pattern_enabled():
        # NoopSampler is L3's honest-stub today; reused across L3
        # SampleOverlap + L5 ValuePattern. Operators see the strategy
        # fire telemetry counter but no proposals materialise until a
        # real connector-backed sampler lands.
        value_pattern = ValuePatternFingerprintStrategy(
            sampler=NoopSampler(),
        )

    distribution: DistributionFingerprintStrategy | None = None
    if is_fingerprint_distribution_enabled():
        # NoopHistoricalStatsReader is L7's honest-stub today; reused
        # across L7 HistoricalStats + L5 Distribution. Operators see
        # the strategy fire telemetry counter but no proposals
        # materialise until Wave 1 catalog mirror emits per-column
        # stats.
        distribution = DistributionFingerprintStrategy(
            stats_reader=NoopHistoricalStatsReader(),
        )

    # Capture min_confidence env knob for forward compatibility — the
    # Sub-wave B composite doesn't currently consume a global
    # min-confidence (strategies apply their own confidence factors).
    # The knob is read here without crashing; a future Sub-wave can
    # extend the composite to filter at promotion time.
    _ = _env_float("WORMBASE_FINGERPRINT_MIN_CONFIDENCE", 0.6)

    return make_composite_semantic_type_service(
        column_name=column_name,
        value_pattern=value_pattern,
        distribution=distribution,
    )


def compose_fingerprint_reactivity_if_enabled(
    *, ledger: Any, company_id: UUID | None = None,
) -> Compounding | None:
    """Compose the L5 fingerprint-discovery Reactivity, or ``None`` if disabled.

    Wires (when ``WORMBASE_FINGERPRINT_DISCOVERY_ENABLED=true``):

      * :class:`LakeLoopComposite[ProposedSemanticType]` from env (built
        via :func:`build_fingerprint_service_from_env`).
      * :class:`LedgerCatalogReader` for catalog enumeration (reused
        from L3 — both L3 and L5 consume the same catalog reader
        Protocol structurally, so we instantiate once; mirrors the L4
        reuse pattern).
      * ``propose_window_seconds`` env knob.

    Default OFF: returns ``None``. Callers (cli.py wire_agent_gateway
    composition) check the return value and only register the
    Reactivity when it is non-None, preserving byte-identical pre-L5
    reactivity count + behaviour.

    Reactivity ordering: this is composed + registered AFTER L4 in
    ``cli._run_async`` (per Sub-wave B handoff concern #5) so telemetry
    counters indexing by Reactivity position stay stable. When L5 is
    enabled alongside L3 + L7 + L4, the registry holds 5 default + L3
    + L7 + L4 + L5 = 9 Reactivities (or 10 with subscriptions).

    Tenant isolation: the :class:`LedgerCatalogReader` takes
    company_id per-call via the Compounding factory's gather_fn
    signature.

    ``sample_size`` defaults to 20 (the canonical N for value-pattern
    M/N matching) — flowed through the factory call.
    """
    fingerprint_service = build_fingerprint_service_from_env()
    if fingerprint_service is None:
        return None

    # Sampler activation Wave: when ``WORMBASE_SAMPLER_ACTIVATION_ENABLED=true``
    # AND ``company_id`` is threaded from the boot wire, swap the
    # ValuePatternFingerprintStrategy's NoopSampler for a tenant-scoped
    # ConnectorSampler. Default-OFF (or missing company_id): the
    # NoopSampler from build_fingerprint_service_from_env stays in
    # place → byte-identical pre-activation behaviour.
    #
    # LakeLoopComposite holds its strategies in the ``_strategies`` dict;
    # the ``strategies`` property returns a defensive copy so we cannot
    # mutate the slot through it. Reach through ``_strategies`` directly
    # to upgrade the live strategy instance.
    value_pattern = fingerprint_service._strategies.get("value_pattern")  # noqa: SLF001
    if (
        value_pattern is not None
        and is_sampler_activation_enabled()
        and company_id is not None
    ):
        value_pattern.sampler = _build_active_sampler_if_enabled(
            ledger=ledger, company_id=company_id,
        )

    # Reuse L3's LedgerCatalogReader for catalog enumeration. Both L3
    # and L5 consume the same catalog reader Protocol structurally;
    # one instance per boot wire avoids duplicate construction.
    # Mirrors the L4 reuse pattern.
    catalog_reader = LedgerCatalogReader(ledger=ledger)

    propose_window_s = _env_int(
        "WORMBASE_FINGERPRINT_PROPOSE_WINDOW_SECONDS", 86400,
    )

    reactivity = make_fingerprint_discovery_reactivity(
        fingerprint_service=fingerprint_service,
        catalog_reader=catalog_reader,
        propose_window_seconds=propose_window_s,
        sample_size=20,
    )
    logger.info(
        "L5 fingerprint discovery composed: column_name=on "
        "value_pattern=%s distribution=%s propose_window_s=%d",
        "on" if is_fingerprint_value_pattern_enabled() else "off",
        "on" if is_fingerprint_distribution_enabled() else "off",
        propose_window_s,
    )
    return reactivity


# ---------------------------------------------------------------------------
# L6 Sub-wave C (2026-06-06) — lake-side column-level governance classification
# — env-driven construction.
#
# Mirrors the L5 axis construction shape with two architectural notes:
#  * **Second cross-axis chain** in the lake-side architecture (after
#    L4→L3). L6 reads L5's confirmed semantic types via the new
#    :class:`ConfirmedSemanticTypeReader` Protocol owned by L6 — the
#    concrete impl is :class:`LedgerConfirmedSemanticTypeReader` in
#    ``column_classification_semantic_reader.py`` (mirrors L4's
#    :class:`LedgerLineageEdgeReader`).
#  * **Second lake-side axis built on :class:`LakeLoopComposite` from
#    day one** (after L5's case 12). The composite is built via
#    :func:`make_composite_column_classification_service`, which returns
#    a parameterised :class:`LakeLoopComposite[ProposedColumnClassification]`
#    instead of a custom composite class (~15 LOC factory).
#
# Default OFF (``WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED``
# unset / falsy) preserves byte-identical pre-L6 boot: no classification
# service is constructed, no Reactivity is added to the registry,
# reactivity count + behaviour unchanged.
#
# When enabled the composite adds one more Reactivity to the registry —
# yielding 5 default + L3 (if on) + L7 (if on) + L4 (if on) + L5 (if on)
# + L6 = up to 10 default, or 11 with subscriptions.
#
# Env knobs (defaults per spec §4.8):
#
#   * ``WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED`` (default
#     false) — master switch. When unset / falsy, no classification
#     service is constructed and the L6 Reactivity is not registered.
#   * ``WORMBASE_COLUMN_CLASSIFICATION_SEMANTIC_TYPE_ENABLED`` (default
#     false) — gates :class:`SemanticTypeClassificationStrategy` (the
#     L5 cross-axis chain). Productive when L5 has confirmed types.
#   * ``WORMBASE_COLUMN_CLASSIFICATION_DOMAIN_DEFAULT_ENABLED`` (default
#     false) — gates :class:`DomainDefaultClassificationStrategy`. Reads
#     existing onboarding governance state via
#     :class:`LedgerDomainDefaultReader`; honest no-op when no pack is
#     selected.
#   * ``WORMBASE_COLUMN_CLASSIFICATION_PROPOSE_WINDOW_SECONDS`` (default
#     86400) — per-classification dedup window in seconds.
#   * ``WORMBASE_COLUMN_CLASSIFICATION_MIN_CONFIDENCE`` (default 0.6) —
#     minimum confidence floor applied at the env-resolution layer
#     (gate-shaped, not strategy-baked — per Sub-wave B handoff
#     concern #3).
#
# ``NamingPatternClassificationStrategy`` is always-on when the master
# switch flips (productive today — regex over column names, no upstream
# dependency). The other two strategies are opt-in via their env knobs
# because their upstreams (L5 confirmed types, onboarding pack
# selection) may not yet be wired in a given deployment.


def is_column_classification_discovery_enabled() -> bool:
    """Return True iff ``WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED`` is truthy.

    Default OFF preserves byte-identical pre-L6 boot: no
    column-classification Reactivity is added to the registry.
    """
    return _is_truthy(
        os.environ.get("WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED"),
    )


def is_column_classification_semantic_type_enabled() -> bool:
    """Return True iff ``WORMBASE_COLUMN_CLASSIFICATION_SEMANTIC_TYPE_ENABLED`` is truthy.

    Default OFF wires the composite WITHOUT
    :class:`SemanticTypeClassificationStrategy` — the cross-axis chain
    to L5 is the most powerful strategy but requires L5 to have
    confirmed types to surface signal. Opt-in via this knob.
    """
    return _is_truthy(
        os.environ.get(
            "WORMBASE_COLUMN_CLASSIFICATION_SEMANTIC_TYPE_ENABLED",
        ),
    )


def is_column_classification_domain_default_enabled() -> bool:
    """Return True iff ``WORMBASE_COLUMN_CLASSIFICATION_DOMAIN_DEFAULT_ENABLED`` is truthy.

    Default OFF wires the composite WITHOUT
    :class:`DomainDefaultClassificationStrategy`. The strategy reads
    existing onboarding governance state via
    :class:`LedgerDomainDefaultReader` and proposes the active pack's
    default at low confidence (0.60) — admin should override with the
    more specific strategies. Opt-in via this knob.
    """
    return _is_truthy(
        os.environ.get(
            "WORMBASE_COLUMN_CLASSIFICATION_DOMAIN_DEFAULT_ENABLED",
        ),
    )


def build_column_classification_service_from_env(
    *, ledger: Any,
) -> LakeLoopComposite[ProposedColumnClassification] | None:
    """Build the L6 composite per env knobs. Returns None when L6 disabled.

    Env-knob mapping (per spec §4.8):

      * ``WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED`` — master
        switch. When unset / falsy returns ``None``. The
        :func:`compose_column_classification_reactivity_if_enabled`
        wire reads this return-value to decide whether to register the
        Compounding Reactivity at all (byte-identical pre-L6 boot when
        disabled).
      * ``WORMBASE_COLUMN_CLASSIFICATION_SEMANTIC_TYPE_ENABLED`` — when
        truthy, composes :class:`SemanticTypeClassificationStrategy`
        with the production
        :class:`LedgerConfirmedSemanticTypeReader` (2nd cross-axis
        impl — mirrors L4's :class:`LedgerLineageEdgeReader`).
      * ``WORMBASE_COLUMN_CLASSIFICATION_DOMAIN_DEFAULT_ENABLED`` —
        when truthy, composes
        :class:`DomainDefaultClassificationStrategy` with
        :class:`LedgerDomainDefaultReader` (reads existing onboarding
        governance state; honest no-op when no pack is selected).

    The composite is wired with NamingPattern always-on when the master
    switch flips (productive-today on bare column names — no upstream
    dependency); the other two strategies are opt-in.

    Cross-axis reader reuse: the
    :class:`LedgerConfirmedSemanticTypeReader` is the 2nd cross-axis
    impl (mirrors L4's pattern). Built once per boot wire so the
    strategy sees the same read surface across invocations.

    ``min_confidence`` knob (per Sub-wave B handoff concern #3) is
    captured at this env-resolution layer rather than baked into the
    strategy — it surfaces as a forward-compat read today and a
    promotion-time filter in a future Sub-wave.

    Returns a :class:`LakeLoopComposite` parameterised over
    :class:`ProposedColumnClassification` — doctrine case 13 (2nd
    lake-side axis on the shared abstraction from day one).
    """
    if not is_column_classification_discovery_enabled():
        return None

    # Shared cross-axis reader (built once per boot wire so the
    # SemanticType strategy and any future cross-axis consumers see
    # the same read surface — same pattern as L4's
    # LedgerLineageEdgeReader shared across two strategies).
    confirmed_semantic_type_reader = LedgerConfirmedSemanticTypeReader(
        ledger=ledger,
    )

    semantic_type: SemanticTypeClassificationStrategy | None = None
    if is_column_classification_semantic_type_enabled():
        semantic_type = SemanticTypeClassificationStrategy(
            semantic_type_reader=confirmed_semantic_type_reader,
        )

    # NamingPattern is productive-today (regex over column names) — fires
    # always-on when the master switch flips.
    naming_pattern = NamingPatternClassificationStrategy()

    domain_default: DomainDefaultClassificationStrategy | None = None
    if is_column_classification_domain_default_enabled():
        domain_default = DomainDefaultClassificationStrategy(
            domain_default_reader=LedgerDomainDefaultReader(ledger=ledger),
        )

    # Promotion-time min_confidence floor (Sub-wave B handoff concern
    # #3, polish-bundle wire-up 2026-06-10). The composite filters
    # post-merge so per-strategy telemetry stays intact while the
    # promotion-rate gate is auditable via
    # ``column_classification_inference_below_min_confidence_dropped``
    # in metrics().
    min_confidence = _env_float(
        "WORMBASE_COLUMN_CLASSIFICATION_MIN_CONFIDENCE", 0.6,
    )

    return make_composite_column_classification_service(
        semantic_type=semantic_type,
        naming_pattern=naming_pattern,
        domain_default=domain_default,
        min_confidence=min_confidence,
    )


def compose_column_classification_reactivity_if_enabled(
    *, ledger: Any,
) -> Compounding | None:
    """Compose the L6 column-classification Reactivity, or ``None`` if disabled.

    Wires (when ``WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED=true``):

      * :class:`LakeLoopComposite[ProposedColumnClassification]` from env
        (built via :func:`build_column_classification_service_from_env`).
      * :class:`LedgerCatalogReader` for catalog enumeration (reused
        from L3 — both L3 and L6 consume the same catalog reader
        Protocol structurally, so we instantiate once; mirrors the L4
        + L5 reuse pattern).
      * ``propose_window_seconds`` env knob.

    Default OFF: returns ``None``. Callers (cli.py wire_agent_gateway
    composition) check the return value and only register the
    Reactivity when it is non-None, preserving byte-identical pre-L6
    reactivity count + behaviour.

    Reactivity ordering: this is composed + registered AFTER L5 in
    ``cli._run_async`` so telemetry counters indexing by Reactivity
    position stay stable. When L6 is enabled alongside L3 + L7 + L4 +
    L5, the registry holds 5 default + L3 + L7 + L4 + L5 + L6 = 10
    Reactivities (or 11 with subscriptions).

    Tenant isolation: the :class:`LedgerCatalogReader` +
    :class:`LedgerConfirmedSemanticTypeReader` +
    :class:`LedgerDomainDefaultReader` all take ``company_id`` per-call
    via the Compounding factory's gather_fn / strategy signatures.
    """
    classification_service = build_column_classification_service_from_env(
        ledger=ledger,
    )
    if classification_service is None:
        return None

    # Reuse L3's LedgerCatalogReader for catalog enumeration. Both L3
    # and L6 consume the same catalog reader Protocol structurally;
    # one instance per boot wire avoids duplicate construction.
    # Mirrors the L4 + L5 reuse pattern.
    catalog_reader = LedgerCatalogReader(ledger=ledger)

    propose_window_s = _env_int(
        "WORMBASE_COLUMN_CLASSIFICATION_PROPOSE_WINDOW_SECONDS",
        86400,
    )

    reactivity = make_column_classification_discovery_reactivity(
        classification_service=classification_service,
        catalog_reader=catalog_reader,
        propose_window_seconds=propose_window_s,
    )
    logger.info(
        "L6 column-classification discovery composed: naming_pattern=on "
        "semantic_type=%s domain_default=%s propose_window_s=%d",
        "on" if is_column_classification_semantic_type_enabled() else "off",
        "on" if is_column_classification_domain_default_enabled() else "off",
        propose_window_s,
    )
    return reactivity


# ---------------------------------------------------------------------------
# L8 Sub-wave C (2026-06-07) — lake-side cross-source entity stitching —
# env-driven construction.
#
# Mirrors the L6 axis construction shape with two architectural notes:
#  * **Third cross-axis chain** in the lake-side architecture (after
#    L4→L3 and L6→L5). L8's :class:`NameMatchEntityStrategy` consumes
#    L6's :class:`ConfirmedSemanticTypeReader` Protocol — second
#    consumer of that Protocol (L6's own
#    :class:`SemanticTypeClassificationStrategy` is the first). No new
#    reader implementation is introduced — L6's existing
#    :class:`LedgerConfirmedSemanticTypeReader` is **reused verbatim**.
#    This is the cleanest Sub-wave C in the lake-side family — zero new
#    cross-axis readers, two reuses (L6 reader + L7's NoopSampler), one
#    L3 catalog reuse.
#  * **Third lake-side axis built on :class:`LakeLoopComposite` from
#    day one** (after L5's case 12 and L6's case 13). The composite is
#    built via :func:`make_composite_entity_stitch_service`, which
#    returns a parameterised :class:`LakeLoopComposite[ProposedEntityStitch]`
#    instead of a custom composite class (~15 LOC factory).
#
# Default OFF (``WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED`` unset /
# falsy) preserves byte-identical pre-L8 boot: no stitch service is
# constructed, no Reactivity is added to the registry, reactivity count
# + behaviour unchanged.
#
# When enabled the composite adds one more Reactivity to the registry —
# yielding 5 default + L3 (if on) + L7 (if on) + L4 (if on) + L5 (if
# on) + L6 (if on) + L8 = up to 11 default, or 12 with subscriptions.
#
# Env knobs (defaults per spec §6):
#
#   * ``WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED`` (default false) —
#     master switch. When unset / falsy, no stitch service is
#     constructed and the L8 Reactivity is not registered.
#   * ``WORMBASE_ENTITY_STITCH_SEMANTIC_TYPE_ANCHOR_ENABLED`` (default
#     false) — gates :class:`NameMatchEntityStrategy`'s L5 semantic-type
#     anchor. When false the strategy degrades to pure-fuzzy-name (the
#     fuzzy path is independent of the anchor and always available when
#     NameMatch is in the composite).
#   * ``WORMBASE_ENTITY_STITCH_SAMPLE_OVERLAP_ENABLED`` (default false)
#     — gates :class:`SampleOverlapEntityStrategy`. Honest stub today
#     (NoopSampler from L3/L5/L7); future wave wires the production
#     sampler.
#   * ``WORMBASE_ENTITY_STITCH_PROPOSE_WINDOW_SECONDS`` (default 86400)
#     — per-stitch dedup window in seconds.
#   * ``WORMBASE_ENTITY_STITCH_MIN_CONFIDENCE`` (default 0.6) — minimum
#     confidence floor applied at the env-resolution layer (gate-shaped,
#     not strategy-baked — per Sub-wave B handoff concern #3 / mirrors
#     L6's posture).
#
# :class:`SchemaShapeEntityStrategy` is always-on when the master
# switch flips (productive on bare catalog metadata when columns are
# available; degrades to no-op today because the LedgerCatalogReader's
# catalog-table dicts carry empty ``columns`` tuples — the
# external_catalog_imported entry shape does not yet carry per-column
# lists). NameMatch's fuzzy-name path is also always-on when the master
# switch flips; the semantic-type anchor is opt-in. SampleOverlap is
# opt-in via its own knob.


def is_entity_stitch_discovery_enabled() -> bool:
    """Return True iff ``WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED`` is truthy.

    Default OFF preserves byte-identical pre-L8 boot: no entity-stitch
    Reactivity is added to the registry.
    """
    return _is_truthy(
        os.environ.get("WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED"),
    )


def is_entity_stitch_semantic_type_anchor_enabled() -> bool:
    """Return True iff ``WORMBASE_ENTITY_STITCH_SEMANTIC_TYPE_ANCHOR_ENABLED`` is truthy.

    Default OFF wires :class:`NameMatchEntityStrategy` WITHOUT the L5
    cross-axis anchor — the strategy still runs the fuzzy-name path
    (productive today on bare column names; no upstream dependency).
    Opt-in via this knob to also consult L5 confirmed semantic types.
    """
    return _is_truthy(
        os.environ.get(
            "WORMBASE_ENTITY_STITCH_SEMANTIC_TYPE_ANCHOR_ENABLED",
        ),
    )


def is_entity_stitch_sample_overlap_enabled() -> bool:
    """Return True iff ``WORMBASE_ENTITY_STITCH_SAMPLE_OVERLAP_ENABLED`` is truthy.

    Default OFF wires the composite WITHOUT
    :class:`SampleOverlapEntityStrategy`. The strategy reuses L7's
    :class:`NoopSampler` (empty samples → 0.0 Jaccard → below threshold
    → no proposals); future wave wires the production sampler. Opt-in
    via this knob so deployments without sampling don't pay the
    composite slot cost.
    """
    return _is_truthy(
        os.environ.get(
            "WORMBASE_ENTITY_STITCH_SAMPLE_OVERLAP_ENABLED",
        ),
    )


def build_entity_stitch_service_from_env(
    *, ledger: Any,
) -> LakeLoopComposite[ProposedEntityStitch] | None:
    """Build the L8 composite per env knobs. Returns None when L8 disabled.

    Env-knob mapping (per spec §6):

      * ``WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED`` — master switch.
        When unset / falsy returns ``None``. The
        :func:`compose_entity_stitch_reactivity_if_enabled` wire reads
        this return-value to decide whether to register the Compounding
        Reactivity at all (byte-identical pre-L8 boot when disabled).
      * ``WORMBASE_ENTITY_STITCH_SEMANTIC_TYPE_ANCHOR_ENABLED`` — when
        truthy, composes :class:`NameMatchEntityStrategy` with the
        production :class:`LedgerConfirmedSemanticTypeReader`
        **reused verbatim from L6** (no new cross-axis adapter; second
        consumer of L6's Protocol after L6's own
        :class:`SemanticTypeClassificationStrategy`). When falsy, the
        strategy is still composed but ``use_semantic_type_anchor=False``
        — the fuzzy-name path remains productive.
      * ``WORMBASE_ENTITY_STITCH_SAMPLE_OVERLAP_ENABLED`` — when truthy,
        composes :class:`SampleOverlapEntityStrategy` with L7's
        :class:`NoopSampler` (honest stub today; same posture as L5's
        Distribution + ValuePattern strategies).

    :class:`SchemaShapeEntityStrategy` is always composed when the
    master switch flips. Its ``parent_table_columns_lookup`` is a
    closure over the shared :class:`LedgerCatalogReader` instance —
    same reader instance reused across L3 + L4 + L5 + L6 + L8 per
    Sub-wave C reuse pattern. Per Sub-wave B handoff concern #2, the
    closure pattern is fine for now; promote to a Protocol when a 4th
    call site lands.

    Cross-axis reader reuse: the
    :class:`LedgerConfirmedSemanticTypeReader` is **reused from L6**
    (no new cross-axis impl — third cross-axis chain shares L6's
    Protocol second-consumer pattern). Built once per boot wire so the
    strategy sees the same read surface across invocations.

    ``min_confidence`` knob (per Sub-wave B handoff concern #3 / mirrors
    L6's posture) is captured at this env-resolution layer rather than
    baked into the strategy — it surfaces as a forward-compat read
    today and a promotion-time filter in a future Sub-wave.

    Returns a :class:`LakeLoopComposite` parameterised over
    :class:`ProposedEntityStitch` — doctrine case 14 (third lake-side
    axis built on the shared abstraction from day one, after L5 / L6).
    """
    if not is_entity_stitch_discovery_enabled():
        return None

    # NameMatchEntityStrategy — always composed when master switch flips.
    # Fuzzy-name path is independent of the semantic-type anchor and
    # productive today (Levenshtein over column names; no upstream
    # dependency). Anchor is opt-in via its env knob and reuses L6's
    # LedgerConfirmedSemanticTypeReader verbatim — no new cross-axis
    # impl introduced (third cross-axis chain in the lake stack;
    # second consumer of L6's Protocol after L6's own SemanticType
    # strategy).
    use_anchor = is_entity_stitch_semantic_type_anchor_enabled()
    name_match = NameMatchEntityStrategy(
        confirmed_semantic_type_reader=(
            LedgerConfirmedSemanticTypeReader(ledger=ledger)
            if use_anchor
            else None
        ),
        use_semantic_type_anchor=use_anchor,
    )

    # SampleOverlapEntityStrategy — opt-in via its env knob. Honest stub
    # today via L7's NoopSampler (empty samples → 0.0 Jaccard → below
    # threshold → no proposals). Future wave wires the production
    # sampler.
    sample_overlap: SampleOverlapEntityStrategy | None = None
    if is_entity_stitch_sample_overlap_enabled():
        sample_overlap = SampleOverlapEntityStrategy(sampler=NoopSampler())

    # SchemaShapeEntityStrategy — always composed when master switch
    # flips. Productive on bare catalog metadata when per-column lists
    # are available; degrades to no-op today because
    # LedgerCatalogReader._make_catalog_table returns columns=() (the
    # external_catalog_imported entry shape does not yet carry
    # per-column lists). When future catalog_table_imported entries
    # carry columns, this strategy lights up without code change here.
    async def _parent_table_columns_lookup(
        source_id: str, table_id: str,
    ) -> list[str]:
        """Async closure over the shared LedgerCatalogReader.

        Per Sub-wave B handoff concern #2: closure pattern is OK for now;
        promote to a Protocol when a 4th call site lands.

        Tenant scope: the catalog reader's list_tables_for_source
        requires a company_id; we can't thread one through the
        Protocol's pure-(source_id, table_id) signature without breaking
        SchemaShape's contract. We accept that limitation today — the
        ledger.fetch underneath uses an implicit tenant binding for
        single-tenant deployments; multi-tenant deployments enforce
        tenant isolation at the gather_fn layer (which always scopes
        by ctx.company_id). The lookup will return [] today since the
        catalog dicts carry empty columns tuples.
        """
        del source_id  # Reserved for future per-source dispatch.
        del table_id   # Reserved for column-set lookup once available.
        return []

    schema_shape = SchemaShapeEntityStrategy(
        parent_table_columns_lookup=_parent_table_columns_lookup,
    )

    # Promotion-time min_confidence floor (Sub-wave B handoff concern
    # #3, polish-bundle wire-up 2026-06-10). The composite filters
    # post-merge so per-strategy telemetry stays intact while the
    # promotion-rate gate is auditable via
    # ``entity_stitch_inference_below_min_confidence_dropped`` in
    # metrics().
    min_confidence = _env_float(
        "WORMBASE_ENTITY_STITCH_MIN_CONFIDENCE", 0.6,
    )

    return make_composite_entity_stitch_service(
        name_match=name_match,
        sample_overlap=sample_overlap,
        schema_shape=schema_shape,
        min_confidence=min_confidence,
    )


def compose_entity_stitch_reactivity_if_enabled(
    *, ledger: Any, company_id: UUID | None = None,
) -> Compounding | None:
    """Compose the L8 entity-stitch Reactivity, or ``None`` if disabled.

    Wires (when ``WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED=true``):

      * :class:`LakeLoopComposite[ProposedEntityStitch]` from env
        (built via :func:`build_entity_stitch_service_from_env`).
      * :class:`LedgerCatalogReader` for cross-source pair enumeration
        (reused from L3 — both L3 and L8 consume the same catalog
        reader Protocol structurally, so we instantiate once; mirrors
        the L4 + L5 + L6 reuse pattern).
      * ``propose_window_seconds`` env knob.

    Default OFF: returns ``None``. Callers (cli.py wire_agent_gateway
    composition) check the return value and only register the
    Reactivity when it is non-None, preserving byte-identical pre-L8
    reactivity count + behaviour.

    Reactivity ordering: this is composed + registered AFTER L6 in
    ``cli._run_async`` so telemetry counters indexing by Reactivity
    position stay stable. When L8 is enabled alongside L3 + L7 + L4 +
    L5 + L6, the registry holds 5 default + L3 + L7 + L4 + L5 + L6 +
    L8 = 11 Reactivities (or 12 with subscriptions).

    Tenant isolation: the :class:`LedgerCatalogReader` +
    :class:`LedgerConfirmedSemanticTypeReader` (when anchor enabled)
    all take ``company_id`` per-call via the Compounding factory's
    gather_fn / strategy signatures.
    """
    stitch_service = build_entity_stitch_service_from_env(ledger=ledger)
    if stitch_service is None:
        return None

    # Sampler activation Wave: when ``WORMBASE_SAMPLER_ACTIVATION_ENABLED=true``
    # AND ``company_id`` is threaded from the boot wire, swap the
    # SampleOverlapEntityStrategy's NoopSampler for a tenant-scoped
    # ConnectorSampler. Default-OFF (or missing company_id): the
    # NoopSampler from build_entity_stitch_service_from_env stays in
    # place → byte-identical pre-activation behaviour.
    #
    # LakeLoopComposite holds its strategies in the ``_strategies`` dict;
    # mirror the L5 reach-through to upgrade the live strategy instance.
    sample_overlap = stitch_service._strategies.get("sample_overlap")  # noqa: SLF001
    if (
        sample_overlap is not None
        and is_sampler_activation_enabled()
        and company_id is not None
    ):
        sample_overlap.sampler = _build_active_sampler_if_enabled(
            ledger=ledger, company_id=company_id,
        )

    # Reuse L3's LedgerCatalogReader for cross-source pair enumeration.
    # Both L3 and L8 consume the same catalog reader Protocol
    # structurally; one instance per boot wire avoids duplicate
    # construction. Mirrors the L4 + L5 + L6 reuse pattern.
    catalog_reader = LedgerCatalogReader(ledger=ledger)

    propose_window_s = _env_int(
        "WORMBASE_ENTITY_STITCH_PROPOSE_WINDOW_SECONDS",
        86400,
    )

    reactivity = make_entity_stitch_discovery_reactivity(
        stitch_service=stitch_service,
        catalog_reader=catalog_reader,
        propose_window_seconds=propose_window_s,
    )
    logger.info(
        "L8 entity-stitch discovery composed: name_match=on (anchor=%s) "
        "sample_overlap=%s schema_shape=on propose_window_s=%d",
        "on" if is_entity_stitch_semantic_type_anchor_enabled() else "off",
        "on" if is_entity_stitch_sample_overlap_enabled() else "off",
        propose_window_s,
    )
    return reactivity


# ---------------------------------------------------------------------------
# L1 Sub-wave C (2026-06-08) — lake-side source-candidate triage —
# env-driven construction.
#
# Mirrors the L6 + L8 axis-construction shape with two architectural
# notes:
#  * **Zero new cross-axis chains in the L4→L3 / L6→L5 / L8→L5 sense**
#    (cross-axis chain count stays at 3). L1 introduces three NEW
#    lightweight Reader Protocols (ConnectedSourceReader, KpiNodeReader,
#    SilverConversationReader) — but these read first-class platform
#    projections (projection_sources, projection_kpi_nodes,
#    projection_conversations), not peer L-axis projections. The
#    producers are substrate, not Compounding loops. Per spec §4.6
#    doctrine clarification; see also
#    ``packages/wormbase-agent-gateway/.../source_candidates/protocol.py``.
#  * **Fourth lake-side axis built on :class:`LakeLoopComposite[T]`
#    from day one** (after L5 case 12, L6 case 13, L8 case 14). The
#    composite is built via
#    :func:`make_composite_source_candidate_service` returning a
#    parameterised :class:`LakeLoopComposite[ProposedSourceCandidate]`
#    instead of a custom composite class (~14 LOC factory).
#  * **Periodic source predicate** (diverges from L3/L7/L4/L5/L6/L8
#    which all use event-driven external_catalog_imported /
#    source_connected). L1 strategies all scan platform projections
#    rather than react to a specific entry kind, so a periodic cadence
#    decouples discovery from upstream traffic. ``tick_interval_s``
#    defaults to 3600 (hourly).
#
# Default OFF (``WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED`` unset /
# falsy) preserves byte-identical pre-L1 boot: no source-candidate
# service is constructed, no Reactivity is added to the registry,
# reactivity count + behaviour unchanged.
#
# When enabled the composite adds one more Reactivity to the registry
# — yielding 5 default + L3 (if on) + L7 (if on) + L4 (if on) + L5 (if
# on) + L6 (if on) + L8 (if on) + L1 = up to 12 default, or 13 with
# subscriptions.
#
# Env knobs (defaults per spec §4.8):
#
#   * ``WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED`` (default false)
#     — master switch. When unset / falsy, no source-candidate service
#     is constructed and the L1 Reactivity is not registered.
#   * ``WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED`` (default false) —
#     gates :class:`KpiGapAcquisitionStrategy`. Productive on unbacked
#     KPI nodes; ``configured · awaiting-kpi-tree-population`` when
#     KPI tree is empty.
#   * ``WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED`` (default
#     false) — gates :class:`ChannelMentionAcquisitionStrategy`.
#     Productive once silver-conversations have rows;
#     ``configured · empty-upstream`` when the silver projection has
#     no rows.
#   * ``WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED`` (default
#     false) — gates :class:`ComplementaritySourceStrategy`.
#     Productive as soon as ≥1 source is connected; static portfolio
#     heuristic with no upstream signal dependency beyond connected
#     sources.
#   * ``WORMBASE_SOURCE_CANDIDATE_MIN_CONFIDENCE`` (default 0.4) —
#     minimum confidence floor applied at the env-resolution layer
#     (gate-shaped, not strategy-baked — per Sub-wave B handoff
#     concern #3 / mirrors L6 + L8 posture). L1 floor (0.4) is lower
#     than other axes' 0.6 because candidate-triage is the right
#     place for low-confidence noise (per spec §4.8).
#
# Note: L1 omits a ``PROPOSE_WINDOW_SECONDS`` knob — candidate dedup
# is handled by ``candidate_id`` collision on the projection PK
# (re-proposing the same (kind, identifier, strategy) is idempotent).
# Per spec §4.8 / Sub-wave B handoff concern #8 — the v027 fold
# absorbs duplicates.
#
# ``WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_WINDOW`` is reserved
# per Sub-wave B handoff concern #4 and deferred to Phase 2; the
# Sub-wave B reader caps recent conversations at 1000 rows by default.


def is_source_candidate_discovery_enabled() -> bool:
    """Return True iff ``WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED`` is truthy.

    Default OFF preserves byte-identical pre-L1 boot: no
    source-candidate Reactivity is added to the registry.
    """
    return _is_truthy(
        os.environ.get("WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED"),
    )


def is_source_candidate_kpi_gap_enabled() -> bool:
    """Return True iff ``WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED`` is truthy.

    Default OFF wires the L1 composite WITHOUT
    :class:`KpiGapAcquisitionStrategy`. Opt-in via this knob so
    deployments without a populated KPI tree don't pay the strategy
    invocation cost.
    """
    return _is_truthy(
        os.environ.get("WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED"),
    )


def is_source_candidate_channel_mention_enabled() -> bool:
    """Return True iff ``WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED`` is truthy.

    Default OFF wires the L1 composite WITHOUT
    :class:`ChannelMentionAcquisitionStrategy`. Opt-in via this knob
    because regex-scanning silver conversations is the most expensive
    of the three L1 strategies.
    """
    return _is_truthy(
        os.environ.get(
            "WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED",
        ),
    )


def is_source_candidate_complementarity_enabled() -> bool:
    """Return True iff ``WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED`` is truthy.

    Default OFF wires the L1 composite WITHOUT
    :class:`ComplementaritySourceStrategy`. Opt-in via this knob even
    though the strategy is productive as soon as ≥1 source is connected
    — the portfolio heuristic can be noisy and admins typically prefer
    to opt in explicitly.
    """
    return _is_truthy(
        os.environ.get(
            "WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED",
        ),
    )


def build_source_candidate_service_from_env(
    *, ledger: Any,
) -> LakeLoopComposite[ProposedSourceCandidate] | None:
    """Build the L1 composite per env knobs. Returns None when L1 disabled.

    Env-knob mapping (per spec §4.8):

      * ``WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED`` — master switch.
        When unset / falsy returns ``None``. The
        :func:`compose_source_candidate_reactivity_if_enabled` wire
        reads this return-value to decide whether to register the
        Compounding Reactivity at all (byte-identical pre-L1 boot when
        disabled).
      * ``WORMBASE_SOURCE_CANDIDATE_KPI_GAP_ENABLED`` — when truthy,
        composes :class:`KpiGapAcquisitionStrategy` with the production
        :class:`LedgerKpiNodeReader`. When falsy the slot is ``None``
        on the composite (Optional-Effect Injection — no proposals on
        that path).
      * ``WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED`` — when
        truthy, composes :class:`ChannelMentionAcquisitionStrategy`
        with the production :class:`LedgerSilverConversationReader`.
      * ``WORMBASE_SOURCE_CANDIDATE_COMPLEMENTARITY_ENABLED`` — when
        truthy, composes :class:`ComplementaritySourceStrategy` with
        the production :class:`LedgerConnectedSourceReader`.

    All three strategies have their own knob — unlike L6/L8 there is
    no always-on strategy in the L1 composite. Reason: every L1
    strategy reads a different platform projection (KPI tree / silver
    conversations / sources), and operators may legitimately want
    only a subset based on which projections are productive in their
    tenancy.

    Reader instances are constructed fresh per build call (single
    instance per boot wire; mirrors L4 + L5 + L6 + L8 reuse pattern
    within a single wire). The readers carry no per-instance state so
    sharing across strategies is safe.

    ``min_confidence`` knob (per Sub-wave B handoff concern #3 /
    mirrors L6 + L8 posture) is captured at this env-resolution layer
    rather than baked into the strategy — it surfaces as a
    forward-compat read today and a promotion-time filter in a future
    Sub-wave. L1's floor is 0.4 (lower than other axes' 0.6) because
    candidate-triage is the right place for low-confidence noise.

    Returns a :class:`LakeLoopComposite` parameterised over
    :class:`ProposedSourceCandidate` — doctrine case 15 (fourth
    lake-side axis built on the shared abstraction from day one,
    after L5 / L6 / L8).
    """
    if not is_source_candidate_discovery_enabled():
        return None

    # KpiGap — opt-in via its env knob. Reads
    # projection_kpi_nodes via LedgerKpiNodeReader (fold of
    # kpi_proposed entries filtered to unbacked nodes).
    kpi_gap: KpiGapAcquisitionStrategy | None = None
    if is_source_candidate_kpi_gap_enabled():
        kpi_gap = KpiGapAcquisitionStrategy(
            kpi_node_reader=LedgerKpiNodeReader(ledger=ledger),
        )

    # ChannelMention — opt-in via its env knob. Reads recent
    # silver-conversation rows via LedgerSilverConversationReader
    # (fold of chat_received entries within the default 24h window,
    # capped at 1000 rows). The lookback is overridable via
    # WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_WINDOW (seconds);
    # e.g. set to 604800 to scan the last 7 days during demo / backfill.
    channel_mention: ChannelMentionAcquisitionStrategy | None = None
    if is_source_candidate_channel_mention_enabled():
        channel_mention_kwargs: dict[str, Any] = {
            "silver_conversation_reader": LedgerSilverConversationReader(
                ledger=ledger,
            ),
        }
        window_override = _env_int(
            "WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_WINDOW", 0,
        )
        if window_override > 0:
            channel_mention_kwargs["lookback_seconds"] = window_override
        channel_mention = ChannelMentionAcquisitionStrategy(
            **channel_mention_kwargs,
        )

    # Complementarity — opt-in via its env knob. Reads
    # projection_sources via LedgerConnectedSourceReader (fold of the
    # source-pipeline lifecycle, returning sources in
    # connected/profiled state).
    complementarity: ComplementaritySourceStrategy | None = None
    if is_source_candidate_complementarity_enabled():
        complementarity = ComplementaritySourceStrategy(
            connected_source_reader=LedgerConnectedSourceReader(
                ledger=ledger,
            ),
        )

    # Promotion-time min_confidence floor (Sub-wave B handoff concern
    # #3, polish-bundle wire-up 2026-06-10). L1 floor is 0.4 (spec
    # §4.8). The composite filters post-merge so per-strategy
    # telemetry stays intact while the promotion-rate gate is
    # auditable via
    # ``source_candidate_inference_below_min_confidence_dropped`` in
    # metrics().
    min_confidence = _env_float(
        "WORMBASE_SOURCE_CANDIDATE_MIN_CONFIDENCE", 0.4,
    )

    return make_composite_source_candidate_service(
        kpi_gap=kpi_gap,
        channel_mention=channel_mention,
        complementarity=complementarity,
        min_confidence=min_confidence,
    )


def compose_source_candidate_reactivity_if_enabled(
    *, ledger: Any,
) -> Compounding | None:
    """Compose the L1 source-candidate Reactivity, or ``None`` if disabled.

    Wires (when ``WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED=true``):

      * :class:`LakeLoopComposite[ProposedSourceCandidate]` from env
        (built via :func:`build_source_candidate_service_from_env`).
      * ``tick_interval_s`` env knob — defaults to 3600 (hourly). The
        Periodic source predicate consumes this. Reuses
        ``WORMBASE_AGENT_GATEWAY_TICK_S`` for symmetry with the
        gap-escalation axis when set; otherwise uses the
        Reactivity-side default (3600s).

    Default OFF: returns ``None``. Callers (cli.py wire_agent_gateway
    composition) check the return value and only register the
    Reactivity when it is non-None, preserving byte-identical pre-L1
    reactivity count + behaviour.

    Reactivity ordering: this is composed + registered AFTER L8 in
    ``cli._run_async`` so telemetry counters indexing by Reactivity
    position stay stable. When L1 is enabled alongside L3 + L7 + L4 +
    L5 + L6 + L8, the registry holds 5 default + L3 + L7 + L4 + L5 +
    L6 + L8 + L1 = 12 Reactivities (or 13 with subscriptions).

    Tenant isolation: the three lightweight Reader Protocols all take
    ``company_id`` per-call via the strategy signatures; the
    composite + Reactivity scope by ``ctx.company_id``.
    """
    candidate_service = build_source_candidate_service_from_env(
        ledger=ledger,
    )
    if candidate_service is None:
        return None

    # Reuse the agent-gateway tick cadence when set; otherwise let the
    # Reactivity factory's default (3600s) ride. L1's periodic
    # cadence shape mirrors v2.B Phase 3 Axis 4 (gap_to_escalation).
    tick_s = _env_int(
        "WORMBASE_AGENT_GATEWAY_TICK_S",
        3600,
    )

    reactivity = make_source_candidate_discovery_reactivity(
        candidate_service=candidate_service,
        tick_interval_s=tick_s,
    )
    logger.info(
        "L1 source-candidate discovery composed: kpi_gap=%s "
        "channel_mention=%s complementarity=%s tick_s=%d",
        "on" if is_source_candidate_kpi_gap_enabled() else "off",
        "on" if is_source_candidate_channel_mention_enabled() else "off",
        "on" if is_source_candidate_complementarity_enabled() else "off",
        tick_s,
    )
    return reactivity


# ---------------------------------------------------------------------------
# L2 Sub-wave C (2026-06-09) — lake-side catalog-drift detection —
# env-driven construction.
#
# Mirrors the L8 axis-construction shape with key architectural notes:
#  * **Zero new cross-axis chains** (cross-axis chain count stays at 3:
#    L4→L3, L6→L5, L8→L5). L2 introduces ONE NEW lightweight Reader
#    Protocol — :class:`CatalogSnapshotReader` — but it reads
#    catalog-mirror substrate (``external_catalog_imported`` entries),
#    NOT a peer L-axis projection. Per spec §4.6 doctrine clarification
#    this is the **platform-reader** category. See
#    ``packages/wormbase-agent-gateway/.../catalog_drift/protocol.py``.
#  * **Fifth lake-side axis built on :class:`LakeLoopComposite[T]`
#    from day one** (after L5 case 12, L6 case 13, L8 case 14, L1
#    case 15). The composite is built via
#    :func:`make_composite_catalog_drift_service` returning a
#    parameterised :class:`LakeLoopComposite[ProposedCatalogDrift]`
#    instead of a custom composite class (~12 LOC factory).
#  * **Event-driven source predicate** (mirrors L3/L7/L4/L5/L6/L8; diverges
#    from L1's Periodic). Fires on ``EntryKind("external_catalog_imported")``
#    — every fresh upstream snapshot triggers drift detection against
#    the prior snapshot.
#
# Default OFF (``WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED`` unset /
# falsy) preserves byte-identical pre-L2 boot: no catalog-drift service
# is constructed, no Reactivity is added to the registry, reactivity
# count + behaviour unchanged.
#
# When enabled the composite adds one more Reactivity to the registry
# — yielding 5 default + L3 + L7 + L4 + L5 + L6 + L8 + L1 + L2 = up
# to 13 default, or 14 with subscriptions.
#
# Env knobs (5 total — master + 3 strategy + min_confidence; per spec
# §4.7):
#
#   * ``WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED`` (default false)
#     — master switch. When unset / falsy, no catalog-drift service is
#     constructed and the L2 Reactivity is not registered.
#   * ``WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED`` (default false) —
#     gates :class:`TableSetDriftStrategy`. Productive day-1 on any
#     pair of snapshots where the upstream catalog-mirror emits table
#     ids (production posture today).
#   * ``WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED`` (default false) —
#     gates :class:`ColumnSetDriftStrategy`. ``configured · empty-upstream``
#     when ``CatalogTable.columns == ()`` (Sub-wave A reality);
#     productive once richer catalog emitters land.
#   * ``WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED`` (default false) —
#     gates :class:`ColumnTypeDriftStrategy`. Same empty-upstream
#     posture as ColumnSet; productive once per-column type metadata
#     is available.
#   * ``WORMBASE_CATALOG_DRIFT_MIN_CONFIDENCE`` (default 0.7) —
#     minimum confidence floor applied at the env-resolution layer
#     (gate-shaped, not strategy-baked — per Sub-wave B handoff
#     concern #3 / mirrors L6/L8/L1 posture). L2 floor (0.7) sits
#     between L1's 0.4 and L6/L8's 0.6 — catalog-diff signal is
#     structural (high) but admins want a non-trivial floor.
#
# All three strategies have their own knob — like L1, no strategy is
# always-on in the L2 composite. Reason: each strategy operates on a
# different layer of the snapshot (table set / column set / column
# type), and operators may legitimately want only a subset based on
# which layers are productive in their tenancy.


def is_catalog_drift_discovery_enabled() -> bool:
    """Return True iff ``WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED`` is truthy.

    Default OFF preserves byte-identical pre-L2 boot: no catalog-drift
    Reactivity is added to the registry.
    """
    return _is_truthy(
        os.environ.get("WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED"),
    )


def is_catalog_drift_table_set_enabled() -> bool:
    """Return True iff ``WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED`` is truthy.

    Default OFF wires the L2 composite WITHOUT
    :class:`TableSetDriftStrategy`. Opt-in via this knob — productive
    day-1 on cross-snapshot table-id diffs.
    """
    return _is_truthy(
        os.environ.get("WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED"),
    )


def is_catalog_drift_column_set_enabled() -> bool:
    """Return True iff ``WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED`` is truthy.

    Default OFF wires the L2 composite WITHOUT
    :class:`ColumnSetDriftStrategy`. The strategy honest-stubs today
    (``CatalogTable.columns == ()`` per Sub-wave A/B handoff); opt-in
    via this knob so the empty-upstream cost stays opt-in until
    richer-diff emitters land.
    """
    return _is_truthy(
        os.environ.get("WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED"),
    )


def is_catalog_drift_column_type_enabled() -> bool:
    """Return True iff ``WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED`` is truthy.

    Default OFF wires the L2 composite WITHOUT
    :class:`ColumnTypeDriftStrategy`. Same empty-upstream posture as
    ColumnSet — opt-in until per-column type metadata is available.
    """
    return _is_truthy(
        os.environ.get("WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED"),
    )


def build_catalog_drift_service_from_env(
    *, ledger: Any,
) -> LakeLoopComposite[ProposedCatalogDrift] | None:
    """Build the L2 composite per env knobs. Returns None when L2 disabled.

    Env-knob mapping (per spec §4.7):

      * ``WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED`` — master switch.
        When unset / falsy returns ``None``. The
        :func:`compose_catalog_drift_reactivity_if_enabled` wire reads
        this return-value to decide whether to register the Compounding
        Reactivity at all (byte-identical pre-L2 boot when disabled).
      * ``WORMBASE_CATALOG_DRIFT_TABLE_SET_ENABLED`` — when truthy,
        composes :class:`TableSetDriftStrategy`. When falsy the slot
        is ``None`` on the composite (Optional-Effect Injection — no
        proposals on that path).
      * ``WORMBASE_CATALOG_DRIFT_COLUMN_SET_ENABLED`` — when truthy,
        composes :class:`ColumnSetDriftStrategy`. Empty-upstream
        honest-stubs today; productive once richer emitters land.
      * ``WORMBASE_CATALOG_DRIFT_COLUMN_TYPE_ENABLED`` — when truthy,
        composes :class:`ColumnTypeDriftStrategy`. Same empty-upstream
        posture as ColumnSet.

    All three strategies have their own knob — unlike L6/L8 there is
    no always-on strategy in the L2 composite. Reason: each strategy
    operates on a different layer of the snapshot, and operators may
    legitimately want only a subset based on which layers are
    productive in their tenancy.

    Strategies do NOT take a snapshot_reader argument — they consume
    pre-reconstructed :class:`CatalogSnapshot` records passed in via
    ``propose(current=..., baseline=...)``. The
    :class:`LedgerCatalogSnapshotReader` is injected into the L2
    Reactivity factory's gather_fn (see
    :func:`compose_catalog_drift_reactivity_if_enabled`) and produces
    the snapshot pair before invoking the composite.

    ``min_confidence`` knob (per Sub-wave B handoff concern #3 /
    mirrors L6/L8/L1 posture) is captured at this env-resolution layer
    rather than baked into the strategy — it surfaces as a
    forward-compat read today and a promotion-time filter in a future
    Sub-wave. L2's floor is 0.7 (sits between L1's 0.4 and L6/L8's
    0.6 — catalog-diff signal is structural so the floor is
    proportionally higher).

    Returns a :class:`LakeLoopComposite` parameterised over
    :class:`ProposedCatalogDrift` — doctrine case 16 (fifth lake-side
    axis built on the shared abstraction from day one, after L5 / L6 /
    L8 / L1).
    """
    if not is_catalog_drift_discovery_enabled():
        return None

    # TableSet — opt-in via its env knob. Productive day-1 on the
    # current/baseline table-id set diff (no upstream dependency
    # beyond the snapshot pair).
    table_set: TableSetDriftStrategy | None = None
    if is_catalog_drift_table_set_enabled():
        table_set = TableSetDriftStrategy()

    # ColumnSet — opt-in via its env knob. Empty-upstream honest-stub
    # today (CatalogTable.columns == () per Sub-wave A/B handoff);
    # productive once richer-diff emitters land.
    column_set: ColumnSetDriftStrategy | None = None
    if is_catalog_drift_column_set_enabled():
        column_set = ColumnSetDriftStrategy()

    # ColumnType — opt-in via its env knob. Same empty-upstream
    # posture as ColumnSet.
    column_type: ColumnTypeDriftStrategy | None = None
    if is_catalog_drift_column_type_enabled():
        column_type = ColumnTypeDriftStrategy()

    # Promotion-time min_confidence floor (Sub-wave B handoff concern
    # #3, polish-bundle wire-up 2026-06-10). L2 floor is 0.7 (spec
    # §4.7). The composite filters post-merge so per-strategy
    # telemetry stays intact while the promotion-rate gate is
    # auditable via
    # ``catalog_drift_inference_below_min_confidence_dropped`` in
    # metrics().
    min_confidence = _env_float(
        "WORMBASE_CATALOG_DRIFT_MIN_CONFIDENCE", 0.7,
    )

    return make_composite_catalog_drift_service(
        table_set=table_set,
        column_set=column_set,
        column_type=column_type,
        min_confidence=min_confidence,
    )


def compose_catalog_drift_reactivity_if_enabled(
    *, ledger: Any,
) -> Compounding | None:
    """Compose the L2 catalog-drift Reactivity, or ``None`` if disabled.

    Wires (when ``WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED=true``):

      * :class:`LakeLoopComposite[ProposedCatalogDrift]` from env
        (built via :func:`build_catalog_drift_service_from_env`).
      * :class:`LedgerCatalogSnapshotReader` instance constructed once
        per boot wire (no per-instance state) — injected into the
        Reactivity factory's gather_fn so the gather can reconstruct
        ``(current, baseline)`` snapshots when an
        ``external_catalog_imported`` entry fires the predicate.

    Default OFF: returns ``None``. Callers (cli.py wire_agent_gateway
    composition) check the return value and only register the
    Reactivity when it is non-None, preserving byte-identical pre-L2
    reactivity count + behaviour.

    Reactivity ordering: this is composed + registered AFTER L1 in
    ``cli._run_async`` so telemetry counters indexing by Reactivity
    position stay stable. When L2 is enabled alongside L3 + L7 + L4 +
    L5 + L6 + L8 + L1, the registry holds 5 default + L3 + L7 + L4 +
    L5 + L6 + L8 + L1 + L2 = 13 Reactivities (or 14 with
    subscriptions).

    Tenant isolation: the :class:`LedgerCatalogSnapshotReader` takes
    ``company_id`` per-call via the Reactivity factory's gather_fn
    (which threads ``ctx.company_id``). The composite + Reactivity
    scope by ``ctx.company_id``.

    Cross-axis chain count: stays at **3** (L4→L3, L6→L5, L8→L5).
    The :class:`CatalogSnapshotReader` Protocol reads catalog-mirror
    substrate (``external_catalog_imported`` entries — a first-class
    entry kind, not a peer-axis projection). Per spec §4.6 doctrine
    clarification.
    """
    drift_service = build_catalog_drift_service_from_env(ledger=ledger)
    if drift_service is None:
        return None

    snapshot_reader = LedgerCatalogSnapshotReader(ledger=ledger)

    reactivity = make_catalog_drift_discovery_reactivity(
        drift_service=drift_service,
        catalog_snapshot_reader=snapshot_reader,
    )
    logger.info(
        "L2 catalog-drift discovery composed: table_set=%s column_set=%s "
        "column_type=%s",
        "on" if is_catalog_drift_table_set_enabled() else "off",
        "on" if is_catalog_drift_column_set_enabled() else "off",
        "on" if is_catalog_drift_column_type_enabled() else "off",
    )
    return reactivity


__all__ = [
    "GatewayBuildSmokeResult",
    "GatherViaProjectionUnavailableError",
    "build_catalog_drift_service_from_env",
    "build_column_classification_service_from_env",
    "build_entity_stitch_service_from_env",
    "build_fingerprint_service_from_env",
    "build_lineage_inference_service_from_env",
    "build_projection_reader_from_ledger",
    "build_quality_proposal_service_from_env",
    "build_schema_impact_service_from_env",
    "build_source_candidate_service_from_env",
    "build_tenant_router_from_env",
    "compose_catalog_drift_reactivity_if_enabled",
    "compose_column_classification_reactivity_if_enabled",
    "compose_entity_stitch_reactivity_if_enabled",
    "compose_fingerprint_reactivity_if_enabled",
    "compose_lineage_reactivity_if_enabled",
    "compose_production_agent_gateway_deps",
    "compose_quality_reactivity_if_enabled",
    "compose_schema_impact_reactivity_if_enabled",
    "compose_source_candidate_reactivity_if_enabled",
    "get_last_dispatcher_deps",
    "is_build_smoke_enabled",
    "is_catalog_drift_column_set_enabled",
    "is_catalog_drift_column_type_enabled",
    "is_catalog_drift_discovery_enabled",
    "is_catalog_drift_table_set_enabled",
    "is_column_classification_discovery_enabled",
    "is_column_classification_domain_default_enabled",
    "is_column_classification_semantic_type_enabled",
    "is_entity_stitch_discovery_enabled",
    "is_entity_stitch_sample_overlap_enabled",
    "is_entity_stitch_semantic_type_anchor_enabled",
    "is_fingerprint_discovery_enabled",
    "is_fingerprint_distribution_enabled",
    "is_fingerprint_value_pattern_enabled",
    "is_gather_via_projection_enabled",
    "is_gather_via_projection_force_enabled",
    "is_lineage_discovery_enabled",
    "is_lineage_sample_overlap_enabled",
    "is_listener_enabled",
    "is_multi_tenant_mcp_enabled",
    "is_quality_discovery_enabled",
    "is_quality_historical_stats_enabled",
    "is_schema_impact_dbt_test_enabled",
    "is_schema_impact_discovery_enabled",
    "is_schema_impact_governance_enabled",
    "is_schema_impact_naming_lineage_enabled",
    "is_source_candidate_channel_mention_enabled",
    "is_source_candidate_complementarity_enabled",
    "is_source_candidate_discovery_enabled",
    "is_source_candidate_kpi_gap_enabled",
    "is_subscriptions_enabled",
    "make_clock_tick_emitter_if_configured",
    "resolve_clock_tick_interval_s",
    "resolve_listener_http_host",
    "resolve_listener_http_port",
    "resolve_listener_transport",
    "resolve_subscription_webhook_max_retries",
    "resolve_subscription_webhook_timeout_s",
    "run_agent_gateway_build_smoke",
    "run_agent_gateway_mcp_listener",
]
