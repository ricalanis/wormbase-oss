"""MCP tools for ``data_products.*`` — Wave 3.2 Hole #3.

Three tools — two read, one write:

    - data_products.list(domain_id?, status?)    — list latest-version
                                                   data products
    - data_products.get(data_product_id)         — fetch one row
    - data_products.consume(data_product_id, …)  — emit
                                                   ``data_product_consumed``
                                                   chained off the agent_query

The two read tools follow the canonical pattern (gate → fetch via
injected ``DataProductReader`` → audit via ``agent_query_pevr``).

The ``consume`` tool is the one WRITE in the new MCP surface:

    1. Same gate + pre-check + denial path
    2. ``agent_query_pevr`` audit cycle for the tool call itself
    3. On success, ``deps.ledger.write`` emits a ``data_product_consumed``
       PEVR (target_kind + emit_ tool primitive). The inner cycle's
       propose-payload carries ``caused_by = audit_trail_id`` so the
       consumption trace is chained back to the agent_query in a way
       projection-folders can walk.

The ``consumed_by_person_id`` payload field stores the agent's 1:1
Person id (every agent has one in v1; see W2 Task 5 agent_grant
contract). The ``consumed_by_agent_id`` field (added v1.1 Task 4,
additive per schema-evolution doctrine Rule 2) carries the AgentID
explicitly so downstream projections can distinguish agent-driven
consumption from human-driven consumption without needing to walk
the agent_grant projection.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from wormbase_inference import AgentID, GovernanceContext

from ..identity import agent_query_pevr
from .responses import (
    DataProductConsumeResponse,
    DataProductGetResponse,
    DataProductListResponse,
    DeniedResponse,
    _DataProductRow,
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


def _coerce_data_product_row(row: dict[str, Any]) -> _DataProductRow:
    """Coerce a projection_data_products row to the response shape."""
    return _DataProductRow(
        data_product_id=str(row.get("data_product_id", "")),
        name=str(row.get("name", "")),
        kind=str(row.get("kind", "")),
        status=str(row.get("status", "")),
        requested_by_person_id=(
            str(row["requested_by_person_id"])
            if row.get("requested_by_person_id")
            else None
        ),
        domain_id=(str(row["domain_id"]) if row.get("domain_id") else None),
        generated_at=_iso(row.get("generated_at")),
        content_hash=row.get("content_hash"),
        contents_uri=row.get("contents_uri"),
    )


# ---------------------------------------------------------------------------
# Tool 1: data_products.list
# ---------------------------------------------------------------------------


async def list_data_products(
    *,
    domain_id: str | None,
    status: str | None,
    limit: int,
    deps: GoldArtifactDeps,
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> DataProductListResponse | DeniedResponse:
    """List data products, optionally filtered by domain_id + status."""
    args = {
        "domain_id": domain_id,
        "status": status,
        "limit": int(limit),
    }
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="data_products.list",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="data_products.list",
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

    rows = await deps.data_product_reader.list_data_products(
        company_id=deps.company_id,
        domain_id=domain_id,
        status=status,
        limit=int(limit),
    )

    def _execute() -> dict[str, Any]:
        return {
            "row_count": len(rows),
            "result_ref": "data_products.list",
        }

    audit_trail_id = await agent_query_pevr(
        ledger=deps.ledger,
        company_id=deps.company_id,
        agent_id=agent_id,
        mcp_tool="data_products.list",
        args=pre.redacted_args,
        route_mode="broker",
        execute_fn=_execute,
    )

    return DataProductListResponse(
        audit_trail_id=audit_trail_id,
        row_count=len(rows),
        data_products=tuple(_coerce_data_product_row(r) for r in rows),
    )


# ---------------------------------------------------------------------------
# Tool 2: data_products.get
# ---------------------------------------------------------------------------


async def get_data_product(
    *,
    data_product_id: str,
    deps: GoldArtifactDeps,
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> DataProductGetResponse | DeniedResponse:
    """Fetch a single data product by id."""
    args = {"data_product_id": data_product_id}
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="data_products.get",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="data_products.get",
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

    row = await deps.data_product_reader.get_data_product(
        company_id=deps.company_id,
        data_product_id=data_product_id,
    )

    def _execute() -> dict[str, Any]:
        return {
            "row_count": 1 if row is not None else 0,
            "result_ref": "data_products.get",
        }

    audit_trail_id = await agent_query_pevr(
        ledger=deps.ledger,
        company_id=deps.company_id,
        agent_id=agent_id,
        mcp_tool="data_products.get",
        args=pre.redacted_args,
        route_mode="broker",
        execute_fn=_execute,
    )

    return DataProductGetResponse(
        audit_trail_id=audit_trail_id,
        data_product_id=data_product_id,
        data_product=_coerce_data_product_row(row) if row else None,
    )


# ---------------------------------------------------------------------------
# Tool 3: data_products.consume  (the one WRITE in the new MCP surface)
# ---------------------------------------------------------------------------


async def consume_data_product(
    *,
    data_product_id: str,
    surface: str,
    channel: str | None,
    deps: GoldArtifactDeps,
    agent_id: AgentID,
    governance: GovernanceContext | None = None,
) -> DataProductConsumeResponse | DeniedResponse:
    """Record an agent-driven consumption of a data product.

    Emits an ``emit_data_product_consumed`` ledger PEVR cycle inside
    an enclosing ``agent_query`` audit. The inner cycle's
    propose-payload carries ``caused_by = audit_trail_id`` so the
    consumption is reconstructable from the ledger alone (i.e. follow
    caused_by edges to find every artefact the agent_query produced).

    ``surface`` ∈ {dashboard, chat, voice, export, mcp, agent, api} —
    see ``_DATA_PRODUCT_SURFACES`` in wormbase_ledger.entries. The
    canonical surface for agent-driven consumption via MCP is ``"mcp"``
    (preferred over the legacy ``"agent"`` value, which remains valid
    for back-compat).
    """
    args = {
        "data_product_id": data_product_id,
        "surface": surface,
        "channel": channel,
    }
    pre = await _pre_check(
        chain=deps.gate_chain,
        agent_id=agent_id,
        mcp_tool="data_products.consume",
        args=args,
        governance=governance,
    )
    if pre.denial is not None:
        audit = await _emit_denial_agent_query(
            ledger=deps.ledger,
            company_id=deps.company_id,
            agent_id=agent_id,
            mcp_tool="data_products.consume",
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

    # 1) Wrap the consume tool call in an agent_query PEVR cycle. The
    # emit_data_product_consumed write below chains via caused_by.
    def _execute() -> dict[str, Any]:
        return {
            "row_count": 1,
            "result_ref": data_product_id,
        }

    audit_trail_id = await agent_query_pevr(
        ledger=deps.ledger,
        company_id=deps.company_id,
        agent_id=agent_id,
        mcp_tool="data_products.consume",
        args=pre.redacted_args,
        route_mode="broker",
        execute_fn=_execute,
    )

    # 2) Emit the data_product_consumed entry. Use a target_kind +
    # emit_<kind> tool primitive so the canonical PEVR shape lands.
    #
    # Both consumed_by_person_id and consumed_by_agent_id are set:
    # in v1 every agent is 1:1 with a Person row (W2 Task 5 contract),
    # so the AgentID value satisfies the (still required) person field.
    # The new consumed_by_agent_id field (v1.1 Task 4, additive per
    # schema-evolution doctrine Rule 2) lets downstream projections
    # distinguish agent-driven consumption without walking agent_grant.
    consumption_args: dict[str, Any] = {
        "data_product_id": data_product_id,
        "consumed_by_person_id": agent_id.value,
        "consumed_by_agent_id": agent_id.value,
        "surface": surface,
        "channel": channel,
    }
    consumption_id = str(uuid4())
    await deps.ledger.write(
        company_id=deps.company_id,
        propose={
            "target_kind": "data_product_consumed",
            "ref_id": data_product_id,
            "reason": (
                f"agent {agent_id.value} consumed data_product "
                f"{data_product_id} via {surface}"
            ),
            "proposed_by": agent_id.value,
            "caused_by": audit_trail_id,
            "consumption_id": consumption_id,
        },
        execute_fn=lambda: {
            "tool": "emit_data_product_consumed",
            "args": consumption_args,
            "result_ref": data_product_id,
            "caused_by": audit_trail_id,
            "consumption_id": consumption_id,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "data_product_consumed", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "data_product_consumed",
            "consumption_id": consumption_id,
        },
    )

    return DataProductConsumeResponse(
        audit_trail_id=audit_trail_id,
        data_product_id=data_product_id,
        consumed_by_agent_id=agent_id.value,
        surface=surface,
    )


__all__ = [
    "consume_data_product",
    "get_data_product",
    "list_data_products",
]
