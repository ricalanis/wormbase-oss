"""MCP read-side tools (J1).

Eleven read tools that fold the company's ledger and project the
result through the role-aware filter. Each tool:

1. Authenticates the caller via the shared bearer-token mechanism.
2. Resolves the tenant from token claims / X-Tenant-Slug header / arg.
3. Loads the caller's role grants.
4. Applies role-aware filter (admin/installer/observer see all;
   member sees own-domain rows; unknown role sees nothing).
5. Audits the call through ``record_mcp_call``.

The fold is request-time over ``ledger.fetch(company_id)``. The
projection_runner populates ``projection_*`` SQL tables asynchronously
for hot-path optimisation; the tools fall back to the ledger fold
when the projections are empty (acceptable until Phase 2).
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from wormbase_core.mcp_tools.auth import (
    RateLimitExceeded,
    audit,
    authorize_caller,
    canonical_args_hash,
    check_rate_limit,
    clip_ua_for_audit,
    filter_rows_by_domain_access,
    resolve_user_agent,
)
from wormbase_ledger import InMemoryLedger, Ledger

logger = logging.getLogger("wormbase_core.mcp_tools.read_tools")

LedgerLike = Ledger | InMemoryLedger | Any

# Sentinel classifications that trigger audit-log clipping.
_PII_CLASSIFICATIONS = ("pii", "regulated")

# Tools registered by ``register_read_tools``. Exposed for tests.
READ_TOOL_NAMES = (
    "query_sources",
    "query_kpis",
    "query_decisions",
    "query_processes",
    "query_recurring_questions",
    "query_system_map",
    "query_data_products",
    "query_notebooks",
    "query_conversations",
    "query_persons",
    "query_audit_trail",
)


# ---------------------------------------------------------------------------
# Tiny ledger-fold helpers (one per tool, all stateless).
# ---------------------------------------------------------------------------


def _is_execute_with_tool(entry: dict[str, Any], tool: str) -> bool:
    if entry.get("kind") != "execute":
        return False
    payload = entry.get("payload") or {}
    return payload.get("tool") == tool


def _args_of(entry: dict[str, Any]) -> dict[str, Any]:
    payload = entry.get("payload") or {}
    return payload.get("args") or {}


def _ts_str(ts: Any) -> str:
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _fold_sources(
    rows: list[dict[str, Any]],
    *,
    kind: str | None,
    status: str | None,
) -> list[dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for entry in rows:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        tool = payload.get("tool")
        args = _args_of(entry)
        sid = args.get("source_id")
        if not sid:
            continue
        if tool == "emit_source_proposed":
            state[sid] = {
                "source_id": sid,
                "status": "proposed",
                "kind": args.get("source_kind"),
                "uri": args.get("uri"),
                "domain_id": None,
                "classification": args.get("suggested_classification"),
                "added_via_flow": args.get("added_via_flow"),
                "added_at": _ts_str(entry.get("ts")),
            }
        elif tool == "emit_source_confirmed" and sid in state:
            state[sid]["status"] = "confirmed"
            if args.get("domain_id"):
                state[sid]["domain_id"] = args["domain_id"]
            if args.get("classification"):
                state[sid]["classification"] = args["classification"]
        elif tool == "emit_source_connected" and sid in state:
            state[sid]["status"] = "connected"
        elif tool == "emit_source_profiled" and sid in state:
            state[sid]["status"] = "profiled"

    out = list(state.values())
    if kind:
        out = [r for r in out if r.get("kind") == kind]
    if status:
        out = [r for r in out if r.get("status") == status]
    return out


def _fold_kpis(
    rows: list[dict[str, Any]],
    *,
    domain: str | None,
) -> list[dict[str, Any]]:
    """Fold ``emit_kpi_node`` (generic tree write) + ``emit_kpi_proposed``.

    Both shapes participate in the projected KPI tree. ``emit_kpi_node``
    is the canonical full-row write; ``emit_kpi_proposed`` is a proposal
    bridge from gold aggregates.
    """
    nodes: dict[str, dict[str, Any]] = {}
    for entry in rows:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        tool = payload.get("tool")
        args = _args_of(entry)
        if tool == "emit_kpi_node":
            node_id = args.get("id")
            if node_id is None:
                continue
            nodes[node_id] = dict(args)
        elif tool == "emit_kpi_proposed":
            kpi_id = args.get("kpi_id")
            if kpi_id is None:
                continue
            nodes[kpi_id] = {
                "id": kpi_id,
                "name": args.get("label"),
                "formula": args.get("formula"),
                "owner_position": args.get("owner_position"),
                "domain_id": None,
                "status": "proposed",
                "proposed_at": _ts_str(entry.get("ts")),
                "source_ids": list(args.get("source_ids", [])),
            }
    out = list(nodes.values())
    if domain:
        out = [
            n for n in out
            if str(n.get("domain_id") or "") == domain
            or n.get("domain") == domain
        ]
    return out


def _fold_decisions(
    rows: list[dict[str, Any]],
    *,
    since: datetime | None,
    domain: str | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in rows:
        if not _is_execute_with_tool(entry, "emit_decision_recorded"):
            continue
        ts = entry.get("ts")
        if since and ts and ts < since:
            continue
        args = _args_of(entry)
        out.append(
            {
                "decision_id": args.get("decision_id"),
                "decision_text": args.get("decision_text"),
                "decision_at": _ts_str(args.get("decision_at") or ts),
                "channel_id": args.get("channel_id"),
                "decided_by_persons": list(args.get("decided_by_persons") or []),
                "evidence_message_ids": list(args.get("evidence_message_ids") or []),
                "confidence": args.get("confidence"),
                "domain_id": args.get("domain_id"),
            }
        )
    if domain:
        out = [d for d in out if d.get("domain_id") == domain]
    return out


def _fold_processes(
    rows: list[dict[str, Any]],
    *,
    domain: str | None,
) -> list[dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for entry in rows:
        if not _is_execute_with_tool(entry, "emit_process_map_proposed"):
            continue
        args = _args_of(entry)
        pid = args.get("process_id")
        if not pid:
            continue
        state[pid] = {
            "process_id": pid,
            "process_name": args.get("process_name"),
            "domain": args.get("domain"),
            "domain_id": args.get("domain_id"),
            "steps": list(args.get("steps") or []),
            "confidence": args.get("confidence"),
            "proposed_at": _ts_str(entry.get("ts")),
        }
    out = list(state.values())
    if domain:
        out = [
            p for p in out
            if p.get("domain") == domain or str(p.get("domain_id") or "") == domain
        ]
    return out


def _fold_recurring_questions(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for entry in rows:
        if not _is_execute_with_tool(entry, "emit_recurring_question"):
            continue
        args = _args_of(entry)
        qid = args.get("question_id")
        if not qid:
            continue
        state[qid] = {
            "question_id": qid,
            "normalized_question": args.get("normalized_question"),
            "asked_by_persons": list(args.get("asked_by_persons") or []),
            "occurrences": args.get("occurrences"),
            "first_seen_at": _ts_str(args.get("first_seen_at")),
            "last_seen_at": _ts_str(args.get("last_seen_at")),
            "suggested_automation": args.get("suggested_automation"),
        }
    return list(state.values())


def _fold_system_map(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for entry in rows:
        if not _is_execute_with_tool(entry, "emit_system_map_node"):
            continue
        args = _args_of(entry)
        node_id = args.get("node_id")
        if not node_id:
            continue
        nodes[node_id] = {
            "node_id": node_id,
            "node_kind": args.get("node_kind"),
        }
        for e in args.get("edges") or []:
            edges.append(
                {
                    "from": node_id,
                    "to": e.get("target_id"),
                    "kind": e.get("kind"),
                    "weight": e.get("weight"),
                }
            )
    return {"nodes": list(nodes.values()), "edges": edges}


def _fold_data_products(
    rows: list[dict[str, Any]],
    *,
    kind: str | None,
    requested_by: str | None,
) -> list[dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for entry in rows:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        tool = payload.get("tool")
        args = _args_of(entry)
        dpid = args.get("data_product_id")
        if not dpid:
            continue
        if tool == "emit_data_product_proposed":
            state[dpid] = {
                "data_product_id": dpid,
                "name": args.get("name"),
                "kind": args.get("kind"),
                "status": "proposed",
                "requested_by_person_id": args.get("requested_by_person_id"),
                "domain_id": args.get("domain_id"),
                "generated_at": None,
                "content_hash": None,
                "contents_uri": None,
            }
        elif tool == "emit_data_product_generated" and dpid in state:
            state[dpid]["status"] = "generated"
            state[dpid]["generated_at"] = _ts_str(entry.get("ts"))
            state[dpid]["content_hash"] = args.get("content_hash")
            state[dpid]["contents_uri"] = args.get("contents_uri")
        elif tool == "emit_data_product_archived" and dpid in state:
            state[dpid]["status"] = "archived"

    out = list(state.values())
    if kind:
        out = [r for r in out if r.get("kind") == kind]
    if requested_by:
        out = [r for r in out if r.get("requested_by_person_id") == requested_by]
    return out


def _fold_notebooks(
    rows: list[dict[str, Any]],
    *,
    owner_person_id: str | None,
) -> list[dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for entry in rows:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        tool = payload.get("tool")
        args = _args_of(entry)
        nbid = args.get("notebook_id")
        if not nbid:
            continue
        if tool == "emit_notebook_proposed":
            state[nbid] = {
                "notebook_id": nbid,
                "name": args.get("name"),
                "kernel": args.get("kernel"),
                "status": "proposed",
                "owner_person_id": args.get("proposed_by_person_id"),
                "domain_id": args.get("domain_id"),
                "version": None,
            }
        elif tool == "emit_notebook_run" and nbid in state:
            state[nbid]["status"] = args.get("status") or "ok"
            state[nbid]["latest_run_id"] = args.get("run_id")
        elif tool == "emit_notebook_published" and nbid in state:
            state[nbid]["status"] = "published"
            state[nbid]["version"] = args.get("version")
            state[nbid]["owner_person_id"] = args.get("owner_person_id")
        elif tool == "emit_notebook_archived" and nbid in state:
            state[nbid]["status"] = "archived"

    out = list(state.values())
    if owner_person_id:
        out = [n for n in out if n.get("owner_person_id") == owner_person_id]
    return out


def _fold_conversations(
    rows: list[dict[str, Any]],
    *,
    channel_id: str | None,
    since: datetime | None,
    limit: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in rows:
        if not _is_execute_with_tool(entry, "emit_chat_received"):
            continue
        ts = entry.get("ts")
        if since and ts and ts < since:
            continue
        args = _args_of(entry)
        if channel_id and args.get("channel_id") != channel_id:
            continue
        out.append(
            {
                "channel_id": args.get("channel_id"),
                "message_id": args.get("message_id"),
                "sender_person": args.get("sender_person"),
                "text": args.get("text"),
                "classification": args.get("classification"),
                "ts": _ts_str(ts),
            }
        )
    # Most recent first.
    out.sort(key=lambda r: r.get("ts") or "", reverse=True)
    return out[: max(0, limit)]


def _fold_persons(
    rows: list[dict[str, Any]],
    *,
    role_filter: str | None,
) -> list[dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    grants: list[dict[str, Any]] = []
    for entry in rows:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        tool = payload.get("tool")
        args = _args_of(entry)
        if tool == "emit_person_proposed":
            pid = args.get("person_id")
            if not pid:
                continue
            state[pid] = {
                "person_id": pid,
                "name": args.get("name"),
                "email": args.get("email"),
                "position": args.get("position"),
                "status": "proposed",
                "tenant_id": args.get("tenant_id"),
            }
        elif tool == "emit_person_confirmed":
            pid = args.get("person_id")
            if pid in state:
                state[pid]["status"] = "active"
        elif tool == "emit_person_archived":
            pid = args.get("person_id")
            if pid in state:
                state[pid]["status"] = "archived"
        elif tool == "emit_role_assigned":
            grants.append(
                {
                    "person_id": args.get("person_id"),
                    "facet": "tenancy",
                    "role": args.get("role"),
                    "scope_id": None,
                }
            )
        elif tool == "emit_domain_role_assigned":
            grants.append(
                {
                    "person_id": args.get("person_id"),
                    "facet": "domain",
                    "role": args.get("role"),
                    "scope_id": args.get("domain_id"),
                }
            )
        elif tool == "emit_resource_role_assigned":
            grants.append(
                {
                    "person_id": args.get("person_id"),
                    "facet": "resource",
                    "role": args.get("role"),
                    "scope_id": args.get("resource_id"),
                }
            )

    # Attach grant lists to person rows.
    for p in state.values():
        p["grants"] = [g for g in grants if g["person_id"] == p["person_id"]]
    out = list(state.values())
    if role_filter:
        out = [
            p for p in out
            if any(
                g["role"] == role_filter for g in p["grants"]
            )
        ]
    return out


def _fold_audit_trail(
    rows: list[dict[str, Any]],
    *,
    person_id: str | None,
    resource_id: str | None,
    since: datetime | None,
) -> list[dict[str, Any]]:
    """Return execute entries where the args reference the filter target.

    Audit trail = every PEVR execute entry. Filtering is by:
    - ``person_id`` — entries where ``proposed_by``/``person_id``/
      ``confirmed_by`` references the person.
    - ``resource_id`` — entries whose args ref_id / data_product_id /
      source_id / notebook_id / kpi_id matches.
    - ``since`` — entries with ``ts >= since``.
    """
    out: list[dict[str, Any]] = []
    refs = (
        "person_id",
        "data_product_id",
        "source_id",
        "notebook_id",
        "kpi_id",
        "decision_id",
        "process_id",
        "resource_id",
    )
    for entry in rows:
        if entry.get("kind") != "execute":
            continue
        ts = entry.get("ts")
        if since and ts and ts < since:
            continue
        payload = entry.get("payload") or {}
        args = _args_of(entry)
        if person_id is not None:
            referenced = (
                args.get("person_id") == person_id
                or args.get("confirmed_by") == person_id
                or args.get("granted_by") == person_id
                or args.get("requested_by_person_id") == person_id
                or args.get("caller_person_id") == person_id
            )
            if not referenced:
                continue
        if resource_id is not None:
            if not any(args.get(k) == resource_id for k in refs):
                continue
        out.append(
            {
                "seq": entry.get("seq"),
                "ts": _ts_str(ts),
                "tool": payload.get("tool"),
                "args": args,
            }
        )
    return out


def _row_classifications(rows: list[dict[str, Any]]) -> set[str]:
    """Return the set of distinct classifications appearing in projection rows."""
    out: set[str] = set()
    for r in rows:
        c = r.get("classification")
        if c:
            out.add(str(c).lower())
    return out


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_read_tools(
    mcp: FastMCP,
    *,
    ledger: LedgerLike,
    api_token: str,
) -> None:
    """Register all 11 read-side MCP tools on the FastMCP instance."""

    async def _setup_call(
        ctx: Context,
        *,
        company_id_arg: str,
        tool_name: str,
        request_args: dict[str, Any],
    ) -> tuple[Any, str, str | None, datetime, float]:
        """Common preamble: authn + rate-limit. Returns CallerContext."""
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
            # Best-effort denied-audit on the resolved tenant; fall back to
            # the raw arg if even that fails.
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

        # Rate-limit check (writes a denied audit on breach).
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

    async def _finish_call(
        *,
        caller: Any,
        tool_name: str,
        args_hash: str,
        client_ua: str | None,
        started_at: datetime,
        t0: float,
        outcome: str,
        result_rows: list[Any] | None = None,
        has_pii: bool = False,
    ) -> None:
        elapsed = int((time.perf_counter() - t0) * 1000)
        ua = clip_ua_for_audit(client_ua, has_pii=has_pii)
        await audit(
            ledger,
            company_id=caller["company_id"],
            caller_person_id=caller["caller_person_id"],
            tool_name=tool_name,
            args_hash=args_hash,
            client_ua=ua,
            started_at=started_at,
            outcome=outcome,
            latency_ms=elapsed,
        )

    # -----------------------------------------------------------------
    # query_sources
    # -----------------------------------------------------------------
    @mcp.tool()
    async def query_sources(
        company_id: str,
        ctx: Context,
        kind: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return source rows with cascade state (proposed / confirmed / connected / profiled)."""
        request_args = {"company_id": company_id, "kind": kind, "status": status}
        caller, args_hash, ua, started_at, t0 = await _setup_call(
            ctx,
            company_id_arg=company_id,
            tool_name="query_sources",
            request_args=request_args,
        )
        rows = await ledger.fetch(caller["company_id"])
        sources = _fold_sources(rows, kind=kind, status=status)
        filtered = filter_rows_by_domain_access(
            sources,
            tenancy_role=caller["tenancy_role"],
            domains=caller["domain_access"],
        )
        has_pii = bool(_row_classifications(filtered) & set(_PII_CLASSIFICATIONS))
        await _finish_call(
            caller=caller, tool_name="query_sources",
            args_hash=args_hash, client_ua=ua, started_at=started_at, t0=t0,
            outcome="ok", has_pii=has_pii,
        )
        return filtered

    # -----------------------------------------------------------------
    # query_kpis
    # -----------------------------------------------------------------
    @mcp.tool()
    async def query_kpis(
        company_id: str,
        ctx: Context,
        domain: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the KPI tree (optionally domain-filtered)."""
        request_args = {"company_id": company_id, "domain": domain}
        caller, args_hash, ua, started_at, t0 = await _setup_call(
            ctx,
            company_id_arg=company_id,
            tool_name="query_kpis",
            request_args=request_args,
        )
        rows = await ledger.fetch(caller["company_id"])
        kpis = _fold_kpis(rows, domain=domain)
        filtered = filter_rows_by_domain_access(
            kpis,
            tenancy_role=caller["tenancy_role"],
            domains=caller["domain_access"],
        )
        await _finish_call(
            caller=caller, tool_name="query_kpis",
            args_hash=args_hash, client_ua=ua, started_at=started_at, t0=t0,
            outcome="ok",
        )
        return filtered

    # -----------------------------------------------------------------
    # query_decisions
    # -----------------------------------------------------------------
    @mcp.tool()
    async def query_decisions(
        company_id: str,
        ctx: Context,
        since: str | None = None,
        domain: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return decisions extracted by the process_extractor."""
        request_args = {"company_id": company_id, "since": since, "domain": domain}
        caller, args_hash, ua, started_at, t0 = await _setup_call(
            ctx,
            company_id_arg=company_id,
            tool_name="query_decisions",
            request_args=request_args,
        )
        rows = await ledger.fetch(caller["company_id"])
        decisions = _fold_decisions(
            rows, since=_parse_iso(since), domain=domain,
        )
        filtered = filter_rows_by_domain_access(
            decisions,
            tenancy_role=caller["tenancy_role"],
            domains=caller["domain_access"],
        )
        await _finish_call(
            caller=caller, tool_name="query_decisions",
            args_hash=args_hash, client_ua=ua, started_at=started_at, t0=t0,
            outcome="ok",
        )
        return filtered

    # -----------------------------------------------------------------
    # query_processes
    # -----------------------------------------------------------------
    @mcp.tool()
    async def query_processes(
        company_id: str,
        ctx: Context,
        domain: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return process maps extracted from chatter."""
        request_args = {"company_id": company_id, "domain": domain}
        caller, args_hash, ua, started_at, t0 = await _setup_call(
            ctx,
            company_id_arg=company_id,
            tool_name="query_processes",
            request_args=request_args,
        )
        rows = await ledger.fetch(caller["company_id"])
        processes = _fold_processes(rows, domain=domain)
        filtered = filter_rows_by_domain_access(
            processes,
            tenancy_role=caller["tenancy_role"],
            domains=caller["domain_access"],
        )
        await _finish_call(
            caller=caller, tool_name="query_processes",
            args_hash=args_hash, client_ua=ua, started_at=started_at, t0=t0,
            outcome="ok",
        )
        return filtered

    # -----------------------------------------------------------------
    # query_recurring_questions
    # -----------------------------------------------------------------
    @mcp.tool()
    async def query_recurring_questions(
        company_id: str,
        ctx: Context,
    ) -> list[dict[str, Any]]:
        """Return the recurring-questions panel data (Carol's "x4 'what's Q3 revenue'" beat)."""
        request_args = {"company_id": company_id}
        caller, args_hash, ua, started_at, t0 = await _setup_call(
            ctx,
            company_id_arg=company_id,
            tool_name="query_recurring_questions",
            request_args=request_args,
        )
        rows = await ledger.fetch(caller["company_id"])
        questions = _fold_recurring_questions(rows)
        # Recurring questions don't carry domain_id at the payload level,
        # so admins/observers see all and members see all (the panel is
        # informational, not classified).
        if caller["tenancy_role"] not in ("admin", "installer", "observer", "member"):
            questions = []
        await _finish_call(
            caller=caller, tool_name="query_recurring_questions",
            args_hash=args_hash, client_ua=ua, started_at=started_at, t0=t0,
            outcome="ok",
        )
        return questions

    # -----------------------------------------------------------------
    # query_system_map
    # -----------------------------------------------------------------
    @mcp.tool()
    async def query_system_map(
        company_id: str,
        ctx: Context,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return the who-asks-whom system map ({nodes, edges})."""
        request_args = {"company_id": company_id}
        caller, args_hash, ua, started_at, t0 = await _setup_call(
            ctx,
            company_id_arg=company_id,
            tool_name="query_system_map",
            request_args=request_args,
        )
        rows = await ledger.fetch(caller["company_id"])
        graph = _fold_system_map(rows)
        if caller["tenancy_role"] not in ("admin", "installer", "observer", "member"):
            graph = {"nodes": [], "edges": []}
        await _finish_call(
            caller=caller, tool_name="query_system_map",
            args_hash=args_hash, client_ua=ua, started_at=started_at, t0=t0,
            outcome="ok",
        )
        return graph

    # -----------------------------------------------------------------
    # query_data_products
    # -----------------------------------------------------------------
    @mcp.tool()
    async def query_data_products(
        company_id: str,
        ctx: Context,
        kind: str | None = None,
        requested_by: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return Block F data-product artifacts."""
        request_args = {
            "company_id": company_id, "kind": kind,
            "requested_by": requested_by,
        }
        caller, args_hash, ua, started_at, t0 = await _setup_call(
            ctx,
            company_id_arg=company_id,
            tool_name="query_data_products",
            request_args=request_args,
        )
        rows = await ledger.fetch(caller["company_id"])
        products = _fold_data_products(
            rows, kind=kind, requested_by=requested_by,
        )
        filtered = filter_rows_by_domain_access(
            products,
            tenancy_role=caller["tenancy_role"],
            domains=caller["domain_access"],
        )
        await _finish_call(
            caller=caller, tool_name="query_data_products",
            args_hash=args_hash, client_ua=ua, started_at=started_at, t0=t0,
            outcome="ok",
        )
        return filtered

    # -----------------------------------------------------------------
    # query_notebooks
    # -----------------------------------------------------------------
    @mcp.tool()
    async def query_notebooks(
        company_id: str,
        ctx: Context,
        owner_person_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return Block F notebooks (latest version per id)."""
        request_args = {
            "company_id": company_id, "owner_person_id": owner_person_id,
        }
        caller, args_hash, ua, started_at, t0 = await _setup_call(
            ctx,
            company_id_arg=company_id,
            tool_name="query_notebooks",
            request_args=request_args,
        )
        rows = await ledger.fetch(caller["company_id"])
        notebooks = _fold_notebooks(rows, owner_person_id=owner_person_id)
        filtered = filter_rows_by_domain_access(
            notebooks,
            tenancy_role=caller["tenancy_role"],
            domains=caller["domain_access"],
        )
        await _finish_call(
            caller=caller, tool_name="query_notebooks",
            args_hash=args_hash, client_ua=ua, started_at=started_at, t0=t0,
            outcome="ok",
        )
        return filtered

    # -----------------------------------------------------------------
    # query_conversations
    # -----------------------------------------------------------------
    @mcp.tool()
    async def query_conversations(
        company_id: str,
        ctx: Context,
        channel_id: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return bronze conversation messages (most recent first, capped)."""
        request_args = {
            "company_id": company_id, "channel_id": channel_id,
            "since": since, "limit": limit,
        }
        caller, args_hash, ua, started_at, t0 = await _setup_call(
            ctx,
            company_id_arg=company_id,
            tool_name="query_conversations",
            request_args=request_args,
        )
        rows = await ledger.fetch(caller["company_id"])
        msgs = _fold_conversations(
            rows, channel_id=channel_id,
            since=_parse_iso(since), limit=limit,
        )
        # Conversations carry classification at the row level. Members see
        # all messages whose classification is `public` or `internal`;
        # admins / observers see everything.
        if caller["tenancy_role"] == "member":
            msgs = [
                m for m in msgs
                if (m.get("classification") or "internal") in ("public", "internal")
            ]
        elif caller["tenancy_role"] not in ("admin", "installer", "observer"):
            msgs = []
        has_pii = bool(_row_classifications(msgs) & set(_PII_CLASSIFICATIONS))
        await _finish_call(
            caller=caller, tool_name="query_conversations",
            args_hash=args_hash, client_ua=ua, started_at=started_at, t0=t0,
            outcome="ok", has_pii=has_pii,
        )
        return msgs

    # -----------------------------------------------------------------
    # query_persons
    # -----------------------------------------------------------------
    @mcp.tool()
    async def query_persons(
        company_id: str,
        ctx: Context,
        role: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return Person rows with role grants attached."""
        request_args = {"company_id": company_id, "role": role}
        caller, args_hash, ua, started_at, t0 = await _setup_call(
            ctx,
            company_id_arg=company_id,
            tool_name="query_persons",
            request_args=request_args,
        )
        rows = await ledger.fetch(caller["company_id"])
        persons = _fold_persons(rows, role_filter=role)
        # Members can only see themselves + their own grants. Admins +
        # installers see everyone. Observers see read-only-all.
        if caller["tenancy_role"] == "member" and caller["caller_person_id"]:
            persons = [
                p for p in persons
                if p.get("person_id") == str(caller["caller_person_id"])
            ]
        elif caller["tenancy_role"] not in (
            "admin", "installer", "observer",
        ):
            persons = []
        has_pii = any(p.get("email") for p in persons)
        await _finish_call(
            caller=caller, tool_name="query_persons",
            args_hash=args_hash, client_ua=ua, started_at=started_at, t0=t0,
            outcome="ok", has_pii=has_pii,
        )
        return persons

    # -----------------------------------------------------------------
    # query_audit_trail
    # -----------------------------------------------------------------
    @mcp.tool()
    async def query_audit_trail(
        company_id: str,
        ctx: Context,
        person_id: str | None = None,
        resource_id: str | None = None,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return execute-entry audit traces (governance view).

        Admin-only by default; members get an empty list (the audit log
        is more sensitive than the data, so we lock it to admins).
        """
        request_args = {
            "company_id": company_id, "person_id": person_id,
            "resource_id": resource_id, "since": since,
        }
        caller, args_hash, ua, started_at, t0 = await _setup_call(
            ctx,
            company_id_arg=company_id,
            tool_name="query_audit_trail",
            request_args=request_args,
        )
        if caller["tenancy_role"] not in ("admin", "installer"):
            await _finish_call(
                caller=caller, tool_name="query_audit_trail",
                args_hash=args_hash, client_ua=ua, started_at=started_at, t0=t0,
                outcome="denied",
            )
            return []
        rows = await ledger.fetch(caller["company_id"])
        trail = _fold_audit_trail(
            rows, person_id=person_id, resource_id=resource_id,
            since=_parse_iso(since),
        )
        await _finish_call(
            caller=caller, tool_name="query_audit_trail",
            args_hash=args_hash, client_ua=ua, started_at=started_at, t0=t0,
            outcome="ok",
        )
        return trail


__all__ = [
    "READ_TOOL_NAMES",
    "register_read_tools",
]
