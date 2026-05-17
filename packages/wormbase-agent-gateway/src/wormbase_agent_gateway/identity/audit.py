"""agent_query PEVR helper — wraps :meth:`Ledger.write` with gateway-specific fns.

Per doctrine Addendum 3: ONE entry kind (``agent_query``), FOUR phases. The
helper assembles the four phase callables and delegates to
``Ledger.write(propose=, execute_fn=, verify_fn=, resolve_fn=)`` — there
are no per-phase ``emit_agent_query_*`` helpers.

The canonical ``Ledger.write`` signature observed in
``packages/ledger/src/wormbase_ledger/ledger_api.py`` (and matched by
``InMemoryLedger``)::

    await ledger.write(
        company_id=UUID,
        propose=dict[str, Any],
        execute_fn=Callable[[], dict[str, Any]],
        verify_fn=Callable[[dict[str, Any]], dict[str, Any]],
        resolve_fn=Callable[[dict[str, Any]], dict[str, Any]],
        timestamp=datetime | None,
        quadrant=Quadrant,
    ) -> WriteResult

Per-phase callbacks are **synchronous** (return plain dicts), not async —
this matches the lake-maintainer ``_emit_signal`` pattern. If the
execute step needs to do async work, run it BEFORE the ``ledger.write``
call and pass the result into the closure.

Payload shape: each phase's dict is the JSON-serialized form of an
:class:`AgentQueryPayload` for that phase. The four envelope kinds
land as ``propose`` / ``execute`` / ``verify`` / ``resolve`` (the
PEVR standard), and the agent_query semantics live in the payload —
``projection_agent_queries`` folds all four into one row by
``audit_trail_id``.
"""
from __future__ import annotations

from typing import Any, Callable, Literal
from uuid import UUID, uuid4

from wormbase_inference import AgentID
from wormbase_ledger.entries import AgentQueryPayload


def _payload_for_phase(
    *,
    agent_id: str,
    mcp_tool: str,
    args: dict[str, Any],
    route_mode: Literal["broker", "federate"],
    phase: Literal["propose", "execute", "verify", "resolve"],
    caused_by: str | None = None,
    row_count: int | None = None,
    cost_usd: str | None = None,
    latency_ms: int | None = None,
) -> dict[str, Any]:
    """Build a JSON-safe AgentQueryPayload dict for one phase."""
    p = AgentQueryPayload(
        agent_id=agent_id,
        mcp_tool=mcp_tool,
        args=args,
        route_mode=route_mode,
        phase=phase,
        caused_by=caused_by,
        row_count=row_count,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
    )
    return p.model_dump()


