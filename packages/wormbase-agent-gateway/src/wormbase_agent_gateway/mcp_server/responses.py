"""Pydantic response shapes for the 9 MCP tools.

Every tool returns a structured Pydantic model carrying:
    - ``audit_trail_id`` — the ``agent_query`` UUID (or, for
      semantic_gap which has no enclosing PEVR, the entry id of the
      ``semantic_gap_proposed`` event)
    - Tool-specific result fields

A separate :class:`DeniedResponse` is returned when any governance
gate fires; it carries enough information for the agent to retry
under a tighter scope or escalate to an admin without re-discovering
the failure mode.

S3 spike implication: returning a structured Pydantic model produces
both ``structured_content`` and a serialized ``content[0].text`` JSON
payload on the FastMCP wire — clients reading either field see the
same data.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class _GatewayResponseBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# Denial shape — returned by any tool when a gate fires
# ---------------------------------------------------------------------------


class DeniedResponse(_GatewayResponseBase):
    """Returned when one of the 4 gates fires on the request.

    The audit row still lands (with ``status="denied"``) so the
    denial is reproducible and auditable.
    """

    status: Literal["denied"] = "denied"
    audit_trail_id: str
    gate_name: str
    reason: str
    suggested_fix: str | None = None


# ---------------------------------------------------------------------------
# Data-plane (original 4) responses
# ---------------------------------------------------------------------------


class _CatalogTableRow(_GatewayResponseBase):
    """Minimal catalog row surfaced via the metric/table query.

    Mirrors what the catalog-mirror projection carries plus a
    classification field for the agent's tooling.
    """

    source_id: str
    source_kind: str
    name: str
    classification: str | None = None
    snapshot_hash: str | None = None
    imported_at: str | None = None


class CatalogTablesResponse(_GatewayResponseBase):
    audit_trail_id: str
    row_count: int
    tables: tuple[_CatalogTableRow, ...] = ()


class MetricQueryResponse(_GatewayResponseBase):
    """Broker-mode metric query response.

    ``sample_rows`` carries up to 5 result rows (full row set is not
    streamed — agents that need bulk export pivot to federate-mode
    via ``lake.query``). ``sample_rows_hash`` is a stable sha256 of
    the canonical-encoded FULL result, so two callers that issued the
    same metric query see the same hash regardless of how many sample
    rows they receive.
    """

    audit_trail_id: str
    metric_name: str | None = None
    row_count: int
    sample_rows: tuple[dict[str, Any], ...] = ()
    sample_rows_hash: str
    masking_applied: tuple[str, ...] = ()
    latency_ms: int


class _LineageEdge(_GatewayResponseBase):
    upstream: str
    downstream: str
    source_id: str | None = None


class LineageResponse(_GatewayResponseBase):
    audit_trail_id: str
    resource_id: str
    direction: Literal["upstream", "downstream", "both"] = "both"
    edges: tuple[_LineageEdge, ...] = ()


class QueryFederateResponse(_GatewayResponseBase):
    """Federate-mode raw-SQL response — agent executes upstream-direct.

    ``token_id`` + ``token_expires_at`` are the scoped JWT envelope;
    ``callback_url`` is where the agent POSTs its result hash after
    upstream execution closes.
    """

    audit_trail_id: str
    sql: str
    token_id: str
    token_expires_at: int
    callback_url: str


# ---------------------------------------------------------------------------
# Compounding-layer (§4.5) responses
# ---------------------------------------------------------------------------


class _SemanticMatch(_GatewayResponseBase):
    """One match returned by lake.semantic.search."""

    catalog_kind: Literal["metric", "table"]
    name: str
    source_id: str | None = None
    confidence: float = 0.0
    snippet: str | None = None


class SemanticSearchResponse(_GatewayResponseBase):
    audit_trail_id: str
    nl_question: str
    matches: tuple[_SemanticMatch, ...] = ()


class SuggestCorrectionResponse(_GatewayResponseBase):
    """Reflective rewrite for a failed agent_query.

    ``refined_query_spec`` is the canonical QuerySpec dump that the
    agent should resubmit; ``rationale`` summarizes why the original
    failed.
    """

    audit_trail_id: str
    original_query_id: str
    failure_kind: Literal["error", "empty", "schema_mismatch"]
    refined_query_spec: dict[str, Any]
    rationale: str


class OutcomeRecordedResponse(_GatewayResponseBase):
    """Confirms an agent's post-query outcome landed on the ledger."""

    audit_trail_id: str
    agent_query_id: str
    used: bool
    useful: bool
    quality_score: str  # Decimal-as-string, [0.0, 1.0]


class SemanticGapResponse(_GatewayResponseBase):
    """Receipt for an agent-reported semantic gap.

    Distinct from the other §4.5 responses because the entry lands
    OUTSIDE an enclosing agent_query (per Addendum 3 §B). The
    ``audit_trail_id`` here is the propose-phase entry_id of the
    ``semantic_gap_proposed`` cycle.
    """

    audit_trail_id: str
    nl_question: str
    reason: Literal["no_match", "low_confidence", "ambiguous"]
    proposed_metric_name: str | None = None


