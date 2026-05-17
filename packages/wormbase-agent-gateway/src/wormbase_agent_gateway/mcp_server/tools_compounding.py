"""5 §4.5 compounding-layer MCP tools.

Per Wave 2 Task 7 Step 1 (compounding half):

    - lake.semantic.search             — substring/embedding match over catalog
    - lake.semantic.query_spec         — submit QuerySpec; run validate+plan+compile+execute
    - lake.query.suggest_correction    — emit query_correction_suggested
    - lake.query.record_outcome        — emit query_outcome_recorded
    - lake.semantic.gap                — emit semantic_gap_proposed (no enclosing agent_query)

The first 3 wrap an enclosing ``agent_query`` PEVR cycle (single-kind
per Addendum 3) so the audit trail folds into projection_agent_queries.
``record_outcome`` and ``semantic_gap_proposed`` are emit-only kinds —
they land OUTSIDE an agent_query envelope per Addendum 3 §B (their
temporality + cause-effect chain differs from a single PEVR cycle).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from wormbase_inference import AgentID, GovernanceContext
from wormbase_ledger.entries import (
    QueryCorrectionSuggestedPayload,
    QueryOutcomeRecordedPayload,
    SemanticGapProposedPayload,
)

from ..governance import GateChain
from ..identity import agent_query_pevr
from ..query_spec import (
    CatalogClient,
    QuerySpec,
    compile_to_sql,
    plan_query,
    validate_query_spec,
)
from ..router_query import BrokerExecutor
from .responses import (
    DeniedResponse,
    MetricQueryResponse,
    OutcomeRecordedResponse,
    SemanticGapResponse,
    SemanticSearchResponse,
    SuggestCorrectionResponse,
)
from .tools_lake import CatalogReader, _emit_denial_agent_query, _pre_check


# ---------------------------------------------------------------------------
# Dependency envelope (compounding tools)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompoundingToolsDeps:
    """Per-tool deps bundle for the §4.5 compounding suite.

    Most tools touch the catalog + broker executor + ledger; only
    ``suggest_correction`` reaches out to the inference router (Wave 3
    extends this — v1 returns a stub refined spec). The router handle
    is therefore Optional in this dataclass.

    v2.B Phase 3b adds optional ``embedding_service`` — when wired,
    ``lake.query.record_outcome`` calls ``embed(nl_question)`` at write
    time and stamps the vector onto ``QueryOutcomeRecordedPayload.embedding``.
    When None (default), the payload's ``embedding`` field stays None and
    downstream axes 1+3 cluster via the substring fallback.

    Default-off preserves byte-identical behaviour: existing test fakes
    don't need to inject an EmbeddingService, and a fresh deployment
    starts in substring-only mode until ``WORMBASE_EMBEDDING_ENABLED=true``
    flips the wiring.
    """

    ledger: Any
    company_id: UUID
    catalog_client: CatalogClient
    catalog_reader: CatalogReader
    broker_executor: BrokerExecutor
    gate_chain: GateChain
    # Optional — used by suggest_correction. v1 returns a stub refined
    # spec; v1.1 plumbs Router.call(call_type="agent_tool_reasoning").
    router: Any | None = None
    # v2.B Phase 3b — optional embedding wire. Embedding generation is
    # opt-in at construction site (env-gated via WORMBASE_EMBEDDING_ENABLED).
    embedding_service: Any | None = None


# ---------------------------------------------------------------------------
# Tool 1: lake.semantic.search
# ---------------------------------------------------------------------------


async def lake_semantic_search(
    *,
    nl_question: str,
    top_k: int,
    deps: CompoundingToolsDeps,
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> SemanticSearchResponse | DeniedResponse:
    """Rank catalog metrics + tables by simple substring match.

    v1: case-insensitive substring scoring (name + description). v1.1
    replaces this with pgvector cosine over embedded NL-intent
    descriptions populated by the OutcomeToTemplatePromotion Reactivity
    (Wave 2 Task 8).
    """
    args = {"nl_question": nl_question, "top_k": top_k}
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="lake.semantic.search",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="lake.semantic.search",
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

    tables = await deps.catalog_client.list_tables()
    q_lower = nl_question.lower()
    scored: list[tuple[float, dict[str, Any]]] = []
    for t in tables:
        name = str(t.get("name", "")).lower()
        # Substring score: number of question tokens present in name.
        q_tokens = [tok for tok in q_lower.split() if len(tok) > 2]
        hits = sum(1 for tok in q_tokens if tok in name)
        if hits == 0 and q_lower not in name and name not in q_lower:
            continue
        confidence = (hits / max(1, len(q_tokens))) if q_tokens else 0.5
        # Stable tiebreaker — name length favours specificity (shorter wins).
        scored.append((confidence, t))

    scored.sort(key=lambda x: (-x[0], len(str(x[1].get("name", "")))))
    matches = scored[:top_k]

    def _execute() -> dict[str, Any]:
        return {
            "row_count": len(matches),
            "result_ref": "lake.semantic.search",
        }

    audit_trail_id = await agent_query_pevr(
        ledger=deps.ledger,
        company_id=deps.company_id,
        agent_id=agent_id,
        mcp_tool="lake.semantic.search",
        args=pre.redacted_args,
        route_mode="broker",
        execute_fn=_execute,
    )

    from .responses import _SemanticMatch
    return SemanticSearchResponse(
        audit_trail_id=audit_trail_id,
        nl_question=nl_question,
        matches=tuple(
            _SemanticMatch(
                catalog_kind="table",
                name=str(t.get("name", "")),
                source_id=(str(t["source_id"]) if t.get("source_id") else None),
                confidence=float(score),
                snippet=t.get("description"),
            )
            for score, t in matches
        ),
    )


# ---------------------------------------------------------------------------
# Tool 2: lake.semantic.query_spec
# ---------------------------------------------------------------------------


async def lake_semantic_query_spec(
    *,
    spec_dict: dict[str, Any],
    deps: CompoundingToolsDeps,
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> MetricQueryResponse | DeniedResponse:
    """Agent submits a QuerySpec; backend runs validate+plan+compile+execute.

    ``spec_dict`` is the QuerySpec.model_dump()-equivalent shape; we
    construct the dataclass + run the canonical pipeline. The result
    shape matches lake.semantic.metric because both ultimately produce
    a governed broker-mode result.
    """
    args = {"spec": spec_dict}
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="lake.semantic.query_spec",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="lake.semantic.query_spec",
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

    # Build QuerySpec from the dict shape. Tuple fields come back as
    # lists from JSON — coerce them.
    def _tuple(v: Any) -> tuple[Any, ...]:
        if v is None:
            return ()
        if isinstance(v, tuple):
            return v
        return tuple(v)

    spec = QuerySpec(
        metric=spec_dict.get("metric"),
        dimensions=_tuple(spec_dict.get("dimensions")),
        measures=_tuple(spec_dict.get("measures")),
        filter=spec_dict.get("filter"),
        time_grain=spec_dict.get("time_grain"),
        time_range=(
            tuple(spec_dict["time_range"])
            if spec_dict.get("time_range")
            else None
        ),
        limit=int(spec_dict.get("limit", 1000)),
    )

    await validate_query_spec(spec, catalog=deps.catalog_client)
    plan = await plan_query(spec, catalog=deps.catalog_client)
    compiled = compile_to_sql(spec, plan)

    t0 = time.perf_counter()
    result = await deps.broker_executor.execute(compiled)
    total_latency_ms = int((time.perf_counter() - t0) * 1000)

    def _execute() -> dict[str, Any]:
        return {
            "row_count": result.row_count,
            "latency_ms": total_latency_ms,
            "result_ref": result.rows_hash,
            "metric_name": spec.metric,
        }

    audit_trail_id = await agent_query_pevr(
        ledger=deps.ledger,
        company_id=deps.company_id,
        agent_id=agent_id,
        mcp_tool="lake.semantic.query_spec",
        args=pre.redacted_args,
        route_mode="broker",
        execute_fn=_execute,
    )

    return MetricQueryResponse(
        audit_trail_id=audit_trail_id,
        metric_name=spec.metric,
        row_count=result.row_count,
        sample_rows=tuple(result.sample_rows),
        sample_rows_hash=result.rows_hash,
        masking_applied=result.masking_policies_applied,
        latency_ms=total_latency_ms,
    )


# ---------------------------------------------------------------------------
# Tool 3: lake.query.suggest_correction
# ---------------------------------------------------------------------------


async def lake_query_suggest_correction(
    *,
    original_query_id: str,
    failure_kind: Literal["error", "empty", "schema_mismatch"],
    failure_detail: str,
    deps: CompoundingToolsDeps,
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> SuggestCorrectionResponse | DeniedResponse:
    """Reflective rewrite for a failed agent_query.

    v1: returns a stub-refined QuerySpec that loosens filters when
    ``failure_kind == "empty"`` and clears time_range when
    ``failure_kind == "schema_mismatch"``. v1.1 plumbs Router.call
    with call_type="agent_tool_reasoning" for Kimi-backed reasoning.

    Emits a ``query_correction_suggested`` ledger entry chained via
    ``original_query_id`` to the failed agent_query, AND wraps the
    whole tool call in its own ``agent_query`` PEVR so the
    suggestion is itself an auditable action.
    """
    args = {
        "original_query_id": original_query_id,
        "failure_kind": failure_kind,
        "failure_detail": failure_detail,
    }
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="lake.query.suggest_correction",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="lake.query.suggest_correction",
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

    # v1 stub: produce a refined spec based on failure_kind. The shape
    # is intentionally narrow — Wave 3 swaps this for Router.call.
    if failure_kind == "empty":
        refined: dict[str, Any] = {
            "metric": None,
            "dimensions": [],
            "measures": [],
            "filter": None,  # widen by clearing the filter
            "time_range": None,
            "limit": 1000,
            "_rationale": "filter cleared; ran empty under prior filter",
        }
        rationale = (
            "empty result observed; filter cleared to widen search. "
            "Re-submit and observe row count."
        )
    elif failure_kind == "schema_mismatch":
        refined = {
            "metric": None,
            "dimensions": [],
            "measures": [],
            "filter": None,
            "time_range": None,
            "limit": 1000,
            "_rationale": "schema_mismatch; time_range cleared",
        }
        rationale = (
            "schema_mismatch — time_range cleared. Re-submit with "
            "explicit columns from the catalog."
        )
    else:  # "error"
        refined = {
            "metric": None,
            "dimensions": [],
            "measures": [],
            "filter": None,
            "time_range": None,
            "limit": 100,
            "_rationale": "error; safe shape",
        }
        rationale = (
            "error encountered. Try a minimal QuerySpec — pick one "
            "metric or one (dimension+measure) pair only."
        )

    # 1) Emit the query_correction_suggested entry.
    correction_payload = QueryCorrectionSuggestedPayload(
        original_query_id=original_query_id,
        failure_kind=failure_kind,
        failure_detail=failure_detail,
        refined_query_spec=refined,
    )
    cor_dict = correction_payload.model_dump()
    await deps.ledger.write(
        company_id=deps.company_id,
        propose=cor_dict,
        execute_fn=lambda: dict(cor_dict),
        verify_fn=lambda _r: {
            **cor_dict,
            "checks": [{"name": "correction_recorded", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            **cor_dict,
            "outcome": "keep",
            "rationale": "correction_suggested",
        },
    )

    # 2) Wrap the suggestion-tool call itself in agent_query PEVR; the
    # caused_by edge points at the failed original query.
    def _execute() -> dict[str, Any]:
        return {
            "row_count": 0,
            "result_ref": "refined_query_spec",
        }

    audit_trail_id = await agent_query_pevr(
        ledger=deps.ledger,
        company_id=deps.company_id,
        agent_id=agent_id,
        mcp_tool="lake.query.suggest_correction",
        args=pre.redacted_args,
        route_mode="broker",
        execute_fn=_execute,
        caused_by=original_query_id,
    )

    return SuggestCorrectionResponse(
        audit_trail_id=audit_trail_id,
        original_query_id=original_query_id,
        failure_kind=failure_kind,
        refined_query_spec=refined,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Tool 4: lake.query.record_outcome
# ---------------------------------------------------------------------------


async def lake_query_record_outcome(
    *,
    audit_trail_id: str,
    used: bool,
    useful: bool,
    user_correction: str | None,
    nl_question: str,
    final_query_spec: dict[str, Any],
    result_summary: dict[str, Any],
    deps: CompoundingToolsDeps,
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> OutcomeRecordedResponse | DeniedResponse:
    """Emit a ``query_outcome_recorded`` entry chained to its agent_query.

    The outcome is OBSERVATION-ONLY — it lands as its own ledger
    PEVR cycle (verify always passes, resolve always keeps) but does
    NOT wrap an enclosing agent_query. The chaining to the prior
    agent_query is via the ``agent_query_id`` field on the payload.
    """
    args = {
        "audit_trail_id": audit_trail_id,
        "used": used,
        "useful": useful,
        "user_correction": user_correction,
        "nl_question": nl_question,
    }
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="lake.query.record_outcome",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="lake.query.record_outcome",
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

    # Compute a v1 quality score: 1.0 if used+useful, 0.5 if useful but
    # not used, 0.2 if used but not useful, 0.0 otherwise. v1.1 swaps in
    # the OutcomeToTemplatePromotion scoring.
    if used and useful:
        q = Decimal("1.0")
    elif useful:
        q = Decimal("0.5")
    elif used:
        q = Decimal("0.2")
    else:
        q = Decimal("0.0")
    quality_score = format(q, "f")

    # v2.B Phase 3b — write-time embedding wire. Compute the embedding
    # BEFORE writing the ledger entry so the payload carries the vector.
    # When ``embedding_service`` is None (default; tests / opt-out) OR
    # the call fails, the payload's ``embedding`` field stays None and
    # the downstream cluster_fn falls back to substring canonicalisation
    # for that entry. Failures are swallowed (logged) — losing one
    # embedding never blocks a record-outcome write.
    embedding_vec: list[float] | None = None
    if deps.embedding_service is not None and nl_question.strip():
        try:
            emb_result = await deps.embedding_service.embed(nl_question)
            embedding_vec = list(emb_result.vector)
        except Exception:
            # Best-effort: an embed failure shouldn't fail the write.
            # The substring fallback still produces a workable cluster.
            embedding_vec = None

    outcome_payload = QueryOutcomeRecordedPayload(
        agent_query_id=audit_trail_id,
        nl_question=nl_question,
        final_query_spec=final_query_spec,
        result_summary=result_summary,
        used=used,
        useful=useful,
        user_correction=user_correction,
        quality_score=quality_score,
        embedding=embedding_vec,
    )
    oc_dict = outcome_payload.model_dump()
    # Canonical PEVR shape: target_kind on propose, tool=emit_<kind> on
    # execute. Matches process_mapper / write_actions / phenomenon_gaps
    # and lets ``EntryKind("query_outcome_recorded")`` fire via the
    # execute row's ``tool`` field (the canonical primitive).
    await deps.ledger.write(
        company_id=deps.company_id,
        propose={
            "target_kind": "query_outcome_recorded",
            "ref_id": audit_trail_id,
            "reason": (
                f"record_outcome agent_query={audit_trail_id} "
                f"used={used} useful={useful}"
            ),
            "proposed_by": agent_id.value,
        },
        execute_fn=lambda: {
            "tool": "emit_query_outcome_recorded",
            "args": oc_dict,
            "result_ref": audit_trail_id,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "outcome_recorded", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "outcome_recorded",
        },
    )

    return OutcomeRecordedResponse(
        audit_trail_id=audit_trail_id,
        agent_query_id=audit_trail_id,
        used=used,
        useful=useful,
        quality_score=quality_score,
    )


# ---------------------------------------------------------------------------
# Tool 5: lake.semantic.gap
# ---------------------------------------------------------------------------


async def lake_semantic_gap(
    *,
    nl_question: str,
    reason: Literal["no_match", "low_confidence", "ambiguous"],
    proposed_metric_name: str | None,
    deps: CompoundingToolsDeps,
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> SemanticGapResponse | DeniedResponse:
    """Agent-reported gap — no matching metric for an NL question.

    Per Addendum 3 §B: emitted WITHOUT an enclosing agent_query.
    The returned ``audit_trail_id`` is the propose entry_id of the
    semantic_gap_proposed PEVR cycle (a stable correlation key for
    the metric-proposal queue).
    """
    args = {
        "nl_question": nl_question,
        "reason": reason,
        "proposed_metric_name": proposed_metric_name,
    }
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="lake.semantic.gap",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        # Even for a denial we want to record the gap proposal — but
        # AgentAccessGate guards the WORKFLOW, not the catalog. If the
        # gate denies, we still surface the denial on a separate
        # agent_query entry (this tool is the one exception that emits
        # a "no enclosing agent_query" — the denial path takes the
        # canonical denial-trace anyway for consistency).
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="lake.semantic.gap",
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

    audit_trail_id = str(uuid4())
    gap_payload = SemanticGapProposedPayload(
        agent_id=agent_id.value,
        nl_question=nl_question,
        reason=reason,
        proposed_metric_name=proposed_metric_name,
    )
    gap_dict = gap_payload.model_dump()
    # Attach the audit_trail_id so /lake/metrics-proposed and the
    # admin queue can dedupe re-submissions.
    gap_dict["audit_trail_id"] = audit_trail_id
    await deps.ledger.write(
        company_id=deps.company_id,
        propose=gap_dict,
        execute_fn=lambda: dict(gap_dict),
        verify_fn=lambda _r: {
            **gap_dict,
            "checks": [{"name": "gap_recorded", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            **gap_dict,
            "outcome": "keep",
            "rationale": f"gap proposed: {reason}",
        },
    )

    return SemanticGapResponse(
        audit_trail_id=audit_trail_id,
        nl_question=nl_question,
        reason=reason,
        proposed_metric_name=proposed_metric_name,
    )


__all__ = [
    "CompoundingToolsDeps",
    "lake_query_record_outcome",
    "lake_query_suggest_correction",
    "lake_semantic_gap",
    "lake_semantic_query_spec",
    "lake_semantic_search",
]
