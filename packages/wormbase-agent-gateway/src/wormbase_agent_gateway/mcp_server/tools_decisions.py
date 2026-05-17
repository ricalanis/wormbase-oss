"""MCP tools for ``decisions.*`` — Wave 3.2 Hole #3.

Three tools expose the conversation-lake decision artefacts to external
agents over MCP:

    - decisions.list(domain_id?, limit?)   — list recent decisions
    - decisions.get(decision_id)            — fetch a single decision
    - decisions.search(nl_question)         — substring match on decision_text

All three are read-only and follow the canonical pattern from
``tools_lake.py``:

    1. ``_pre_check`` runs the gate chain + redacts args
    2. On denial, emit a denial agent_query and return ``DeniedResponse``
    3. On allow, fetch rows via the injected ``DecisionReader``
    4. Wrap the result in an ``agent_query_pevr`` cycle and return a
       typed Pydantic response with the audit_trail_id.

The reader is injected via :class:`GoldArtifactDeps` so tests can pass
in seed rows without spinning up Postgres. v1 stubs return list[dict]
shaped to the ``DecisionRecordedPayload`` schema; the production reader
queries raw ledger rows matching ``payload->>'tool' =
'emit_decision_recorded'`` (mirrors ``decision-chain.ts``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from wormbase_inference import AgentID, GovernanceContext

from ..governance import GateChain
from ..identity import agent_query_pevr
from .responses import (
    DecisionGetResponse,
    DecisionListResponse,
    DecisionSearchResponse,
    DeniedResponse,
    _DecisionRow,
)
from .tools_lake import _emit_denial_agent_query, _pre_check


# ---------------------------------------------------------------------------
# DecisionReader Protocol
# ---------------------------------------------------------------------------


class DecisionReader(Protocol):
    """Read-only accessor for decision_recorded rows.

    Tests pass a small in-memory stub; production wires a Postgres-backed
    reader that filters the raw ledger on ``payload->>'tool' =
    'emit_decision_recorded'`` (no separate projection table exists in
    v1 — the chain-walker pattern in ``decision-chain.ts`` is the
    canonical read path).
    """

    async def list_decisions(
        self,
        *,
        company_id: UUID,
        domain_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:  # pragma: no cover
        ...

    async def get_decision(
        self,
        *,
        company_id: UUID,
        decision_id: str,
    ) -> dict[str, Any] | None:  # pragma: no cover
        ...

    async def search_decisions(
        self,
        *,
        company_id: UUID,
        nl_question: str,
        limit: int,
    ) -> list[dict[str, Any]]:  # pragma: no cover
        ...


# ---------------------------------------------------------------------------
# Deps envelope (shared across decisions / processes / data_products tools)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoldArtifactDeps:
    """Per-family deps bundle for the gold-artifact MCP tools.

    One bundle covers all 8 new tools so the server builder only
    threads a single deps object. Tests construct deps with an
    in-memory reader; production wires a Postgres-backed reader.
    """

    ledger: Any
    company_id: UUID
    decision_reader: "DecisionReader"
    process_map_reader: "ProcessMapReader"
    data_product_reader: "DataProductReader"
    gate_chain: GateChain


# ---------------------------------------------------------------------------
# Row coercion
# ---------------------------------------------------------------------------


def _coerce_decision_row(row: dict[str, Any]) -> _DecisionRow:
    """Coerce a stored row (payload or projection-shaped) to the response shape.

    Tolerates both the raw ``DecisionRecordedPayload`` shape (snake_case
    fields per the payload schema) and any wrapper that flattens
    extra fields (e.g. ``entry_hash`` on the propose entry's hash).
    """
    persons = row.get("decided_by_persons") or ()
    evidence = row.get("evidence_message_ids") or ()
    conf = row.get("confidence")
    if conf is not None:
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = None

    return _DecisionRow(
        decision_id=str(row.get("decision_id", "")),
        decision_text=str(row.get("decision_text", "")),
        decision_at=_iso(row.get("decision_at")),
        channel_id=row.get("channel_id"),
        decided_by_persons=tuple(str(p) for p in persons),
        evidence_message_ids=tuple(str(e) for e in evidence),
        confidence=conf,
        domain_id=row.get("domain_id"),
        entry_hash=row.get("entry_hash"),
    )


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


# ---------------------------------------------------------------------------
# Tool 1: decisions.list
# ---------------------------------------------------------------------------


async def list_decisions(
    *,
    domain_id: str | None,
    limit: int,
    deps: GoldArtifactDeps,
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> DecisionListResponse | DeniedResponse:
    """List recent decisions, optionally filtered by domain_id."""
    args = {"domain_id": domain_id, "limit": int(limit)}
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="decisions.list",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="decisions.list",
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

    rows = await deps.decision_reader.list_decisions(
        company_id=deps.company_id,
        domain_id=domain_id,
        limit=int(limit),
    )

    def _execute() -> dict[str, Any]:
        return {
            "row_count": len(rows),
            "result_ref": "decisions.list",
        }

    audit_trail_id = await agent_query_pevr(
        ledger=deps.ledger,
        company_id=deps.company_id,
        agent_id=agent_id,
        mcp_tool="decisions.list",
        args=pre.redacted_args,
        route_mode="broker",
        execute_fn=_execute,
    )

    return DecisionListResponse(
        audit_trail_id=audit_trail_id,
        row_count=len(rows),
        decisions=tuple(_coerce_decision_row(r) for r in rows),
    )


# ---------------------------------------------------------------------------
# Tool 2: decisions.get
# ---------------------------------------------------------------------------


async def get_decision(
    *,
    decision_id: str,
    deps: GoldArtifactDeps,
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> DecisionGetResponse | DeniedResponse:
    """Fetch a single decision by id."""
    args = {"decision_id": decision_id}
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="decisions.get",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="decisions.get",
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

    row = await deps.decision_reader.get_decision(
        company_id=deps.company_id,
        decision_id=decision_id,
    )

    def _execute() -> dict[str, Any]:
        return {
            "row_count": 1 if row is not None else 0,
            "result_ref": "decisions.get",
        }

    audit_trail_id = await agent_query_pevr(
        ledger=deps.ledger,
        company_id=deps.company_id,
        agent_id=agent_id,
        mcp_tool="decisions.get",
        args=pre.redacted_args,
        route_mode="broker",
        execute_fn=_execute,
    )

    return DecisionGetResponse(
        audit_trail_id=audit_trail_id,
        decision_id=decision_id,
        decision=_coerce_decision_row(row) if row else None,
    )


# ---------------------------------------------------------------------------
# Tool 3: decisions.search
# ---------------------------------------------------------------------------


async def search_decisions(
    *,
    nl_question: str,
    limit: int,
    deps: GoldArtifactDeps,
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> DecisionSearchResponse | DeniedResponse:
    """Substring search over ``decision_text``.

    v1: case-insensitive substring match. v1.1 swaps in pgvector
    cosine over embedded decision_summaries.
    """
    args = {"nl_question": nl_question, "limit": int(limit)}
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="decisions.search",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="decisions.search",
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

    rows = await deps.decision_reader.search_decisions(
        company_id=deps.company_id,
        nl_question=nl_question,
        limit=int(limit),
    )

    def _execute() -> dict[str, Any]:
        return {
            "row_count": len(rows),
            "result_ref": "decisions.search",
        }

    audit_trail_id = await agent_query_pevr(
        ledger=deps.ledger,
        company_id=deps.company_id,
        agent_id=agent_id,
        mcp_tool="decisions.search",
        args=pre.redacted_args,
        route_mode="broker",
        execute_fn=_execute,
    )

    return DecisionSearchResponse(
        audit_trail_id=audit_trail_id,
        nl_question=nl_question,
        matches=tuple(_coerce_decision_row(r) for r in rows),
    )


# Re-export Protocols defined in sibling tool modules — kept here so
# the gold-artifact deps bundle is the single import point.
class ProcessMapReader(Protocol):  # noqa: D101 — imported by sibling tools_processes.py
    async def list_process_maps(
        self, *, company_id: UUID, domain_id: str | None, limit: int,
    ) -> list[dict[str, Any]]: ...  # pragma: no cover

    async def get_process_map(
        self, *, company_id: UUID, process_map_id: str,
    ) -> dict[str, Any] | None: ...  # pragma: no cover


class DataProductReader(Protocol):  # noqa: D101 — imported by sibling tools_data_products.py
    async def list_data_products(
        self,
        *,
        company_id: UUID,
        domain_id: str | None,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]: ...  # pragma: no cover

    async def get_data_product(
        self,
        *,
        company_id: UUID,
        data_product_id: str,
    ) -> dict[str, Any] | None: ...  # pragma: no cover


__all__ = [
    "DataProductReader",
    "DecisionReader",
    "GoldArtifactDeps",
    "ProcessMapReader",
    "get_decision",
    "list_decisions",
    "search_decisions",
]