# ---------------------------------------------------------------------------
# Wave 3.2 Hole #3 — decisions.* / processes.* / data_products.* responses
#
# Three families exposing the conversation-lake gold (decisions, processes,
# data products) as MCP tools. Read paths reuse the same gate + PEVR
# pattern as the lake.* tools; the one write tool
# (``data_products.consume``) chains an ``emit_data_product_consumed``
# entry off its enclosing agent_query via ``caused_by``.
# ---------------------------------------------------------------------------


class _DecisionRow(_GatewayResponseBase):
    """One decision_recorded row surfaced via the decisions.* tools.

    Mirrors the ``DecisionRecordedPayload`` ledger shape with a
    flattened JSON-safe layout. Optional fields fall back to None
    when the underlying payload omits them (e.g. legacy rows).
    """

    decision_id: str
    decision_text: str
    decision_at: str | None = None
    channel_id: str | None = None
    decided_by_persons: tuple[str, ...] = ()
    evidence_message_ids: tuple[str, ...] = ()
    confidence: float | None = None
    domain_id: str | None = None
    entry_hash: str | None = None


class DecisionListResponse(_GatewayResponseBase):
    """List response for ``decisions.list``."""

    audit_trail_id: str
    row_count: int
    decisions: tuple[_DecisionRow, ...] = ()


class DecisionGetResponse(_GatewayResponseBase):
    """Single-row response for ``decisions.get``.

    ``decision`` is None when no decision matches the requested id;
    the audit row still lands so the lookup-attempt is reproducible.
    """

    audit_trail_id: str
    decision_id: str
    decision: _DecisionRow | None = None


class DecisionSearchResponse(_GatewayResponseBase):
    """Substring-search response for ``decisions.search``.

    v1 ranks by substring hits on ``decision_text``; v1.1 swaps in
    pgvector embeddings populated by a topic / decision-summary
    promotion reactivity.
    """

    audit_trail_id: str
    nl_question: str
    matches: tuple[_DecisionRow, ...] = ()


class _ProcessMapRow(_GatewayResponseBase):
    """One process_map_proposed row.

    Mirrors ``ProcessMapProposedPayload`` plus a flattened steps shape.
    """

    process_id: str
    process_name: str
    domain: str | None = None
    confidence: float | None = None
    steps: tuple[dict[str, Any], ...] = ()
    proposed_at: str | None = None
    domain_id: str | None = None
    entry_hash: str | None = None


class ProcessMapListResponse(_GatewayResponseBase):
    """List response for ``processes.list``."""

    audit_trail_id: str
    row_count: int
    processes: tuple[_ProcessMapRow, ...] = ()


class ProcessMapGetResponse(_GatewayResponseBase):
    """Single-row response for ``processes.get``."""

    audit_trail_id: str
    process_map_id: str
    process_map: _ProcessMapRow | None = None


class _DataProductRow(_GatewayResponseBase):
    """One projection_data_products row, JSON-safe.

    Mirrors the catalog projection rather than the raw payload — the
    list/get tools surface the materialized (latest-version) shape.
    """

    data_product_id: str
    name: str
    kind: str  # chart | table | report
    status: str  # proposed | generated | archived
    requested_by_person_id: str | None = None
    domain_id: str | None = None
    generated_at: str | None = None
    content_hash: str | None = None
    contents_uri: str | None = None


class DataProductListResponse(_GatewayResponseBase):
    """List response for ``data_products.list``."""

    audit_trail_id: str
    row_count: int
    data_products: tuple[_DataProductRow, ...] = ()


class DataProductGetResponse(_GatewayResponseBase):
    """Single-row response for ``data_products.get``."""

    audit_trail_id: str
    data_product_id: str
    data_product: _DataProductRow | None = None


class DataProductConsumeResponse(_GatewayResponseBase):
    """Receipt for an agent-recorded data-product consumption.

    The enclosing agent_query PEVR is keyed by ``audit_trail_id``;
    the inner ``emit_data_product_consumed`` PEVR is chained via
    its ``caused_by`` edge back to the audit_trail_id so the
    consumption trace is reconstructable from the ledger alone.
    """

    audit_trail_id: str
    data_product_id: str
    consumed_by_agent_id: str
    surface: str = "agent"


__all__ = [
    "CatalogTablesResponse",
    "DataProductConsumeResponse",
    "DataProductGetResponse",
    "DataProductListResponse",
    "DecisionGetResponse",
    "DecisionListResponse",
    "DecisionSearchResponse",
    "DeniedResponse",
    "LineageResponse",
    "MetricQueryResponse",
    "OutcomeRecordedResponse",
    "ProcessMapGetResponse",
    "ProcessMapListResponse",
    "QueryFederateResponse",
    "SemanticGapResponse",
    "SemanticSearchResponse",
    "SuggestCorrectionResponse",
]
