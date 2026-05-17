"""MCP tools for ``processes.*`` — Wave 3.2 Hole #3.

Two tools expose conversation-lake process maps to external agents:

    - processes.list(domain_id?)              — list process maps
    - processes.get(process_map_id)            — fetch a single process map

Both are read-only and mirror the ``decisions.*`` skeleton:

    1. ``_pre_check`` runs the gate chain + redacts args
    2. On denial, emit a denial agent_query and return ``DeniedResponse``
    3. On allow, fetch rows via the injected ``ProcessMapReader``
    4. Wrap the result in an ``agent_query_pevr`` cycle and return a
       typed Pydantic response with the audit_trail_id.

The production reader walks raw ledger rows matching
``payload->>'tool' = 'emit_process_map_proposed'`` (mirrors the
chain-walker pattern in ``decision-chain.ts``); tests pass an
in-memory reader with seeded process-map dicts.
"""
from __future__ import annotations

from typing import Any

from wormbase_inference import AgentID, GovernanceContext

from ..identity import agent_query_pevr
from .responses import (
    DeniedResponse,
    ProcessMapGetResponse,
    ProcessMapListResponse,
    _ProcessMapRow,
)
from .tools_decisions import GoldArtifactDeps
from .tools_lake import _emit_denial_agent_query, _pre_check


# ---------------------------------------------------------------------------
# Row coercion
# ---------------------------------------------------------------------------


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _coerce_process_map_row(row: dict[str, Any]) -> _ProcessMapRow:
    """Coerce a stored row to the response shape.

    Tolerates both the raw ``ProcessMapProposedPayload`` shape and the
    projection-shaped wrapper that may carry ``entry_hash`` or
    ``proposed_at``.
    """
    steps = row.get("steps") or ()
    if not isinstance(steps, (list, tuple)):
        steps = ()
    conf = row.get("confidence")
    if conf is not None:
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = None

    return _ProcessMapRow(
        process_id=str(row.get("process_id", "")),
        process_name=str(row.get("process_name", "")),
        domain=row.get("domain"),
        confidence=conf,
        steps=tuple(dict(s) for s in steps if isinstance(s, dict)),
        proposed_at=_iso(row.get("proposed_at")),
        domain_id=row.get("domain_id"),
        entry_hash=row.get("entry_hash"),
    )


# ---------------------------------------------------------------------------
# Tool 1: processes.list
# ---------------------------------------------------------------------------


async def list_process_maps(
    *,
    domain_id: str | None,
    limit: int,
    deps: GoldArtifactDeps,
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> ProcessMapListResponse | DeniedResponse:
    """List process maps, optionally filtered by domain_id."""
    args = {"domain_id": domain_id, "limit": int(limit)}
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="processes.list",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="processes.list",
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

    rows = await deps.process_map_reader.list_process_maps(
        company_id=deps.company_id,
        domain_id=domain_id,
        limit=int(limit),
    )

    def _execute() -> dict[str, Any]:
        return {
            "row_count": len(rows),
            "result_ref": "processes.list",
        }

    audit_trail_id = await agent_query_pevr(
        ledger=deps.ledger,
        company_id=deps.company_id,
        agent_id=agent_id,
        mcp_tool="processes.list",
        args=pre.redacted_args,
        route_mode="broker",
        execute_fn=_execute,
    )

    return ProcessMapListResponse(
        audit_trail_id=audit_trail_id,
        row_count=len(rows),
        processes=tuple(_coerce_process_map_row(r) for r in rows),
    )


# ---------------------------------------------------------------------------
# Tool 2: processes.get
# ---------------------------------------------------------------------------


async def get_process_map(
    *,
    process_map_id: str,
    deps: GoldArtifactDeps,
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> ProcessMapGetResponse | DeniedResponse:
    """Fetch a single process map by id."""
    args = {"process_map_id": process_map_id}
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="processes.get",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="processes.get",
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

    row = await deps.process_map_reader.get_process_map(
        company_id=deps.company_id,
        process_map_id=process_map_id,
    )

    def _execute() -> dict[str, Any]:
        return {
            "row_count": 1 if row is not None else 0,
            "result_ref": "processes.get",
        }

    audit_trail_id = await agent_query_pevr(
        ledger=deps.ledger,
        company_id=deps.company_id,
        agent_id=agent_id,
        mcp_tool="processes.get",
        args=pre.redacted_args,
        route_mode="broker",
        execute_fn=_execute,
    )

    return ProcessMapGetResponse(
        audit_trail_id=audit_trail_id,
        process_map_id=process_map_id,
        process_map=_coerce_process_map_row(row) if row else None,
    )


__all__ = [
    "get_process_map",
    "list_process_maps",
]