async def agent_query_pevr(
    *,
    ledger: Any,
    company_id: UUID,
    agent_id: AgentID,
    mcp_tool: str,
    args: dict[str, Any],
    route_mode: Literal["broker", "federate"],
    execute_fn: Callable[[], dict[str, Any]],
    verify_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    caused_by: str | None = None,
) -> str:
    """Write a 4-phase ``agent_query`` PEVR cycle via the canonical primitive.

    Returns the ``audit_trail_id`` — the stable cross-phase correlation
    key folded into ``projection_agent_queries`` (single row per cycle).

    Args:
        ledger: A ``Ledger`` or ``InMemoryLedger`` with the canonical
            async ``write(company_id=, propose=, execute_fn=, verify_fn=,
            resolve_fn=, ...)`` surface.
        company_id: Tenant scope; same UUID flows through all four
            envelope entries.
        agent_id: Boundary-typed agent identifier (see Wave 2 Task 4).
        mcp_tool: e.g. ``"lake.semantic.metric"``.
        args: Tool-specific JSON-safe argument dict.
        route_mode: ``"broker"`` (gateway issues a scoped data token to a
            broker SQL exec) or ``"federate"`` (gateway issues a token
            the agent uses against the upstream directly).
        execute_fn: Synchronous callback returning the execute-phase
            body. Must include observed measurements (``row_count``,
            ``cost_usd``, ``latency_ms``) when available. The helper
            wraps these into an AgentQueryPayload(phase="execute").
        verify_fn: Synchronous callback receiving the execute payload
            dict and returning ``{"passed": bool, ...}``. Defaults to a
            permissive verify that always passes when None.
        caused_by: Parent ``audit_trail_id`` when this query chains off
            a prior one (e.g. an auto-correction retry).

    The helper hides the propose/execute/verify/resolve plumbing so
    call-sites can focus on the work and the verify check.
    """
    audit_trail_id = str(uuid4())

    # Propose phase — payload-shaped dict (AgentQueryPayload @ phase="propose").
    propose_payload = _payload_for_phase(
        agent_id=agent_id.value,
        mcp_tool=mcp_tool,
        args=args,
        route_mode=route_mode,
        phase="propose",
        caused_by=caused_by,
    )
    # Attach audit_trail_id as the cycle-wide correlation key. We carry
    # it as a top-level field on every phase dict so projection-folders
    # can group cycles without recomputing entry chains.
    propose_payload["audit_trail_id"] = audit_trail_id

    def _execute() -> dict[str, Any]:
        body = execute_fn()
        # Pull observed measurements (if execute_fn surfaced them) into
        # the AgentQueryPayload @ phase="execute" shape.
        exec_payload = _payload_for_phase(
            agent_id=agent_id.value,
            mcp_tool=mcp_tool,
            args=args,
            route_mode=route_mode,
            phase="execute",
            caused_by=caused_by,
            row_count=body.get("row_count"),
            cost_usd=body.get("cost_usd"),
            latency_ms=body.get("latency_ms"),
        )
        exec_payload["audit_trail_id"] = audit_trail_id
        # Preserve any extra execute-fn returned fields (e.g. result_ref)
        # so downstream consumers can chain off them.
        for k, v in body.items():
            exec_payload.setdefault(k, v)
        return exec_payload

    def _verify(execute_payload: dict[str, Any]) -> dict[str, Any]:
        if verify_fn is not None:
            body = verify_fn(execute_payload)
        else:
            body = {"checks": [{"name": "agent_query_default", "ok": True}], "passed": True}
        verify_payload = _payload_for_phase(
            agent_id=agent_id.value,
            mcp_tool=mcp_tool,
            args=args,
            route_mode=route_mode,
            phase="verify",
            caused_by=caused_by,
            row_count=execute_payload.get("row_count"),
            cost_usd=execute_payload.get("cost_usd"),
            latency_ms=execute_payload.get("latency_ms"),
        )
        verify_payload["audit_trail_id"] = audit_trail_id
        # passed is required by the primitive; everything else is folded.
        verify_payload["passed"] = bool(body.get("passed", True))
        verify_payload["checks"] = body.get(
            "checks", [{"name": "agent_query_default", "ok": True}]
        )
        return verify_payload

    def _resolve(verify_payload: dict[str, Any]) -> dict[str, Any]:
        resolve_payload = _payload_for_phase(
            agent_id=agent_id.value,
            mcp_tool=mcp_tool,
            args=args,
            route_mode=route_mode,
            phase="resolve",
            caused_by=caused_by,
            row_count=verify_payload.get("row_count"),
            cost_usd=verify_payload.get("cost_usd"),
            latency_ms=verify_payload.get("latency_ms"),
        )
        resolve_payload["audit_trail_id"] = audit_trail_id
        resolve_payload["outcome"] = "keep" if verify_payload.get("passed") else "discard"
        resolve_payload["rationale"] = (
            "agent_query verified" if verify_payload.get("passed")
            else "agent_query verify failed"
        )
        return resolve_payload

    await ledger.write(
        company_id=company_id,
        propose=propose_payload,
        execute_fn=_execute,
        verify_fn=_verify,
        resolve_fn=_resolve,
    )
    return audit_trail_id


__all__ = ["agent_query_pevr"]
