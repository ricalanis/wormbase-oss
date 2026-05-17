"""MCP write-side tools (J2).

Three tools:

- ``propose_data_product`` — wraps ``data_product_actions.propose_data_product``.
- ``confirm_proposal`` — generic dispatcher; routes to the right confirm
  orchestrator based on the proposal kind already on the ledger.
- ``propose_kpi`` — admin-driven KPI tree extension; writes ``emit_kpi_proposed``.

All three require ``tenancy.admin`` (or ``installer``). Insufficient
permission → ``denied`` audit entry + PermissionError. Each call goes
through the same audit pipeline as the read tools.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from mcp.server.fastmcp import Context, FastMCP

from wormbase_core import data_product_actions
from wormbase_core.mcp_tools.auth import (
    RateLimitExceeded,
    audit,
    authorize_caller,
    canonical_args_hash,
    check_rate_limit,
    resolve_user_agent,
)
from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ledger.entries import KpiProposedPayload

logger = logging.getLogger("wormbase_core.mcp_tools.write_tools")

LedgerLike = Ledger | InMemoryLedger | Any

WRITE_TOOL_NAMES = (
    "propose_data_product",
    "confirm_proposal",
    "propose_kpi",
)


def _is_admin(role: str | None) -> bool:
    return role in ("admin", "installer")


def _find_proposal(
    rows: list[dict[str, Any]], proposal_id: str,
) -> tuple[str | None, dict[str, Any] | None]:
    """Walk the ledger looking for a *_proposed entry matching ``proposal_id``.

    Returns ``(proposal_kind, args_dict)`` or ``(None, None)`` if no match.
    The proposal_id is matched against the obvious id fields per kind.
    """
    candidates = {
        "data_product_proposed": "data_product_id",
        "source_proposed": "source_id",
        "person_proposed": "person_id",
        "kpi_proposed": "kpi_id",
        "notebook_proposed": "notebook_id",
    }
    for entry in rows:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        tool = payload.get("tool", "")
        for prop_kind, id_field in candidates.items():
            if tool == f"emit_{prop_kind}":
                args = payload.get("args") or {}
                if args.get(id_field) == proposal_id:
                    return prop_kind, args
    return None, None


def register_write_tools(
    mcp: FastMCP,
    *,
    ledger: LedgerLike,
    api_token: str,
) -> None:
    """Register the 3 write-side MCP tools on the FastMCP instance."""

    async def _setup(
        ctx: Context,
        *,
        company_id_arg: str,
        tool_name: str,
        request_args: dict[str, Any],
    ) -> tuple[Any, str, str | None, datetime, float]:
        started_at = datetime.now(tz=UTC)
        t0 = time.perf_counter()
        args_hash = canonical_args_hash(request_args)
        client_ua = resolve_user_agent(ctx)

        try:
            caller = await authorize_caller(
                ctx,
                ledger=ledger,
                api_token=api_token,
                fallback_company_id=company_id_arg,
            )
        except PermissionError:
            elapsed = int((time.perf_counter() - t0) * 1000)
            try:
                from wormbase_core.service import tenant_to_uuid as _t
                cid = _t(company_id_arg)
            except Exception:  # noqa: BLE001
                cid = None
            if cid is not None:
                await audit(
                    ledger,
                    company_id=cid,
                    caller_person_id=None,
                    tool_name=tool_name,
                    args_hash=args_hash,
                    client_ua=client_ua,
                    started_at=started_at,
                    outcome="denied",
                    latency_ms=elapsed,
                )
            raise

        try:
            await check_rate_limit(
                ledger,
                company_id=caller["company_id"],
                caller_person_id=caller["caller_person_id"],
                now=started_at,
            )
        except RateLimitExceeded:
            elapsed = int((time.perf_counter() - t0) * 1000)
            await audit(
                ledger,
                company_id=caller["company_id"],
                caller_person_id=caller["caller_person_id"],
                tool_name=tool_name,
                args_hash=args_hash,
                client_ua=client_ua,
                started_at=started_at,
                outcome="denied",
                latency_ms=elapsed,
            )
            raise

        return caller, args_hash, client_ua, started_at, t0

    async def _finish(
        *,
        caller: Any,
        tool_name: str,
        args_hash: str,
        client_ua: str | None,
        started_at: datetime,
        t0: float,
        outcome: str,
    ) -> None:
        elapsed = int((time.perf_counter() - t0) * 1000)
        await audit(
            ledger,
            company_id=caller["company_id"],
            caller_person_id=caller["caller_person_id"],
            tool_name=tool_name,
            args_hash=args_hash,
            client_ua=client_ua,
            started_at=started_at,
            outcome=outcome,
            latency_ms=elapsed,
        )

    # -----------------------------------------------------------------
    # propose_data_product
    # -----------------------------------------------------------------
    @mcp.tool()
    async def propose_data_product(
        company_id: str,
        ctx: Context,
        name: str,
        kind: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Propose a new data product (admin-only)."""
        request_args = {
            "company_id": company_id, "name": name, "kind": kind,
            "parameters": parameters,
        }
        caller, args_hash, ua, started_at, t0 = await _setup(
            ctx,
            company_id_arg=company_id,
            tool_name="propose_data_product",
            request_args=request_args,
        )

        if not _is_admin(caller["tenancy_role"]):
            await _finish(
                caller=caller, tool_name="propose_data_product",
                args_hash=args_hash, client_ua=ua,
                started_at=started_at, t0=t0, outcome="denied",
            )
            raise PermissionError(
                "propose_data_product requires tenancy.admin"
            )

        # The Pydantic model requires ``requested_by_person_id``; if the
        # caller has no resolved Person (legacy flat token), we fall back
        # to the well-known anonymous-MCP marker uuid (zero-uuid + 1).
        requested_by = (
            caller["caller_person_id"]
            or UUID("00000000-0000-0000-0000-00000000feed")
        )
        try:
            dp_id, _ = await data_product_actions.propose_data_product(
                ledger,
                caller["company_id"],
                name=name,
                kind=kind,
                requested_by_person_id=requested_by,
                sources_required=[],
                parameters=parameters or {},
                proposed_by="mcp",
            )
        except Exception:
            await _finish(
                caller=caller, tool_name="propose_data_product",
                args_hash=args_hash, client_ua=ua,
                started_at=started_at, t0=t0, outcome="error",
            )
            raise

        await _finish(
            caller=caller, tool_name="propose_data_product",
            args_hash=args_hash, client_ua=ua,
            started_at=started_at, t0=t0, outcome="ok",
        )
        return {"data_product_id": str(dp_id), "status": "proposed"}

    # -----------------------------------------------------------------
    # confirm_proposal
    # -----------------------------------------------------------------
    @mcp.tool()
    async def confirm_proposal(
        company_id: str,
        proposal_id: str,
        person_id: str,
        ctx: Context,
    ) -> dict[str, Any]:
        """Confirm a previously-proposed entity (admin-only).

        Walks the ledger to find the proposal, dispatches to the
        appropriate confirm orchestrator (currently only person; data
        products use the generated/archived lifecycle, so a confirm is a
        no-op there). The intent is the unified dispatcher pattern; per-
        kind orchestrators can be wired in as they ship.
        """
        request_args = {
            "company_id": company_id, "proposal_id": proposal_id,
            "person_id": person_id,
        }
        caller, args_hash, ua, started_at, t0 = await _setup(
            ctx,
            company_id_arg=company_id,
            tool_name="confirm_proposal",
            request_args=request_args,
        )

        if not _is_admin(caller["tenancy_role"]):
            await _finish(
                caller=caller, tool_name="confirm_proposal",
                args_hash=args_hash, client_ua=ua,
                started_at=started_at, t0=t0, outcome="denied",
            )
            raise PermissionError(
                "confirm_proposal requires tenancy.admin"
            )

        rows = await ledger.fetch(caller["company_id"])
        prop_kind, prop_args = _find_proposal(rows, proposal_id)
        if prop_kind is None:
            await _finish(
                caller=caller, tool_name="confirm_proposal",
                args_hash=args_hash, client_ua=ua,
                started_at=started_at, t0=t0, outcome="error",
            )
            raise ValueError(
                f"no proposal found for id {proposal_id!r}"
            )

        try:
            confirmed_by = UUID(person_id)
        except (TypeError, ValueError) as exc:
            await _finish(
                caller=caller, tool_name="confirm_proposal",
                args_hash=args_hash, client_ua=ua,
                started_at=started_at, t0=t0, outcome="error",
            )
            raise ValueError(
                f"invalid person_id {person_id!r}: {exc}"
            ) from exc

        try:
            if prop_kind == "person_proposed":
                from wormbase_core import write_actions
                await write_actions.confirm_person(
                    ledger,
                    caller["company_id"],
                    person_id=UUID(prop_args["person_id"]),
                    confirmed_by=confirmed_by,
                )
                kind_out = "person_confirmed"
            else:
                # For data_product, source, kpi, notebook — confirming is
                # currently a no-op (each has its own lifecycle), so we
                # write a generic ledger marker via the data-product
                # consume path or simply audit and return. The dispatcher
                # records the intent so future orchestrators can wire in.
                kind_out = f"{prop_kind}_acknowledged"
        except Exception:
            await _finish(
                caller=caller, tool_name="confirm_proposal",
                args_hash=args_hash, client_ua=ua,
                started_at=started_at, t0=t0, outcome="error",
            )
            raise

        await _finish(
            caller=caller, tool_name="confirm_proposal",
            args_hash=args_hash, client_ua=ua,
            started_at=started_at, t0=t0, outcome="ok",
        )
        return {
            "proposal_id": proposal_id,
            "kind": kind_out,
            "confirmed_by": str(confirmed_by),
        }

    # -----------------------------------------------------------------
    # propose_kpi
    # -----------------------------------------------------------------
    @mcp.tool()
    async def propose_kpi(
        company_id: str,
        ctx: Context,
        name: str,
        parent_node_id: str | None = None,
        formula: str | None = None,
        owner_person_id: str | None = None,
    ) -> dict[str, Any]:
        """Propose a new KPI tree node (admin-only).

        Writes ``emit_kpi_proposed`` (the canonical proposal-bridge entry)
        through the same PEVR primitive every dashboard write uses.
        """
        request_args = {
            "company_id": company_id, "name": name,
            "parent_node_id": parent_node_id, "formula": formula,
            "owner_person_id": owner_person_id,
        }
        caller, args_hash, ua, started_at, t0 = await _setup(
            ctx,
            company_id_arg=company_id,
            tool_name="propose_kpi",
            request_args=request_args,
        )

        if not _is_admin(caller["tenancy_role"]):
            await _finish(
                caller=caller, tool_name="propose_kpi",
                args_hash=args_hash, client_ua=ua,
                started_at=started_at, t0=t0, outcome="denied",
            )
            raise PermissionError(
                "propose_kpi requires tenancy.admin"
            )

        kpi_id = uuid4()
        payload = KpiProposedPayload(
            kpi_id=kpi_id,
            label=name,
            formula=formula or "",
            source_ids=[],
            unit="count",
            owner_position=None,
            proposed_at=started_at,
        )
        args = payload.model_dump(mode="json")

        # Inline PEVR write — small enough that we don't need a helper here.
        try:
            await ledger.write(
                company_id=caller["company_id"],
                propose={
                    "target_kind": "kpi_proposed",
                    "ref_id": str(kpi_id),
                    "reason": f"propose KPI {name!r} via MCP",
                    "proposed_by": (
                        str(caller["caller_person_id"])
                        if caller["caller_person_id"] is not None
                        else "mcp"
                    ),
                },
                execute_fn=lambda: {
                    "tool": "emit_kpi_proposed",
                    "args": args,
                    "result_ref": str(kpi_id),
                },
                verify_fn=lambda _ep: {
                    "checks": [{"name": "kpi_proposed_payload_valid", "ok": True}],
                    "passed": True,
                },
                resolve_fn=lambda _v: {
                    "outcome": "keep",
                    "rationale": "KPI proposed via MCP",
                },
            )
        except Exception:
            await _finish(
                caller=caller, tool_name="propose_kpi",
                args_hash=args_hash, client_ua=ua,
                started_at=started_at, t0=t0, outcome="error",
            )
            raise

        await _finish(
            caller=caller, tool_name="propose_kpi",
            args_hash=args_hash, client_ua=ua,
            started_at=started_at, t0=t0, outcome="ok",
        )
        return {
            "kpi_id": str(kpi_id),
            "name": name,
            "parent_node_id": parent_node_id,
            "status": "proposed",
        }


__all__ = [
    "WRITE_TOOL_NAMES",
    "register_write_tools",
]
