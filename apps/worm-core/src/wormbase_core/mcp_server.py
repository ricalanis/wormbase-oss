"""MCP server for WormBase — Phase 0 spike.

Per docs/superpowers/specs/2026-04-27-mcp-integration.md §10.1.

Exposes ONE tool — ``query_ledger`` — over Streamable HTTP via FastMCP
3.0 (the official Anthropic Python SDK, package ``mcp``). Every call
audit-writes a full PEVR cycle ending in ``emit_mcp_call_received``
to the existing hash-chained ledger.

Architectural posture (Phase 0):

- Bind on a separate port (default 9911) from the existing HTTP write
  API (8910). Wired into ``cli._run_async`` as a 7th asyncio task gated
  behind ``WORMBASE_MCP_ENABLED=1``.
- Bearer-token auth: ``Authorization: Bearer <token>`` checked against
  ``WORMBASE_LEDGER_API_TOKEN`` (same token the existing HTTP write API
  uses). Missing/wrong → ``denied`` outcome on the audit + raise.
- ``args_hash`` is sha256 of canonical-encoded args; raw args never
  persist (privacy).
- Single tool, single endpoint, single audit shape — Phase 1 will add
  more tools, role-aware filtering, OAuth 2.1, etc.

Replay-stability: every audit entry is hash-chained PEVR, so replaying
the ledger produces a byte-identical projection_mcp_calls table.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from mcp.server.fastmcp import Context, FastMCP

from wormbase_core import write_actions
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger, Ledger

logger = logging.getLogger("wormbase_core.mcp_server")

DEFAULT_MCP_PORT = 9911
MCP_TOOL_NAME = "query_ledger"


def _canonical_args_hash(args: dict[str, Any]) -> str:
    """sha256-hex of canonical JSON encoding (sorted keys, no whitespace).

    The hash is replay-stable: identical args produce identical hashes
    regardless of dict insertion order.
    """
    blob = json.dumps(args, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _resolve_bearer_token(ctx: Context) -> str | None:
    """Extract the bearer token from the underlying Starlette Request.

    FastMCP's Streamable HTTP transport stashes the raw Starlette Request
    on ``ctx.request_context.request``. We read the Authorization header
    off it, strip the ``Bearer `` prefix, and return the token (or None
    if absent). Wrong tokens are NOT detected here — the caller compares
    against the configured token.
    """
    try:
        rc = ctx.request_context
    except (LookupError, ValueError):
        return None
    request = getattr(rc, "request", None)
    if request is None:
        return None
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        return None
    return auth[len("Bearer "):].strip() or None


def _resolve_user_agent(ctx: Context) -> str | None:
    """Extract the User-Agent header for ``client_ua`` audit field."""
    try:
        rc = ctx.request_context
    except (LookupError, ValueError):
        return None
    request = getattr(rc, "request", None)
    if request is None:
        return None
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    return (
        headers.get("user-agent")
        or headers.get("User-Agent")
        or None
    )


def build_mcp_server(
    *,
    ledger: Ledger | InMemoryLedger | Any,
    api_token: str,
    host: str = "0.0.0.0",
    port: int = DEFAULT_MCP_PORT,
) -> FastMCP:
    """Build a FastMCP server with the ``query_ledger`` tool wired in.

    Stateless Streamable HTTP at ``/mcp``. Caller wires this into a
    long-lived asyncio task via ``run_streamable_http_async``.
    """
    if not api_token:
        raise ValueError(
            "api_token must be non-empty; set WORMBASE_LEDGER_API_TOKEN "
            "before booting the MCP server",
        )

    mcp = FastMCP(
        "wormbase",
        host=host,
        port=port,
        # Stateless: Phase 0 spike doesn't need session resumability;
        # every request is independent. Matches the 2026 MCP roadmap's
        # recommended posture for hosted multi-tenant servers.
        stateless_http=True,
        json_response=True,
    )

    @mcp.tool()
    async def query_ledger(
        company_id: str,
        ctx: Context,
        since: str | None = None,
        kinds: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query the company's ledger for execute entries.

        Args:
            company_id: tenant slug (e.g. "baseworm") — resolved via
                ``tenant_to_uuid`` to the canonical company UUID.
            since: ISO-8601 timestamp; only entries with ``ts >= since``
                are returned. None = no lower bound.
            kinds: filter by entry kind list (e.g. ["execute"]).
                None = all kinds.
            limit: max entries to return (most recent first). 50 default.

        Returns:
            A list of ``{seq, ts, kind, tool, args, hash}`` dicts.
        """
        call_id = uuid4()
        started_at = datetime.now(tz=UTC)
        t0 = time.perf_counter()

        # Build the args hash up front so the audit row carries it
        # regardless of outcome (privacy: hash, never raw).
        request_args: dict[str, Any] = {
            "company_id": company_id,
            "since": since,
            "kinds": kinds,
            "limit": limit,
        }
        args_hash = _canonical_args_hash(request_args)
        client_ua = _resolve_user_agent(ctx)

        # Resolve the tenant. We resolve company_id from the slug here
        # because the ledger fetch is keyed on the UUID; a malformed
        # slug → 'denied' outcome with the audit landing on the
        # canonical tenant derived from the WORMBASE_TENANT_ID env (so
        # we still have a hash-chained record of the bad call).
        try:
            resolved_company_id = tenant_to_uuid(company_id)
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            audit_company_id = tenant_to_uuid(
                os.environ.get("WORMBASE_TENANT_ID", "baseworm"),
            )
            await _audit(
                ledger=ledger,
                company_id=audit_company_id,
                call_id=call_id,
                tool_name=MCP_TOOL_NAME,
                args_hash=args_hash,
                client_ua=client_ua,
                started_at=started_at,
                outcome="error",
                latency_ms=elapsed_ms,
            )
            raise ValueError(
                f"invalid company_id slug {company_id!r}: {exc}",
            ) from exc

        # Bearer-token check.
        presented = _resolve_bearer_token(ctx)
        if presented is None or presented != api_token:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            await _audit(
                ledger=ledger,
                company_id=resolved_company_id,
                call_id=call_id,
                tool_name=MCP_TOOL_NAME,
                args_hash=args_hash,
                client_ua=client_ua,
                started_at=started_at,
                outcome="denied",
                latency_ms=elapsed_ms,
            )
            raise PermissionError(
                "missing or invalid bearer token; "
                "set Authorization: Bearer <WORMBASE_LEDGER_API_TOKEN>"
            )

        # Fetch + filter the ledger. ``Ledger.fetch`` returns rows in
        # ascending seq order; we filter then take the most recent
        # ``limit`` entries.
        try:
            rows = await ledger.fetch(resolved_company_id)
        except Exception:  # noqa: BLE001
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            await _audit(
                ledger=ledger,
                company_id=resolved_company_id,
                call_id=call_id,
                tool_name=MCP_TOOL_NAME,
                args_hash=args_hash,
                client_ua=client_ua,
                started_at=started_at,
                outcome="error",
                latency_ms=elapsed_ms,
            )
            raise

        # Apply since / kinds filters.
        if since is not None:
            try:
                since_dt = datetime.fromisoformat(since)
                if since_dt.tzinfo is None:
                    since_dt = since_dt.replace(tzinfo=UTC)
            except ValueError as exc:
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                await _audit(
                    ledger=ledger,
                    company_id=resolved_company_id,
                    call_id=call_id,
                    tool_name=MCP_TOOL_NAME,
                    args_hash=args_hash,
                    client_ua=client_ua,
                    started_at=started_at,
                    outcome="error",
                    latency_ms=elapsed_ms,
                )
                raise ValueError(f"invalid 'since' iso-8601: {exc}") from exc
            rows = [r for r in rows if r["ts"] >= since_dt]

        if kinds:
            kind_set = set(kinds)
            rows = [r for r in rows if r["kind"] in kind_set]

        # Most recent first; cap at limit.
        rows = sorted(rows, key=lambda r: r["seq"], reverse=True)[:max(0, limit)]

        # Project to a stable wire shape. ``hash`` is bytes (sha256 digest)
        # so we hex-encode for JSON. ``ts`` becomes ISO-8601.
        out: list[dict[str, Any]] = []
        for r in rows:
            payload = r.get("payload") or {}
            tool = payload.get("tool") if isinstance(payload, dict) else None
            args = payload.get("args") if isinstance(payload, dict) else None
            out.append(
                {
                    "seq": int(r["seq"]),
                    "ts": (
                        r["ts"].isoformat()
                        if hasattr(r["ts"], "isoformat")
                        else str(r["ts"])
                    ),
                    "kind": r["kind"],
                    "tool": tool,
                    "args": args,
                    "hash": (
                        r["hash"].hex()
                        if isinstance(r["hash"], (bytes, bytearray))
                        else str(r["hash"])
                    ),
                }
            )

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        await _audit(
            ledger=ledger,
            company_id=resolved_company_id,
            call_id=call_id,
            tool_name=MCP_TOOL_NAME,
            args_hash=args_hash,
            client_ua=client_ua,
            started_at=started_at,
            outcome="ok",
            latency_ms=elapsed_ms,
        )
        return out

    # J1+J2+J3: register the full read/write/resource/prompt catalog on
    # top of Phase 0's query_ledger. Each register_* function is a thin
    # glue layer that re-uses the same auth + audit + role-aware filter
    # primitives from ``mcp_tools.auth``.
    from wormbase_core.mcp_tools import (
        register_audit_tools,
        register_prompts,
        register_read_tools,
        register_resources,
        register_write_tools,
    )

    register_read_tools(mcp, ledger=ledger, api_token=api_token)
    register_write_tools(mcp, ledger=ledger, api_token=api_token)
    register_audit_tools(mcp, ledger=ledger, api_token=api_token)
    register_resources(mcp, ledger=ledger, api_token=api_token)
    register_prompts(mcp, ledger=ledger, api_token=api_token)

    return mcp


