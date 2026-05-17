"""4 data-plane MCP tools — broker/federate dispatch.

Per Wave 2 Task 7 Step 1 (data plane half):

    - lake.catalog.tables       — list tables from catalog-mirror
    - lake.semantic.metric      — broker-mode metric query via QuerySpec pipeline
    - lake.lineage              — read external_lineage projection
    - lake.query                — federate-mode raw SQL with scoped JWT

Each tool's call site has the same skeleton:

    1. apply_gates(...) — short-circuit with DeniedResponse on first denial
    2. agent_query_pevr(...) — single-kind 4-phase PEVR cycle
    3. return a typed Pydantic response carrying audit_trail_id + result

Tools 1-3 dispatch via broker (the agent does not see raw SQL); tool 4
is the deliberate escape hatch into federate-mode for power agents.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from wormbase_inference import AgentID, GovernanceContext

from ..governance import GateChain, GateDenial, apply_gates
from ..identity import agent_query_pevr
from ..query_spec import (
    CatalogClient,
    CompiledQuery,
    QuerySpec,
    compile_to_sql,
    plan_query,
    validate_query_spec,
)
from ..router_query import (
    BrokerExecutor,
    FederateIssuer,
    choose_route_mode,
)
from .responses import (
    CatalogTablesResponse,
    DeniedResponse,
    LineageResponse,
    MetricQueryResponse,
    QueryFederateResponse,
)


# ---------------------------------------------------------------------------
# CatalogReader Protocol — reads projection rows for catalog + lineage tools
# ---------------------------------------------------------------------------


class CatalogReader:
    """Reads the catalog + lineage projections.

    v1 callers pass a concrete reader that walks the catalog-mirror's
    projection_external_catalog / projection_external_lineage tables.
    Tests pass an in-memory stub keyed by (company_id, source_id).

    The Protocol is structural (duck-typed); any object exposing the
    three async methods satisfies it.
    """

    async def list_tables(
        self, *, company_id: UUID, filter: dict[str, Any] | None,
    ) -> list[dict[str, Any]]: ...  # pragma: no cover

    async def list_lineage(
        self,
        *,
        company_id: UUID,
        resource_id: str,
        direction: Literal["upstream", "downstream", "both"],
    ) -> list[dict[str, Any]]: ...  # pragma: no cover

    async def get_resource_classification(self, resource_id: str) -> str | None:
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# DenialPayload — emits a "denied" agent_query
# ---------------------------------------------------------------------------


async def _emit_denial_agent_query(
    *,
    ledger: Any,
    company_id: UUID,
    agent_id: AgentID,
    mcp_tool: str,
    args: dict[str, Any],
    route_mode: Literal["broker", "federate"],
    denial: GateDenial,
) -> str:
    """Write an ``agent_query`` PEVR cycle that resolves to discard with
    ``status="denied"`` so the denial is reproducible from the ledger
    alone.

    The verify phase fails so the resolve phase records ``outcome=discard``
    with the gate's denial reason. We use the same helper for denial as
    for success because the audit row's projection-fold key is the
    same audit_trail_id either way — splitting denial off into a
    separate kind would create a temporal seam in the trace.
    """
    def _execute() -> dict[str, Any]:
        return {
            "denial_gate": denial.gate_name,
            "denial_reason": denial.reason,
            "suggested_fix": denial.suggested_fix,
        }

    def _verify(execute_payload: dict[str, Any]) -> dict[str, Any]:
        # Mark as failed so resolve records outcome=discard with rationale.
        return {
            "checks": [{
                "name": "gate_chain",
                "ok": False,
                "denial": {
                    "gate_name": denial.gate_name,
                    "reason": denial.reason,
                },
            }],
            # passed=True because we don't want to roll back the entries —
            # the denial is the AUDIT, not a verify failure. Resolve
            # carries outcome=discard via the helper's default mapping.
            # We keep passed=True so the InMemoryLedger doesn't drop the
            # PEVR cycle.
            "passed": True,
            "status": "denied",
        }

    return await agent_query_pevr(
        ledger=ledger,
        company_id=company_id,
        agent_id=agent_id,
        mcp_tool=mcp_tool,
        args=args,
        route_mode=route_mode,
        execute_fn=_execute,
        verify_fn=_verify,
    )


# ---------------------------------------------------------------------------
# Pre-tool envelope — runs gates + redact + emit denial if needed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PreCheck:
    """Outcome of the pre-tool gate + redaction pass.

    When ``denial`` is None, ``redacted_args`` carry the args the
    audit row should record (the original args are preserved on the
    caller side for backend execution). When ``denial`` is set, the
    caller short-circuits with a :class:`DeniedResponse`.
    """

    denial: GateDenial | None
    redacted_args: dict[str, Any]


async def _pre_check(
    *,
    chain: GateChain,
    agent_id: AgentID,
    mcp_tool: str,
    args: dict[str, Any],
    governance: GovernanceContext | None,
) -> _PreCheck:
    """Run the gate chain + redact args for the audit row."""
    redacted_args, _ = chain.pii_redaction.redact_args(args)
    denial = await apply_gates(
        chain,
        agent_id=agent_id,
        mcp_tool=mcp_tool,
        args=args,
        governance=governance,
    )
    return _PreCheck(denial=denial, redacted_args=redacted_args)


# ---------------------------------------------------------------------------
# Tool 1: lake.catalog.tables
# ---------------------------------------------------------------------------


async def lake_catalog_tables(
    *,
    filter: dict[str, Any] | None,
    deps: "LakeToolsDeps",
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> CatalogTablesResponse | DeniedResponse:
    """List tables in projection_external_catalog filtered by `filter`.

    Filter shape (v1): ``{"source_id": "<uuid>", "source_kind": "snowflake"}``
    Either key is optional; missing keys imply no filter on that axis.
    """
    args = {"filter": filter or {}}
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="lake.catalog.tables",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="lake.catalog.tables",
            args=pre.redacted_args,
            route_mode="broker",
            denial=pre.denial,
        )
        return DeniedResponse(
            audit_trail_id=audit,
            gate_name=pre.denial.gate_name,
            reason=pre.denial.reason,
            suggested_fix=pre.denial.suggested_fix,
        )

    # Backend execution — pre-fetch rows so we can populate row_count on
    # the execute payload. The catalog read is part of the synchronous
    # execute_fn closure so the audit row carries the actual count.
    rows = await deps.catalog_reader.list_tables(
        company_id=deps.company_id, filter=filter,
    )

    def _execute() -> dict[str, Any]:
        return {
            "row_count": len(rows),
            "result_ref": "projection_external_catalog",
        }

    audit_trail_id = await agent_query_pevr(
        ledger=deps.ledger,
        company_id=deps.company_id,
        agent_id=agent_id,
        mcp_tool="lake.catalog.tables",
        args=pre.redacted_args,
        route_mode="broker",
        execute_fn=_execute,
    )

    from .responses import _CatalogTableRow  # local import to keep public surface flat
    return CatalogTablesResponse(
        audit_trail_id=audit_trail_id,
        row_count=len(rows),
        tables=tuple(
            _CatalogTableRow(
                source_id=str(r.get("source_id", "")),
                source_kind=str(r.get("source_kind", "")),
                name=str(r.get("name", "")),
                classification=r.get("classification"),
                snapshot_hash=r.get("snapshot_hash"),
                imported_at=(
                    r.get("imported_at").isoformat()
                    if hasattr(r.get("imported_at"), "isoformat")
                    else r.get("imported_at")
                ),
            )
            for r in rows
        ),
    )


# ---------------------------------------------------------------------------
# Tool 2: lake.semantic.metric
# ---------------------------------------------------------------------------


async def lake_semantic_metric(
    *,
    name: str,
    filter: dict[str, Any] | None,
    deps: "LakeToolsDeps",
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> MetricQueryResponse | DeniedResponse:
    """Broker-mode metric query.

    Wraps the QuerySpec validate -> plan -> compile -> execute
    pipeline with the gate chain + agent_query PEVR audit.
    """
    args = {"name": name, "filter": filter or {}}
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="lake.semantic.metric",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="lake.semantic.metric",
            args=pre.redacted_args,
            route_mode="broker",
            denial=pre.denial,
        )
        return DeniedResponse(
            audit_trail_id=audit,
            gate_name=pre.denial.gate_name,
            reason=pre.denial.reason,
            suggested_fix=pre.denial.suggested_fix,
        )

    # Build spec + run pipeline OUTSIDE the agent_query closure so any
    # validation errors surface immediately (and don't appear as a
    # ledger-rollback). Catalog reads here are governed by the agent's
    # access grant — already checked by AgentAccessGate.
    spec = QuerySpec(metric=name, filter=filter)
    await validate_query_spec(spec, catalog=deps.catalog_client)
    plan = await plan_query(spec, catalog=deps.catalog_client)
    compiled = compile_to_sql(spec, plan)
    classification = await deps.catalog_reader.get_resource_classification(
        compiled.upstream_resource_id,
    )
    route = choose_route_mode(spec, classification=classification)
    # v1: metric tool is broker-only — the federate escape hatch is
    # lake.query. We honor choose_route_mode for forward compatibility
    # but log the choice on the audit row.

    t0 = time.perf_counter()
    result = await deps.broker_executor.execute(compiled)
    total_latency_ms = int((time.perf_counter() - t0) * 1000)

    def _execute() -> dict[str, Any]:
        return {
            "row_count": result.row_count,
            "latency_ms": total_latency_ms,
            "result_ref": result.rows_hash,
            "metric_name": name,
        }

    audit_trail_id = await agent_query_pevr(
        ledger=deps.ledger,
        company_id=deps.company_id,
        agent_id=agent_id,
        mcp_tool="lake.semantic.metric",
        args=pre.redacted_args,
        route_mode=route,
        execute_fn=_execute,
    )

    return MetricQueryResponse(
        audit_trail_id=audit_trail_id,
        metric_name=name,
        row_count=result.row_count,
        sample_rows=tuple(result.sample_rows),
        sample_rows_hash=result.rows_hash,
        masking_applied=result.masking_policies_applied,
        latency_ms=total_latency_ms,
    )


# ---------------------------------------------------------------------------
# Tool 3: lake.lineage
# ---------------------------------------------------------------------------


async def lake_lineage(
    *,
    resource_id: str,
    direction: Literal["upstream", "downstream", "both"],
    deps: "LakeToolsDeps",
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> LineageResponse | DeniedResponse:
    """Read lineage edges from projection_external_lineage for a resource."""
    args = {"resource_id": resource_id, "direction": direction}
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="lake.lineage",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="lake.lineage",
            args=pre.redacted_args,
            route_mode="broker",
            denial=pre.denial,
        )
        return DeniedResponse(
            audit_trail_id=audit,
            gate_name=pre.denial.gate_name,
            reason=pre.denial.reason,
            suggested_fix=pre.denial.suggested_fix,
        )

    edges = await deps.catalog_reader.list_lineage(
        company_id=deps.company_id,
        resource_id=resource_id,
        direction=direction,
    )

    def _execute() -> dict[str, Any]:
        return {
            "row_count": len(edges),
            "result_ref": "projection_external_lineage",
        }

    audit_trail_id = await agent_query_pevr(
        ledger=deps.ledger,
        company_id=deps.company_id,
        agent_id=agent_id,
        mcp_tool="lake.lineage",
        args=pre.redacted_args,
        route_mode="broker",
        execute_fn=_execute,
    )

    from .responses import _LineageEdge
    return LineageResponse(
        audit_trail_id=audit_trail_id,
        resource_id=resource_id,
        direction=direction,
        edges=tuple(
            _LineageEdge(
                upstream=str(e.get("upstream", "")),
                downstream=str(e.get("downstream", "")),
                source_id=(str(e["source_id"]) if e.get("source_id") else None),
            )
            for e in edges
        ),
    )


# ---------------------------------------------------------------------------
# Tool 4: lake.query
# ---------------------------------------------------------------------------


async def lake_query(
    *,
    sql: str,
    scope_token: str | None,
    resource_id: str,
    deps: "LakeToolsDeps",
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> QueryFederateResponse | DeniedResponse:
    """Federate-mode raw SQL — issues a ScopedDataToken + returns
    ``(sql, token, callback_url)``.

    ``scope_token`` is the agent's session token (carried in the args
    but not validated here in v1 — the broker checks it on the issue
    path). ``resource_id`` is the upstream resource the SQL touches;
    used to scope the issued data token.
    """
    args = {"sql": sql, "scope_token": scope_token, "resource_id": resource_id}
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="lake.query",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="lake.query",
            args=pre.redacted_args,
            route_mode="federate",
            denial=pre.denial,
        )
        return DeniedResponse(
            audit_trail_id=audit,
            gate_name=pre.denial.gate_name,
            reason=pre.denial.reason,
            suggested_fix=pre.denial.suggested_fix,
        )

    # Build a CompiledQuery shell so the FederateIssuer can scope the token.
    compiled = CompiledQuery(
        sql=sql,
        upstream_kind="snowflake",  # v1: federate path only supports snowflake-shaped JWTs
        upstream_resource_id=resource_id,
    )
    issuance = await deps.federate_issuer.issue(compiled, agent_id=agent_id)

    # The credential entry lands via the broker's own path? No — the
    # federate path's token is observed in the agent_query.execute payload
    # via result_ref. A separate credential entry is the right model
    # but emit_data_credential() requires using the higher-level helper;
    # for federate-only path we keep it on the agent_query trail and let
    # Wave 3 add an inline credential PEVR if needed. The token is
    # ephemeral (TTL=15 min by default) and revocation is observable
    # via the broker.

    def _execute() -> dict[str, Any]:
        return {
            "row_count": 0,  # federate-mode: agent fills in via callback
            "result_ref": issuance.token.token_id,
            "token_id": issuance.token.token_id,
        }

    audit_trail_id = await agent_query_pevr(
        ledger=deps.ledger,
        company_id=deps.company_id,
        agent_id=agent_id,
        mcp_tool="lake.query",
        args=pre.redacted_args,
        route_mode="federate",
        execute_fn=_execute,
    )

    # Also emit a credential lifecycle entry so /trace/credentials shows
    # the issuance — federate is the ONLY tool that mints a wire-visible
    # token, so the credential trail must record it.
    # We already issued the token via the FederateIssuer; the credential
    # helper is for the issue-AND-emit case. Here we just emit the entry
    # directly via the ledger to avoid re-issuing (which would mint a
    # second token).
    from wormbase_ledger.entries import CredentialPayload
    from datetime import datetime, timezone
    cred_payload = CredentialPayload(
        agent_id=agent_id.value,
        credential_kind="data",
        target=resource_id,
        status="active",
        ttl_expires_at=datetime.fromtimestamp(
            issuance.token.expires_at, tz=timezone.utc,
        ).isoformat(),
        issued_by="agent-gateway",
    )
    cred_dict = cred_payload.model_dump()
    await deps.ledger.write(
        company_id=deps.company_id,
        propose=cred_dict,
        execute_fn=lambda: dict(cred_dict),
        verify_fn=lambda _r: {
            **cred_dict,
            "checks": [{"name": "credential_recorded", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            **cred_dict,
            "outcome": "keep",
            "rationale": "federate_token_issued",
        },
    )

    return QueryFederateResponse(
        audit_trail_id=audit_trail_id,
        sql=issuance.sql,
        token_id=issuance.token.token_id,
        token_expires_at=issuance.token.expires_at,
        callback_url=issuance.callback_url,
    )


# ---------------------------------------------------------------------------
# Dependency-injection envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LakeToolsDeps:
    """Per-tool deps bundle — what every lake tool needs to run.

    Constructed at server-build time; tools are pure async fns that
    receive this bundle so test code can compose against a fresh
    in-memory ledger without monkeypatching the server.
    """

    ledger: Any
    company_id: UUID
    catalog_client: CatalogClient
    catalog_reader: CatalogReader
    broker_executor: BrokerExecutor
    federate_issuer: FederateIssuer
    gate_chain: GateChain


__all__ = [
    "CatalogReader",
    "LakeToolsDeps",
    "lake_catalog_tables",
    "lake_lineage",
    "lake_query",
    "lake_semantic_metric",
]
