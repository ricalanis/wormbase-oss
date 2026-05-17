"""FastMCP server entrypoint — wires the 9 tools.

Per Wave 2 Task 7 Step 1+. Build the server at boot time via
:func:`build_agent_gateway_mcp_server` and run it via
``mcp.run()`` (stdio default) or pass to FastMCP's HTTP runner for
remote MCP.

Multi-tenant mode (Path 4, 2026-05-21) — opt-in via
``WORMBASE_MULTI_TENANT_MCP=true``: when a :class:`TenantRouter`
is wired through ``GatewayDeps.tenant_router``, every tool handler
resolves the inbound ``X-Tenant-Slug`` HTTP header to a
:class:`TenantContext`, overrides ``company_id`` per request, and
enforces per-tenant rate-limits + 24h quotas. Default OFF preserves
byte-identical single-tenant behavior — see Optional-Effect Injection
doctrine Case 5.

Per S3 spike (`spikes/2026-05-10-semantic-layer/s3_mcp_roundtrip/`),
FastMCP supports dotted tool names (``lake.semantic.metric``) without
underscore substitution. We therefore register tool names verbatim
as documented in the spec.

Dependency injection: callers pass a :class:`GatewayDeps` carrying
the ledger, broker, catalog client, catalog reader, agent-id resolver,
gate chain. Tests construct deps with InMemoryLedger +
EnvCredentialBroker + an in-memory CatalogClient stub.

Agent identity per call
-----------------------
v1: the agent's identity is resolved from a configurable "agent_id
resolver" function passed in deps. For stdio tests this returns a
constant; for HTTP transport it parses the Authorization header.
The resolver is intentionally external so the server core stays
transport-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Sequence
from uuid import UUID

from fastmcp import FastMCP

from wormbase_inference import AgentID, GovernanceContext

from ..governance import GateChain, StatefulGateBundle, make_default_gate_chain
from ..identity import AgentGrant
from ..query_spec import CatalogClient
from ..router_query import BrokerExecutor, FederateIssuer
from ..tenancy import (
    TenantResolveError,
    TenantRouter,
)
from . import tools_compounding as tc
from . import tools_data_products as tdp
from . import tools_decisions as td
from . import tools_lake as tl
from . import tools_processes as tp
from .responses import (
    CatalogTablesResponse,
    DataProductConsumeResponse,
    DataProductGetResponse,
    DataProductListResponse,
    DecisionGetResponse,
    DecisionListResponse,
    DecisionSearchResponse,
    DeniedResponse,
    LineageResponse,
    MetricQueryResponse,
    OutcomeRecordedResponse,
    ProcessMapGetResponse,
    ProcessMapListResponse,
    QueryFederateResponse,
    SemanticGapResponse,
    SemanticSearchResponse,
    SuggestCorrectionResponse,
)
from .tools_compounding import CompoundingToolsDeps
from .tools_decisions import (
    DataProductReader,
    DecisionReader,
    GoldArtifactDeps,
    ProcessMapReader,
)
from .tools_lake import CatalogReader, LakeToolsDeps
from .wire_record import McpToolCallRecorder


# ---------------------------------------------------------------------------
# Resolver Protocols
# ---------------------------------------------------------------------------


def _get_tenant_slug_header_for_request() -> str | None:
    """Module-level helper — read the inbound HTTP X-Tenant-Slug header.

    Lives at module scope (rather than inside ``build_agent_gateway_mcp_server``)
    so test code can monkeypatch it without affecting FastMCP's own
    internal use of :func:`fastmcp.server.dependencies.get_http_request`
    (which is also called by the framework for routing). Returns:

      * the header value (str), when present and non-empty;
      * None, when the header is absent OR there's no HTTP context
        (stdio transport).
    """
    try:
        from fastmcp.server.dependencies import get_http_request
        request = get_http_request()
    except Exception:
        return None
    if request is None:
        return None
    try:
        value = request.headers.get("X-Tenant-Slug")
    except Exception:
        return None
    return value if value else None


AgentIdResolver = Callable[[], Awaitable[AgentID]]
"""Returns the calling agent's :class:`AgentID`.

v1: typically returns a static AgentID for stdio tests, or reads an
Authorization header for HTTP transport. The resolver is async to
match the gate-chain's async surface.
"""

GovernanceResolver = Callable[[AgentID], Awaitable[GovernanceContext]]
"""Returns the :class:`GovernanceContext` envelope for the calling agent.