async def _audit(
    *,
    ledger: Ledger | InMemoryLedger | Any,
    company_id: UUID,
    call_id: UUID,
    tool_name: str,
    args_hash: str,
    client_ua: str | None,
    started_at: datetime,
    outcome: str,
    latency_ms: int,
) -> None:
    """Audit one MCP call by driving the canonical PEVR cycle.

    Failures here are LOGGED, not raised — we do not want to mask the
    underlying tool result with an audit-write error. Phase 3 may add
    a hard-fail mode if regulatory deployments require it.
    """
    try:
        await write_actions.record_mcp_call(
            ledger,
            company_id,
            mcp_call_id=call_id,
            caller_person_id=None,  # bearer-token v1: no Person resolution yet
            tool_name=tool_name,
            args_hash=args_hash,
            client_ua=client_ua,
            started_at=started_at,
            outcome=outcome,
            latency_ms=latency_ms,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "mcp audit write failed (call_id=%s outcome=%s): %s",
            call_id, outcome, exc,
        )


def read_mcp_port(default: int = DEFAULT_MCP_PORT) -> int:
    raw = os.environ.get("WORMBASE_MCP_PORT", "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def is_mcp_enabled() -> bool:
    """Return True iff WORMBASE_MCP_ENABLED is set to a truthy value."""
    return os.environ.get("WORMBASE_MCP_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# ---------------------------------------------------------------------------
# Catalog introspection (J7 gap close — `/mcp/catalog` HTTP endpoint).
# ---------------------------------------------------------------------------
#
# The dashboard's ``/mcp`` tab calls ``getMcpCatalog()`` against a URL set
# by ``WORMBASE_MCP_CATALOG_URL``. The endpoint surfaces the registered
# tool / resource / prompt set so an admin can see what MCP clients
# (Claude Desktop, Cursor, Cline) can pull from this tenant.
#
# We source the catalog by introspecting a built FastMCP instance —
# the same instance shape the production server runs — so a registration
# that wires into FastMCP is automatically reflected in the catalog.
# Drift between the catalog and the running server is impossible by
# construction: there is no parallel registry to keep in sync.

_TOOL_KIND_BY_NAME: dict[str, str] = {}
_WRITE_TOOL_TAG = "write"
_READ_TOOL_TAG = "read"
_AUDIT_TOOL_TAG = "audit"


def _classify_tool(name: str) -> tuple[str, list[str]]:
    """Return ``(kind_tag, tags_list)`` for a tool name.

    The classifier reads the WRITE_TOOL_NAMES + AUDIT_TOOL_NAMES tuples
    from the relevant ``mcp_tools`` modules; everything else is
    read-side. The Phase 0 ``query_ledger`` tool is a read tool by design.
    """
    if not _TOOL_KIND_BY_NAME:
        from wormbase_core.mcp_tools.audit import AUDIT_TOOL_NAMES
        from wormbase_core.mcp_tools.write_tools import WRITE_TOOL_NAMES
        for n in WRITE_TOOL_NAMES:
            _TOOL_KIND_BY_NAME[n] = _WRITE_TOOL_TAG
        for n in AUDIT_TOOL_NAMES:
            _TOOL_KIND_BY_NAME[n] = _AUDIT_TOOL_TAG
    tag = _TOOL_KIND_BY_NAME.get(name, _READ_TOOL_TAG)
    tags = [tag]
    return tag, tags


async def build_catalog(
    *,
    ledger: Ledger | InMemoryLedger | Any | None = None,
    api_token: str = "catalog-introspect",
) -> dict[str, Any]:
    """Build the MCP catalog payload by introspecting a FastMCP instance.

    Returns the JSON shape consumed by
    ``apps/dashboard/lib/ledger-client.ts::getMcpCatalog``:

    .. code-block:: json

        {
          "available": true,
          "entries": [
            {"kind": "tool",     "name": "...", "description": "...", "tags": ["read"|"write"]},
            {"kind": "resource", "name": "wormbase://...", "description": "..."},
            {"kind": "prompt",   "name": "...", "description": "..."}
          ],
          "tools":     [{"name": "...", "description": "...", "kind": "read"|"write"}, ...],
          "resources": [{"uri_template": "...", "description": "...", "name": "..."}, ...],
          "prompts":   [{"name": "...", "description": "..."}, ...]
        }

    The ``entries`` array satisfies the dashboard's flat-list contract;
    the ``tools`` / ``resources`` / ``prompts`` arrays satisfy the
    MCP-spec-shaped contract requested by external clients that want
    typed access. Both are sourced from the same FastMCP introspection
    pass — there is no separate catalog registry to drift.
    """
    if ledger is None:
        ledger = InMemoryLedger()
    mcp = build_mcp_server(ledger=ledger, api_token=api_token)

    tools_meta = await mcp.list_tools()
    resources_meta = await mcp.list_resource_templates()
    prompts_meta = await mcp.list_prompts()

    entries: list[dict[str, Any]] = []
    tools_out: list[dict[str, Any]] = []
    for t in sorted(tools_meta, key=lambda x: x.name):
        kind_tag, tags = _classify_tool(t.name)
        desc = (t.description or "").strip()
        entries.append({
            "kind": "tool",
            "name": t.name,
            "description": desc,
            "tags": tags,
        })
        tools_out.append({
            "name": t.name,
            "description": desc,
            "kind": kind_tag,
        })

    resources_out: list[dict[str, Any]] = []
    for r in sorted(resources_meta, key=lambda x: getattr(x, "uriTemplate", "")):
        uri = getattr(r, "uriTemplate", None) or getattr(r, "uri_template", "")
        desc = (getattr(r, "description", None) or "").strip()
        name = getattr(r, "name", None) or uri
        entries.append({
            "kind": "resource",
            "name": uri,
            "description": desc,
        })
        resources_out.append({
            "uri_template": uri,
            "description": desc,
            "name": name,
        })

    prompts_out: list[dict[str, Any]] = []
    for p in sorted(prompts_meta, key=lambda x: x.name):
        desc = (p.description or "").strip()
        entries.append({
            "kind": "prompt",
            "name": p.name,
            "description": desc,
        })
        prompts_out.append({
            "name": p.name,
            "description": desc,
        })

    return {
        "available": True,
        "entries": entries,
        "tools": tools_out,
        "resources": resources_out,
        "prompts": prompts_out,
    }


__all__ = [
    "DEFAULT_MCP_PORT",
    "MCP_TOOL_NAME",
    "build_catalog",
    "build_mcp_server",
    "is_mcp_enabled",
    "read_mcp_port",
]
