"""MCP resources catalog (J3).

URI-addressable resources that AI clients can include as context. Each
URI carries the ``company_id`` slug; the resource handler resolves it
via ``tenant_to_uuid`` and returns the projected JSON body.

Resources are application-controlled context. Unlike tools, they do
not pass through the bearer-token auth check (the surrounding MCP
server runtime gates resource access at the session level). They DO
land in the audit log as a low-shape marker so the governance view
sees that a resource was read.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

from wormbase_core.mcp_tools.auth import audit, canonical_args_hash
from wormbase_core.mcp_tools.read_tools import (
    _fold_conversations,
    _fold_data_products,
    _fold_decisions,
    _fold_kpis,
    _fold_notebooks,
    _fold_sources,
    _is_execute_with_tool,
)
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger, Ledger

logger = logging.getLogger("wormbase_core.mcp_tools.resources")

LedgerLike = Ledger | InMemoryLedger | Any

RESOURCE_URIS = (
    "wormbase://ledger/{company_id}/recent",
    "wormbase://kpis/{company_id}/tree",
    "wormbase://decisions/{company_id}/{decision_id}",
    "wormbase://data-products/{company_id}/{data_product_id}",
    "wormbase://notebooks/{company_id}/{notebook_id}",
    "wormbase://sources/{company_id}/{source_id}",
    "wormbase://conversations/{company_id}/channels/{channel_id}",
)


async def _ledger_rows(ledger: LedgerLike, company_slug: str) -> list[dict[str, Any]]:
    """Resolve slug → UUID → fetch."""
    company_id = tenant_to_uuid(company_slug)
    return await ledger.fetch(company_id)


async def _audit_resource_read(
    ledger: LedgerLike,
    *,
    company_slug: str,
    uri: str,
    started_at: datetime,
    t0: float,
) -> None:
    """Best-effort low-shape audit entry for a resource read."""
    try:
        company_id = tenant_to_uuid(company_slug)
    except Exception:  # noqa: BLE001
        return
    elapsed = int((time.perf_counter() - t0) * 1000)
    args_hash = canonical_args_hash({"uri": uri})
    await audit(
        ledger,
        company_id=company_id,
        caller_person_id=None,
        tool_name=f"resource:{uri.split('://', 1)[-1].split('/', 2)[0]}",
        args_hash=args_hash,
        client_ua=None,
        started_at=started_at,
        outcome="ok",
        latency_ms=elapsed,
    )


def register_resources(
    mcp: FastMCP,
    *,
    ledger: LedgerLike,
    api_token: str,  # noqa: ARG001 (parity with read/write registers)
) -> None:
    """Register all 7 URI-addressable resources."""

    @mcp.resource(
        "wormbase://ledger/{company_id}/recent",
        mime_type="application/json",
        description="Most recent 50 ledger entries (PEVR rows) for the tenant.",
    )
    async def ledger_recent(company_id: str) -> str:
        started_at = datetime.now(tz=UTC)
        t0 = time.perf_counter()
        rows = await _ledger_rows(ledger, company_id)
        recent = sorted(rows, key=lambda r: r["seq"], reverse=True)[:50]
        out = [
            {
                "seq": int(r["seq"]),
                "ts": r["ts"].isoformat() if hasattr(r["ts"], "isoformat") else str(r["ts"]),
                "kind": r["kind"],
                "tool": (r.get("payload") or {}).get("tool"),
            }
            for r in recent
        ]
        await _audit_resource_read(
            ledger, company_slug=company_id,
            uri=f"wormbase://ledger/{company_id}/recent",
            started_at=started_at, t0=t0,
        )
        return json.dumps(out)

    @mcp.resource(
        "wormbase://kpis/{company_id}/tree",
        mime_type="application/json",
        description="The full KPI tree current state for the tenant.",
    )
    async def kpis_tree(company_id: str) -> str:
        started_at = datetime.now(tz=UTC)
        t0 = time.perf_counter()
        rows = await _ledger_rows(ledger, company_id)
        tree = _fold_kpis(rows, domain=None)
        await _audit_resource_read(
            ledger, company_slug=company_id,
            uri=f"wormbase://kpis/{company_id}/tree",
            started_at=started_at, t0=t0,
        )
        return json.dumps(tree)

    @mcp.resource(
        "wormbase://decisions/{company_id}/{decision_id}",
        mime_type="application/json",
        description="Single decision detail with full provenance.",
    )
    async def decision_detail(company_id: str, decision_id: str) -> str:
        started_at = datetime.now(tz=UTC)
        t0 = time.perf_counter()
        rows = await _ledger_rows(ledger, company_id)
        decisions = _fold_decisions(rows, since=None, domain=None)
        match = next(
            (d for d in decisions if d.get("decision_id") == decision_id),
            None,
        )
        await _audit_resource_read(
            ledger, company_slug=company_id,
            uri=f"wormbase://decisions/{company_id}/{decision_id}",
            started_at=started_at, t0=t0,
        )
        return json.dumps(match or {"error": "not_found", "decision_id": decision_id})

    @mcp.resource(
        "wormbase://data-products/{company_id}/{data_product_id}",
        mime_type="application/json",
        description="Data product metadata + content reference.",
    )
    async def data_product_detail(company_id: str, data_product_id: str) -> str:
        started_at = datetime.now(tz=UTC)
        t0 = time.perf_counter()
        rows = await _ledger_rows(ledger, company_id)
        products = _fold_data_products(rows, kind=None, requested_by=None)
        match = next(
            (p for p in products if p.get("data_product_id") == data_product_id),
            None,
        )
        await _audit_resource_read(
            ledger, company_slug=company_id,
            uri=f"wormbase://data-products/{company_id}/{data_product_id}",
            started_at=started_at, t0=t0,
        )
        return json.dumps(
            match or {"error": "not_found", "data_product_id": data_product_id}
        )

    @mcp.resource(
        "wormbase://notebooks/{company_id}/{notebook_id}",
        mime_type="application/json",
        description="Notebook metadata + most recent run summary.",
    )
    async def notebook_detail(company_id: str, notebook_id: str) -> str:
        started_at = datetime.now(tz=UTC)
        t0 = time.perf_counter()
        rows = await _ledger_rows(ledger, company_id)
        notebooks = _fold_notebooks(rows, owner_person_id=None)
        match = next(
            (n for n in notebooks if n.get("notebook_id") == notebook_id),
            None,
        )
        # Attach run history (light): all execute notebook_run entries.
        history: list[dict[str, Any]] = []
        for entry in rows:
            if not _is_execute_with_tool(entry, "emit_notebook_run"):
                continue
            args = (entry.get("payload") or {}).get("args") or {}
            if args.get("notebook_id") == notebook_id:
                history.append(
                    {
                        "run_id": args.get("run_id"),
                        "status": args.get("status"),
                        "duration_ms": args.get("duration_ms"),
                        "ts": (
                            entry["ts"].isoformat()
                            if hasattr(entry["ts"], "isoformat")
                            else str(entry["ts"])
                        ),
                    }
                )
        result: dict[str, Any] = match or {
            "error": "not_found", "notebook_id": notebook_id,
        }
        if match:
            result = {**match, "runs": history}
        await _audit_resource_read(
            ledger, company_slug=company_id,
            uri=f"wormbase://notebooks/{company_id}/{notebook_id}",
            started_at=started_at, t0=t0,
        )
        return json.dumps(result)

    @mcp.resource(
        "wormbase://sources/{company_id}/{source_id}",
        mime_type="application/json",
        description="Source metadata + cascade state.",
    )
    async def source_detail(company_id: str, source_id: str) -> str:
        started_at = datetime.now(tz=UTC)
        t0 = time.perf_counter()
        rows = await _ledger_rows(ledger, company_id)
        sources = _fold_sources(rows, kind=None, status=None)
        match = next(
            (s for s in sources if s.get("source_id") == source_id),
            None,
        )
        await _audit_resource_read(
            ledger, company_slug=company_id,
            uri=f"wormbase://sources/{company_id}/{source_id}",
            started_at=started_at, t0=t0,
        )
        return json.dumps(match or {"error": "not_found", "source_id": source_id})

    @mcp.resource(
        "wormbase://conversations/{company_id}/channels/{channel_id}",
        mime_type="application/json",
        description="Most recent 50 messages in a channel.",
    )
    async def channel_recent(company_id: str, channel_id: str) -> str:
        started_at = datetime.now(tz=UTC)
        t0 = time.perf_counter()
        rows = await _ledger_rows(ledger, company_id)
        msgs = _fold_conversations(
            rows, channel_id=channel_id, since=None, limit=50,
        )
        await _audit_resource_read(
            ledger, company_slug=company_id,
            uri=f"wormbase://conversations/{company_id}/channels/{channel_id}",
            started_at=started_at, t0=t0,
        )
        return json.dumps(msgs)


__all__ = [
    "RESOURCE_URIS",
    "register_resources",
]