Reads the agent's grants + the install's classification ceiling and
returns a fresh context per call. v1: typically returns a static
GovernanceContext for tests; production wires this to the projection
of agent_grants by agent_id.
"""

GrantLookup = Callable[[AgentID], Awaitable[Sequence[AgentGrant]]]
"""Per-agent active grant lookup — used by AgentAccessGate + CostGate."""


# ---------------------------------------------------------------------------
# GatewayDeps — top-level injection bundle
# ---------------------------------------------------------------------------


@dataclass
class GatewayDeps:
    """Top-level deps for the FastMCP server.

    The server builder unpacks this into the per-tool-family deps
    bundles (LakeToolsDeps + CompoundingToolsDeps) at construction
    time.
    """

    ledger: Any
    company_id: UUID
    install_id: str
    catalog_client: CatalogClient
    catalog_reader: CatalogReader
    broker_executor: BrokerExecutor
    federate_issuer: FederateIssuer
    grant_lookup: GrantLookup
    agent_id_resolver: AgentIdResolver
    governance_resolver: GovernanceResolver
    router: Any | None = None  # Optional — passed to suggest_correction
    # Wave 3.1: optional MCP-call recorder. When set, every tool wrapper
    # appends an ``mcp.tool_call`` wire event to the recorder's JSONL
    # after the inner call returns. Recorder failure is swallowed so
    # observability never breaks the live tool path.
    recorder: McpToolCallRecorder | None = None
    # Wave 3.2 Hole #3: optional gold-artifact readers for the
    # ``decisions.*`` / ``processes.*`` / ``data_products.*`` MCP tool
    # families. When None, a no-op reader returning empty results is
    # installed so the tools always register (and return honest empty
    # rows) without requiring callers to wire all three accessors at
    # install time. Production deployments inject Postgres-backed
    # readers that fold the corresponding ledger entries / projections.
    decision_reader: DecisionReader | None = None
    process_map_reader: ProcessMapReader | None = None
    data_product_reader: DataProductReader | None = None
    # v1.2 Task 2 Item #2: optional stateful gate bundle. When set,
    # ``build_agent_gateway_mcp_server`` threads it into
    # ``make_default_gate_chain(stateful=...)`` so the 4 inline gates
    # compose with the 4 ``wormbase_governance`` stateful gates per
    # Hole #7. Default ``None`` preserves Wave 2 behaviour byte-for-byte
    # (inline-only chain) — required for callers that haven't yet
    # constructed the stateful gates.
    stateful_gate_bundle: StatefulGateBundle | None = None
    # v2.A Batch B Task 4: optional SubscriptionToolDeps. When set, the
    # 4 agent.subscriptions.* MCP tools delegate to the canonical
    # implementations in subscriptions/mcp_tools.py. When None, the
    # tools register but each surfaces a "subscriptions not configured"
    # denial — preserves the always-advertised tool surface contract.
    subscription_tool_deps: Any | None = None
    # v2.B Phase 3b: optional EmbeddingService. When set (and
    # WORMBASE_EMBEDDING_ENABLED=true at the worm-core wiring site),
    # the §4.5 lake.query.record_outcome MCP tool computes an embedding
    # over the NL question at write time and stamps the resulting
    # vector onto QueryOutcomeRecordedPayload.embedding. None (default)
    # preserves byte-identical behaviour: payloads ship with
    # embedding=None and axes 1+3 cluster via substring fallback.
    embedding_service: Any | None = None
    # Path 4 (2026-05-21 overnight roadmap) — optional multi-tenant
    # router. When set (and WORMBASE_MULTI_TENANT_MCP=true at the
    # worm-core wiring site), every tool handler resolves the inbound
    # request's ``X-Tenant-Slug`` header to a :class:`TenantContext`
    # via the router and overrides ``company_id`` for the duration of
    # the call. Rate limits + 24h quotas are enforced per-tenant. When
    # None (default), the server runs in single-tenant mode —
    # byte-identical to the Phase 1-3c behavior — and ``company_id``
    # is taken verbatim from this deps bundle.
    #
    # This is Case 5 of the Optional-Effect Injection doctrine
    # (``docs/superpowers/specs/2026-05-21-optional-effect-injection-doctrine.md``
    # §9.1). Absence path is the documented single-tenant fallback.
    tenant_router: TenantRouter | None = None


# ---------------------------------------------------------------------------
# Server class
# ---------------------------------------------------------------------------


@dataclass
class AgentGatewayMCPServer:
    """FastMCP server wrapper carrying its deps + the underlying ``mcp``
    instance.

    The ``mcp`` field is the FastMCP object — call ``server.mcp.run()``
    to start stdio, or pass it to FastMCP's HTTP runner. Tests use
    ``fastmcp.Client(server.mcp)`` for in-process round-trips.

    The deps + gate_chain are kept on the instance so tests can poke
    at them without rebuilding the server.
    """

    mcp: FastMCP
    deps: GatewayDeps
    gate_chain: GateChain
    tool_names: tuple[str, ...]


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


_TOOL_NAMES: tuple[str, ...] = (
    "lake.catalog.tables",
    "lake.semantic.metric",
    "lake.lineage",
    "lake.query",
    "lake.semantic.search",
    "lake.semantic.query_spec",
    "lake.query.suggest_correction",
    "lake.query.record_outcome",
    "lake.semantic.gap",
    # Wave 3.2 Hole #3 — gold-artifact MCP surface
    "decisions.list",
    "decisions.get",
    "decisions.search",
    "processes.list",
    "processes.get",
    "data_products.list",
    "data_products.get",
    "data_products.consume",
    # v2.A Task 4 — agent-as-teammate subscription surface (4 tools, 17→21).
    # Tools register unconditionally so the surface is always advertised;
    # the dispatcher itself is opt-in via WORMBASE_SUBSCRIPTIONS_ENABLED.
    # When the SubscriptionTool deps are not wired (default), the tools
    # surface a clear "subscriptions not configured" denial rather than
    # silently 404 — the agent learns the install posture.
    "agent.subscriptions.create",
    "agent.subscriptions.list",
    "agent.subscriptions.revoke",
    "agent.subscriptions.stream",
)


# ---------------------------------------------------------------------------
# Default no-op readers (Wave 3.2 Hole #3)
#
# When the GatewayDeps caller does not inject a reader, install a no-op
# that returns empty rows. This keeps the new tool surface always
# advertised + always governed — even on a fresh install the tools
# register and gate denials still land in the ledger. Production
# deployments inject Postgres-backed readers; tests inject in-memory
# stubs.
# ---------------------------------------------------------------------------


class _EmptyDecisionReader:
    async def list_decisions(
        self, *, company_id: UUID, domain_id: str | None, limit: int,
    ) -> list[dict[str, Any]]:
        return []

    async def get_decision(
        self, *, company_id: UUID, decision_id: str,
    ) -> dict[str, Any] | None:
        return None

    async def search_decisions(
        self, *, company_id: UUID, nl_question: str, limit: int,
    ) -> list[dict[str, Any]]:
        return []


class _EmptyProcessMapReader:
    async def list_process_maps(
        self, *, company_id: UUID, domain_id: str | None, limit: int,
    ) -> list[dict[str, Any]]:
        return []

    async def get_process_map(
        self, *, company_id: UUID, process_map_id: str,
    ) -> dict[str, Any] | None:
        return None


class _EmptyDataProductReader:
    async def list_data_products(
        self,
        *,
        company_id: UUID,
        domain_id: str | None,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        return []

    async def get_data_product(
        self, *, company_id: UUID, data_product_id: str,
    ) -> dict[str, Any] | None:
        return None


def build_agent_gateway_mcp_server(
    deps: GatewayDeps,
    *,
    name: str = "wormbase-agent-gateway",
) -> AgentGatewayMCPServer:
    """Construct + wire the FastMCP server with all 9 tools registered.

    Per Wave 2 Task 7: dotted tool names registered verbatim
    (validated by S3 spike). Each tool is an async function that
    resolves the calling AgentID + GovernanceContext from deps and
    delegates to the canonical tools_lake / tools_compounding fns.
    """
    gate_chain = make_default_gate_chain(
        grant_lookup=deps.grant_lookup,
        resource_classification=deps.catalog_reader.get_resource_classification,
        stateful=deps.stateful_gate_bundle,
    )

    lake_deps = LakeToolsDeps(
        ledger=deps.ledger,
        company_id=deps.company_id,
        catalog_client=deps.catalog_client,
        catalog_reader=deps.catalog_reader,
        broker_executor=deps.broker_executor,
        federate_issuer=deps.federate_issuer,
        gate_chain=gate_chain,
    )
    compound_deps = CompoundingToolsDeps(
        ledger=deps.ledger,
        company_id=deps.company_id,
        catalog_client=deps.catalog_client,
        catalog_reader=deps.catalog_reader,
        broker_executor=deps.broker_executor,
        gate_chain=gate_chain,
        router=deps.router,
        # v2.B Phase 3b — optional EmbeddingService wired at construction
        # time. None preserves byte-identical behaviour (substring
        # clustering); non-None opts the §4.5 record-outcome path into
        # the write-time embedding wire.
        embedding_service=deps.embedding_service,
    )
    # Wave 3.2 Hole #3 — gold-artifact deps. Each reader defaults to a
    # no-op stub when the caller did not inject one; this keeps the new
    # MCP surface always advertised + always governed even on fresh
    # installs.
    gold_deps = GoldArtifactDeps(
        ledger=deps.ledger,
        company_id=deps.company_id,
        decision_reader=deps.decision_reader or _EmptyDecisionReader(),
        process_map_reader=deps.process_map_reader or _EmptyProcessMapReader(),
        data_product_reader=deps.data_product_reader or _EmptyDataProductReader(),
        gate_chain=gate_chain,
    )

    mcp = FastMCP(name=name)

    # -----------------------------------------------------------------
    # Path 4 (2026-05-21 overnight roadmap) — per-request tenant
    # resolution helper.
    #
    # When ``deps.tenant_router`` is None (single-tenant default), the
    # helper returns the default deps bundles constructed above. When
    # set, it:
    #
    #   1. Reads the ``X-Tenant-Slug`` header from the inbound HTTP
    #      request (silently None for stdio transport).
    #   2. Calls ``deps.tenant_router.resolve(slug)`` to get a
    #      :class:`TenantContext` carrying the resolved ``company_id``.
    #   3. Enforces the per-tenant rate limit + 24h quota.
    #   4. Returns per-request deps bundles with the swapped
    #      ``company_id`` (via ``dataclasses.replace``).
    #
    # On :class:`TenantResolveError`, returns ``(None, None, None,
    # None, denied_response)`` so handlers can short-circuit before
    # touching the gate chain. The DeniedResponse uses
    # ``audit_trail_id="tenant-pre-auth"`` because no
    # ``agent_query`` PEVR has been opened yet — the request was
    # rejected at the transport layer before the gate chain.
    #
    # Optional-Effect Injection doctrine §3 Rule 1 — default None
    # preserves byte-identical behavior.
    # -----------------------------------------------------------------

    import dataclasses as _dc

    async def _read_tenant_slug_header() -> str | None:
        """Read ``X-Tenant-Slug`` from the FastMCP HTTP request context.

        Returns the header value, or ``None`` on stdio transport (no
        HTTP context). Catches all FastMCP-side exceptions so a
        transport mismatch never propagates as a 5xx.

        Test seam: tests inject a fake header reader by setting
        ``GatewayDeps.tenant_router`` and monkeypatching the
        :func:`_get_tenant_slug_header_for_request` module-level
        helper rather than the FastMCP dependency itself, so the
        FastMCP framework's own use of ``get_http_request`` for
        routing is not affected.
        """
        return _get_tenant_slug_header_for_request()

    def _denied_for_tenant_error(
        exc: TenantResolveError,
    ) -> DeniedResponse:
        return DeniedResponse(
            audit_trail_id="tenant-pre-auth",
            gate_name=f"tenant:{exc.code}",
            reason=str(exc) or exc.code,
            suggested_fix=(
                "Set the X-Tenant-Slug HTTP header to a registered "
                "tenant slug before retrying."
                if exc.code in ("tenant_unknown", "tenant_revoked")
                else "Wait for the per-tenant rate / quota window to "
                     "reset before retrying."
            ),
        )

    async def _resolve_tenant_deps_or_denial() -> tuple[
        LakeToolsDeps,
        CompoundingToolsDeps,
        GoldArtifactDeps,
        Any | None,
        DeniedResponse | None,
    ]:
        """Return per-request deps + None, or default deps + a DeniedResponse.

        When ``deps.tenant_router`` is None (single-tenant default),
        returns the boot-time-constructed deps bundles unchanged. When
        set, resolves the inbound ``X-Tenant-Slug`` header and returns
        per-request swapped deps (or a denial if resolution / limits
        fail).
        """
        if deps.tenant_router is None:
            return (
                lake_deps,
                compound_deps,
                gold_deps,
                deps.subscription_tool_deps,
                None,
            )
        slug = await _read_tenant_slug_header()
        try:
            ctx = await deps.tenant_router.resolve(slug)
            await deps.tenant_router.enforce_rate_limit(ctx)
            await deps.tenant_router.consume_quota(ctx)
        except TenantResolveError as exc:
            return (
                lake_deps,
                compound_deps,
                gold_deps,
                deps.subscription_tool_deps,
                _denied_for_tenant_error(exc),
            )
        # Build per-request deps with the resolved company_id swapped in.
        request_lake_deps = _dc.replace(lake_deps, company_id=ctx.company_id)
        request_compound_deps = _dc.replace(
            compound_deps, company_id=ctx.company_id,
        )
        request_gold_deps = _dc.replace(gold_deps, company_id=ctx.company_id)
        request_subscription_deps = deps.subscription_tool_deps
        if request_subscription_deps is not None:
            # SubscriptionToolDeps is a frozen dataclass per
            # subscriptions/mcp_tools.py — same replace pattern.
            try:
                request_subscription_deps = _dc.replace(
                    request_subscription_deps, company_id=ctx.company_id,
                )
            except Exception:
                # Defensive: if the future SubscriptionToolDeps changes
                # shape, fall back to the boot-time bundle. Tenant
                # isolation in subscriptions still rests on the
                # reader's SQL.
                pass
        return (
            request_lake_deps,
            request_compound_deps,
            request_gold_deps,
            request_subscription_deps,
            None,
        )

    # -----------------------------------------------------------------
    # Wave 3.1: recorder helper — invoked from every tool wrapper after
    # the inner call returns. Failure to record is swallowed so the
    # live tool path stays available even if the JSONL sink is broken.
    # -----------------------------------------------------------------

    def _record_call(
        tool_name: str,
        params: dict[str, Any],
        agent_id: AgentID,
        response: Any,
    ) -> None:
        if deps.recorder is None:
            return
        try:
            audit_trail_id: str | None = None
            result_summary: dict[str, Any] | None = None
            # Every gateway response carries audit_trail_id; pull it via
            # the model attribute for Pydantic responses, falling back
            # to a dict-like access for forward-compat hand-rolled types.
            atid = getattr(response, "audit_trail_id", None)
            if isinstance(atid, str):
                audit_trail_id = atid
            # result_summary is opaque; surface a small typed digest so
            # the tape is useful to assertion harnesses without bloating
            # the JSONL.
            status_value = getattr(response, "status", None)
            row_count = getattr(response, "row_count", None)
            if status_value is not None or row_count is not None:
                result_summary = {}
                if status_value is not None:
                    result_summary["status"] = str(status_value)
                if isinstance(row_count, int):
                    result_summary["row_count"] = row_count
            deps.recorder.record(
                tool=tool_name,
                params=params,
                agent_id=agent_id.value,
                audit_trail_id=audit_trail_id,
                result_summary=result_summary,
            )
        except Exception as exc:  # noqa: BLE001
            # Observability must never break the live path; surface to
            # operator log + move on.
            import logging as _logging
            _logging.getLogger("wormbase_agent_gateway.mcp_server").warning(
                "mcp wire-record failed for tool=%s: %s", tool_name, exc,
            )

    # -----------------------------------------------------------------
    # Data plane (4)
    # -----------------------------------------------------------------

    @mcp.tool(name="lake.catalog.tables")
    async def _lake_catalog_tables(
        filter: dict[str, Any] | None = None,
    ) -> CatalogTablesResponse | DeniedResponse:
        """List catalog tables.

        Args:
            filter: optional `{source_id, source_kind, ...}` dict.
        """
        lk_d, _, _, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await tl.lake_catalog_tables(
            filter=filter, deps=lk_d,
            agent_id=agent_id, governance=governance,
        )
        _record_call("lake.catalog.tables", {"filter": filter}, agent_id, response)
        return response

    @mcp.tool(name="lake.semantic.metric")
    async def _lake_semantic_metric(
        name: str,
        filter: dict[str, Any] | None = None,
    ) -> MetricQueryResponse | DeniedResponse:
        """Broker-mode metric query."""
        lk_d, _, _, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await tl.lake_semantic_metric(
            name=name, filter=filter, deps=lk_d,
            agent_id=agent_id, governance=governance,
        )
        _record_call(
            "lake.semantic.metric", {"name": name, "filter": filter},
            agent_id, response,
        )
        return response

    @mcp.tool(name="lake.lineage")
    async def _lake_lineage(
        resource_id: str,
        direction: Literal["upstream", "downstream", "both"] = "both",
    ) -> LineageResponse | DeniedResponse:
        """Read lineage edges for a resource."""
        lk_d, _, _, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await tl.lake_lineage(
            resource_id=resource_id, direction=direction,
            deps=lk_d, agent_id=agent_id, governance=governance,
        )
        _record_call(
            "lake.lineage",
            {"resource_id": resource_id, "direction": direction},
            agent_id, response,
        )
        return response

    @mcp.tool(name="lake.query")
    async def _lake_query(
        sql: str,
        resource_id: str,
        scope_token: str | None = None,
    ) -> QueryFederateResponse | DeniedResponse:
        """Federate-mode raw SQL with scoped JWT."""
        lk_d, _, _, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await tl.lake_query(
            sql=sql, scope_token=scope_token, resource_id=resource_id,
            deps=lk_d, agent_id=agent_id, governance=governance,
        )
        _record_call(
            "lake.query",
            {"sql": sql, "resource_id": resource_id, "scope_token": scope_token},
            agent_id, response,
        )
        return response

    # -----------------------------------------------------------------
    # Compounding (5)
    # -----------------------------------------------------------------

    @mcp.tool(name="lake.semantic.search")
    async def _lake_semantic_search(
        nl_question: str,
        top_k: int = 5,
    ) -> SemanticSearchResponse | DeniedResponse:
        """Semantic match over catalog."""
        _, cp_d, _, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await tc.lake_semantic_search(
            nl_question=nl_question, top_k=top_k,
            deps=cp_d, agent_id=agent_id, governance=governance,
        )
        _record_call(
            "lake.semantic.search",
            {"nl_question": nl_question, "top_k": top_k},
            agent_id, response,
        )
        return response

    @mcp.tool(name="lake.semantic.query_spec")
    async def _lake_semantic_query_spec(
        spec: dict[str, Any],
    ) -> MetricQueryResponse | DeniedResponse:
        """Submit a QuerySpec; backend runs the full pipeline."""
        _, cp_d, _, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await tc.lake_semantic_query_spec(
            spec_dict=spec, deps=cp_d,
            agent_id=agent_id, governance=governance,
        )
        _record_call(
            "lake.semantic.query_spec", {"spec": spec}, agent_id, response,
        )
        return response

    @mcp.tool(name="lake.query.suggest_correction")
    async def _lake_query_suggest_correction(
        original_query_id: str,
        failure_kind: Literal["error", "empty", "schema_mismatch"],
        failure_detail: str,
    ) -> SuggestCorrectionResponse | DeniedResponse:
        """Refine a failed query — emits query_correction_suggested."""
        _, cp_d, _, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await tc.lake_query_suggest_correction(
            original_query_id=original_query_id,
            failure_kind=failure_kind,
            failure_detail=failure_detail,
            deps=cp_d, agent_id=agent_id, governance=governance,
        )
        _record_call(
            "lake.query.suggest_correction",
            {
                "original_query_id": original_query_id,
                "failure_kind": failure_kind,
                "failure_detail": failure_detail,
            },
            agent_id, response,
        )
        return response

    @mcp.tool(name="lake.query.record_outcome")
    async def _lake_query_record_outcome(
        audit_trail_id: str,
        used: bool,
        useful: bool,
        nl_question: str,
        final_query_spec: dict[str, Any],
        result_summary: dict[str, Any],
        user_correction: str | None = None,
    ) -> OutcomeRecordedResponse | DeniedResponse:
        """Record agent's post-query outcome — emits query_outcome_recorded."""
        _, cp_d, _, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await tc.lake_query_record_outcome(
            audit_trail_id=audit_trail_id,
            used=used,
            useful=useful,
            user_correction=user_correction,
            nl_question=nl_question,
            final_query_spec=final_query_spec,
            result_summary=result_summary,
            deps=cp_d, agent_id=agent_id, governance=governance,
        )
        _record_call(
            "lake.query.record_outcome",
            {
                "audit_trail_id": audit_trail_id,
                "used": used,
                "useful": useful,
                "nl_question": nl_question,
                "final_query_spec": final_query_spec,
                "result_summary": result_summary,
                "user_correction": user_correction,
            },
            agent_id, response,
        )
        return response

    @mcp.tool(name="lake.semantic.gap")
    async def _lake_semantic_gap(
        nl_question: str,
        reason: Literal["no_match", "low_confidence", "ambiguous"],
        proposed_metric_name: str | None = None,
    ) -> SemanticGapResponse | DeniedResponse:
        """Report a semantic gap — emits semantic_gap_proposed (no enclosing agent_query)."""
        _, cp_d, _, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await tc.lake_semantic_gap(
            nl_question=nl_question,
            reason=reason,
            proposed_metric_name=proposed_metric_name,
            deps=cp_d, agent_id=agent_id, governance=governance,
        )
        _record_call(
            "lake.semantic.gap",
            {
                "nl_question": nl_question,
                "reason": reason,
                "proposed_metric_name": proposed_metric_name,
            },
            agent_id, response,
        )
        return response

    # -----------------------------------------------------------------
    # Wave 3.2 Hole #3 — gold-artifact tools (8)
    # -----------------------------------------------------------------

    @mcp.tool(name="decisions.list")
    async def _decisions_list(
        domain_id: str | None = None,
        limit: int = 50,
    ) -> DecisionListResponse | DeniedResponse:
        """List recent decisions, optionally filtered by domain_id."""
        _, _, gd_d, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await td.list_decisions(
            domain_id=domain_id, limit=limit, deps=gd_d,
            agent_id=agent_id, governance=governance,
        )
        _record_call(
            "decisions.list",
            {"domain_id": domain_id, "limit": limit},
            agent_id, response,
        )
        return response

    @mcp.tool(name="decisions.get")
    async def _decisions_get(
        decision_id: str,
    ) -> DecisionGetResponse | DeniedResponse:
        """Fetch a single decision by id."""
        _, _, gd_d, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await td.get_decision(
            decision_id=decision_id, deps=gd_d,
            agent_id=agent_id, governance=governance,
        )
        _record_call(
            "decisions.get", {"decision_id": decision_id}, agent_id, response,
        )
        return response

    @mcp.tool(name="decisions.search")
    async def _decisions_search(
        nl_question: str,
        limit: int = 10,
    ) -> DecisionSearchResponse | DeniedResponse:
        """Substring search over decision_text."""
        _, _, gd_d, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await td.search_decisions(
            nl_question=nl_question, limit=limit, deps=gd_d,
            agent_id=agent_id, governance=governance,
        )
        _record_call(
            "decisions.search",
            {"nl_question": nl_question, "limit": limit},
            agent_id, response,
        )
        return response

    @mcp.tool(name="processes.list")
    async def _processes_list(
        domain_id: str | None = None,
        limit: int = 50,
    ) -> ProcessMapListResponse | DeniedResponse:
        """List process maps, optionally filtered by domain_id."""
        _, _, gd_d, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await tp.list_process_maps(
            domain_id=domain_id, limit=limit, deps=gd_d,
            agent_id=agent_id, governance=governance,
        )
        _record_call(
            "processes.list",
            {"domain_id": domain_id, "limit": limit},
            agent_id, response,
        )
        return response

    @mcp.tool(name="processes.get")
    async def _processes_get(
        process_map_id: str,
    ) -> ProcessMapGetResponse | DeniedResponse:
        """Fetch a single process map by id."""
        _, _, gd_d, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await tp.get_process_map(
            process_map_id=process_map_id, deps=gd_d,
            agent_id=agent_id, governance=governance,
        )
        _record_call(
            "processes.get",
            {"process_map_id": process_map_id},
            agent_id, response,
        )
        return response

    @mcp.tool(name="data_products.list")
    async def _data_products_list(
        domain_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> DataProductListResponse | DeniedResponse:
        """List data products, optionally filtered by domain_id + status."""
        _, _, gd_d, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await tdp.list_data_products(
            domain_id=domain_id, status=status, limit=limit, deps=gd_d,
            agent_id=agent_id, governance=governance,
        )
        _record_call(
            "data_products.list",
            {"domain_id": domain_id, "status": status, "limit": limit},
            agent_id, response,
        )
        return response

    @mcp.tool(name="data_products.get")
    async def _data_products_get(
        data_product_id: str,
    ) -> DataProductGetResponse | DeniedResponse:
        """Fetch a single data product by id."""
        _, _, gd_d, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await tdp.get_data_product(
            data_product_id=data_product_id, deps=gd_d,
            agent_id=agent_id, governance=governance,
        )
        _record_call(
            "data_products.get",
            {"data_product_id": data_product_id},
            agent_id, response,
        )
        return response

    @mcp.tool(name="data_products.consume")
    async def _data_products_consume(
        data_product_id: str,
        surface: str = "agent",
        channel: str | None = None,
    ) -> DataProductConsumeResponse | DeniedResponse:
        """Record an agent-driven consumption of a data product."""
        _, _, gd_d, _, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        agent_id = await deps.agent_id_resolver()
        governance = await deps.governance_resolver(agent_id)
        response = await tdp.consume_data_product(
            data_product_id=data_product_id,
            surface=surface,
            channel=channel,
            deps=gd_d,
            agent_id=agent_id, governance=governance,
        )
        _record_call(
            "data_products.consume",
            {
                "data_product_id": data_product_id,
                "surface": surface,
                "channel": channel,
            },
            agent_id, response,
        )
        return response

    # -----------------------------------------------------------------
    # v2.A Batch B Task 4 — agent-as-teammate subscription tools (4)
    #
    # All 4 tools register unconditionally so the MCP surface is
    # always advertised. When ``deps.subscription_tool_deps`` is None
    # (env knob not set), each tool surfaces a clear "subscriptions
    # not configured" denial. This matches the Wave 3.2 Hole #3
    # gold-artifact convention: always-advertised, transparently-degraded.
    # -----------------------------------------------------------------

    from ..subscriptions.mcp_tools import (
        SubscriptionDeniedResponse as _SubDenied,
        create_subscription as _sub_create,
        list_subscriptions as _sub_list,
        revoke_subscription as _sub_revoke,
        stream_subscription as _sub_stream,
    )

    def _subscriptions_not_configured(
        subscription_id: str | None = None,
    ) -> _SubDenied:
        return _SubDenied(
            reason=(
                "agent subscriptions not configured for this install "
                "(WORMBASE_SUBSCRIPTIONS_ENABLED unset). Ask admin to "
                "enable the subscription dispatcher."
            ),
            subscription_id=subscription_id,
        )

    @mcp.tool(name="agent.subscriptions.create")
    async def _agent_subscriptions_create(
        agent_id: str,
        filter: dict[str, Any],
        transport: str,
        webhook_url: str | None = None,
        webhook_secret_ref: str | None = None,
        description: str | None = None,
    ) -> Any:
        """Create an agent event subscription.

        Args:
            agent_id: the owning agent (must match the calling agent).
            filter: serialized ``AgentEventFilter`` dict with optional keys
                ``kinds``, ``domains``, ``agent_id_ref``, ``payload_path_eq``.
            transport: ``"mcp_stream"`` or ``"webhook"``.
            webhook_url: required when ``transport == "webhook"``.
            webhook_secret_ref: required when ``transport == "webhook"``;
                resolved via CredentialBroker (e.g. ``vault://wormbase/...``).
            description: human-readable summary.
        """
        _, _, _, sub_d, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        calling = await deps.agent_id_resolver()
        if sub_d is None:
            response: Any = _subscriptions_not_configured()
        else:
            response = await _sub_create(
                agent_id=agent_id,
                filter=filter,
                transport=transport,
                webhook_url=webhook_url,
                webhook_secret_ref=webhook_secret_ref,
                description=description,
                deps=sub_d,
                calling_agent_id=calling,
            )
        _record_call(
            "agent.subscriptions.create",
            {
                "agent_id": agent_id,
                "transport": transport,
                "filter": filter,
            },
            calling, response,
        )
        return response

    @mcp.tool(name="agent.subscriptions.list")
    async def _agent_subscriptions_list(agent_id: str) -> Any:
        """List active subscriptions for ``agent_id`` (must be the calling agent)."""
        _, _, _, sub_d, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        calling = await deps.agent_id_resolver()
        if sub_d is None:
            response: Any = _subscriptions_not_configured()
        else:
            response = await _sub_list(
                agent_id=agent_id,
                deps=sub_d,
                calling_agent_id=calling,
            )
        _record_call(
            "agent.subscriptions.list",
            {"agent_id": agent_id},
            calling, response,
        )
        return response

    @mcp.tool(name="agent.subscriptions.revoke")
    async def _agent_subscriptions_revoke(
        subscription_id: str,
        reason: str = "agent_request",
    ) -> Any:
        """Revoke a subscription. Caller must own it."""
        _, _, _, sub_d, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        calling = await deps.agent_id_resolver()
        if sub_d is None:
            response: Any = _subscriptions_not_configured(subscription_id)
        else:
            response = await _sub_revoke(
                subscription_id=subscription_id,
                reason=reason,
                deps=sub_d,
                calling_agent_id=calling,
            )
        _record_call(
            "agent.subscriptions.revoke",
            {"subscription_id": subscription_id, "reason": reason},
            calling, response,
        )
        return response

    @mcp.tool(name="agent.subscriptions.stream")
    async def _agent_subscriptions_stream(
        subscription_id: str,
        since_seq: int = 0,
    ) -> Any:
        """SSE-style stream of events for a subscription.

        The async generator (``_sub_stream``) yields replay events from
        the ledger first (driven by ``since_seq``) and then enters
        live-tail mode on the per-subscription ``StreamRegistry`` queue.
        How those yields surface to the agent is decided by the
        configured :class:`StreamTransport` on ``sub_d.stream_transport``
        (Path 3, 2026-05-21 overnight roadmap):

          * :class:`ListModeTransport` (default) — collects events into a
            single ``{subscription_id, events: [...]}`` response. Required
            for FastMCP 3.2.4, whose tool runner materializes async
            generators into lists at the transport layer.
          * :class:`SseStreamTransport` (opt-in via
            ``WORMBASE_MCP_SSE_TRANSPORT=true``) — returns true
            event-by-event yield when the underlying FastMCP grows
            streaming-tool support; degrades to list-mode otherwise.

        TenantContext + rate-limit enforcement happens once at
        stream-open via ``_resolve_tenant_deps_or_denial`` (per Path 4
        close-out note: per-event rate-limiting on a long-poll connection
        is an anti-pattern). Subsequent generator yields bypass the
        per-event rate-limit.

        Resumption: pass the last-seen ``triggering_entry_seq`` via
        ``since_seq``; the server replays missed deliveries from the
        ledger before entering live-tail mode.
        """
        # Resolve tenant + rate-limit + quota ONCE at stream-open.
        # The resolved deps bundle is captured into the closure that
        # drives the generator; subsequent live-tail yields bypass the
        # per-event rate-limit. This matches the Wave 4 close-out note.
        _, _, _, sub_d, denial = await _resolve_tenant_deps_or_denial()
        if denial is not None:
            return denial
        calling = await deps.agent_id_resolver()
        if sub_d is None:
            response = _subscriptions_not_configured(subscription_id)
            _record_call(
                "agent.subscriptions.stream",
                {"subscription_id": subscription_id, "since_seq": since_seq},
                calling, response,
            )
            return response
        _record_call(
            "agent.subscriptions.stream",
            {"subscription_id": subscription_id, "since_seq": since_seq},
            calling, None,
        )
        # Drive the generator via the configured StreamTransport.
        # ListModeTransport (default) collects events into the legacy
        # ``{subscription_id, events: [...]}`` shape; SseStreamTransport
        # yields one-at-a-time when FastMCP supports it.
        generator = _sub_stream(
            subscription_id=subscription_id,
            since_seq=since_seq,
            deps=sub_d,
            calling_agent_id=calling,
        )
        transport = sub_d.stream_transport
        # __post_init__ on SubscriptionToolDeps guarantees this is set,
        # but be defensive for callers that bypass the dataclass.
        if transport is None:  # pragma: no cover — defensive
            from ..subscriptions.stream_transport import ListModeTransport
            transport = ListModeTransport()
        return await transport.deliver(
            subscription_id=subscription_id,
            generator=generator,
            stream_registry=sub_d.stream_registry,
        )

    return AgentGatewayMCPServer(
        mcp=mcp, deps=deps, gate_chain=gate_chain, tool_names=_TOOL_NAMES,
    )


__all__ = [
    "AgentGatewayMCPServer",
    "AgentIdResolver",
    "GatewayDeps",
    "GovernanceResolver",
    "GrantLookup",
    "build_agent_gateway_mcp_server",
]
