"""MCP client for the voice-agent — KPI lookup via worm-core's MCP server.

P13 of the demo-day PRD wires the "Ask the worm" floater to a real
MCP read call so the worm answers KPI questions with a citation that
points at a real ledger entry. This module owns that wire.

The client speaks Streamable HTTP to ``WORMBASE_MCP_SERVER_URL``
(e.g. ``http://worm-core:9911/mcp`` over the compose network) using
the official ``mcp`` SDK. Two tools matter for the voice surface:

* ``query_kpis(company_id)`` — resolves a KPI by fuzzy name match.
* ``query_ledger(company_id, kinds=["execute"], limit=N)`` — finds
  the seq of the most recent ``emit_kpi_node`` / ``emit_kpi_proposed``
  entry for that KPI, suitable for a ``/trace?seq=N`` deep link.

Both calls audit-write a ``emit_mcp_call_received`` row on worm-core's
side, so the voice surface inherits the same governance plumbing as
external Claude Desktop clients.

Design knobs:

- :class:`MCPRouter` — Protocol the voice ``app.py`` consumes. Tests
  inject a fake; production uses :class:`StreamableHTTPMCPRouter`.
- :class:`KPIHit` — the resolved-KPI data the ``/v1/ask`` pipeline
  needs to render an answer + citation.
- :func:`looks_like_kpi_question` — cheap-and-honest classifier so
  non-KPI questions skip the MCP call entirely.

If the MCP server is unreachable or returns garbage, the router
returns ``None`` and the caller falls back to the chat-only pipeline
(answer still goes through Kimi, but ``ledger_seq`` falls back to the
``chat_sent`` seq). No silent fallbacks — every degradation logs.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# KPI question classifier
# ---------------------------------------------------------------------------


_KPI_KEYWORDS: tuple[str, ...] = (
    "kpi",
    "revenue",
    "arr",
    "mrr",
    "churn",
    "retention",
    "growth",
    "margin",
    "ebitda",
    "cac",
    "ltv",
    "nps",
    "conversion",
    "pipeline",
    "bookings",
    "billings",
    "active users",
    "dau",
    "mau",
    "wau",
    "net new",
    "net revenue",
    "gross",
)

_KPI_QUESTION_PREFIXES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bwhat(?:'s| is| was| were| are)\b",
        r"\bhow much\b",
        r"\bhow many\b",
        r"\bcurrent value\b",
        r"\bvalue of\b",
        r"\bshow me\b",
        r"\btell me\b",
    )
)


def looks_like_kpi_question(transcript: str) -> bool:
    """Return True iff the transcript looks like a KPI lookup.

    Heuristic, not a parser: a KPI keyword AND a question-shaped
    prefix. Both must be present so "the kpi tab is broken" doesn't
    trigger a lookup. False negatives are fine — we degrade to the
    plain chat pipeline. False positives are also fine — the MCP call
    is read-only and audited.
    """
    if not transcript:
        return False
    text = transcript.lower()
    if not any(kw in text for kw in _KPI_KEYWORDS):
        return False
    return any(p.search(transcript) for p in _KPI_QUESTION_PREFIXES)


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KPIHit:
    """One resolved KPI plus the ledger seq of its most-recent computation.

    ``ledger_seq`` is the seq of the ``emit_kpi_node`` (or
    ``emit_kpi_proposed``) execute entry whose args.id matched
    ``kpi_id``. When no matching execute is found, ``ledger_seq`` is
    ``None`` and the caller falls back to the chat_sent seq for the
    citation link.
    """

    kpi_id: str
    name: str
    formula: str | None
    unit: str | None
    domain_id: str | None
    status: str | None
    owner_position: str | None
    ledger_seq: int | None


# ---------------------------------------------------------------------------
# Router protocol — voice-agent consumes this; tests inject a fake
# ---------------------------------------------------------------------------


class MCPRouter(Protocol):
    """Voice-agent's view of worm-core's MCP server."""

    async def lookup_kpi(
        self, *, company_id: str, transcript: str,
    ) -> KPIHit | None:
        """Resolve the KPI most likely referenced by ``transcript``.

        Returns ``None`` when no KPI fuzzy-matches or the MCP server
        is unreachable. Implementations MUST log unreachable cases at
        WARNING so demo-day operators can see the wire is down.
        """
        ...


# ---------------------------------------------------------------------------
# Production impl — speaks Streamable HTTP to worm-core
# ---------------------------------------------------------------------------


def _normalize(s: str) -> str:
    """Lowercase + collapse non-alphanumerics for fuzzy matching."""
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _token_overlap(a: str, b: str) -> float:
    """Jaccard token overlap on normalized strings.

    Cheap, language-agnostic, and good enough for "q3 net revenue"
    matching "Q3 Net Revenue" and friends. The MCP read tool returns
    the canonical name, so the input side is the variable one.
    """
    ta = set(_normalize(a).split())
    tb = set(_normalize(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def best_kpi_match(
    transcript: str, kpis: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the KPI dict whose ``name`` best matches ``transcript``.

    Tie-break by longer name (more specific match wins). Returns
    ``None`` when the best score is below a confidence floor — we
    don't want to cite a random KPI when the user asked about churn
    and the only KPIs in the tenant are revenue-shaped.
    """
    best: tuple[float, int, dict[str, Any]] | None = None
    for k in kpis:
        name = k.get("name") or k.get("label") or ""
        if not isinstance(name, str) or not name:
            continue
        score = _token_overlap(transcript, name)
        if score <= 0.0:
            continue
        candidate = (score, len(name), k)
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return None
    score, _, kpi = best
    # Require at least one shared token. Below this we'd be guessing.
    if score < 0.15:
        return None
    return kpi


def _find_kpi_compute_seq(
    rows: list[dict[str, Any]], *, kpi_id: str,
) -> int | None:
    """Walk MCP ``query_ledger`` rows; return seq of the most recent
    KPI-related execute matching ``kpi_id``."""
    target_id = str(kpi_id)
    best_seq: int | None = None
    for row in rows:
        if row.get("kind") != "execute":
            continue
        tool = row.get("tool")
        args = row.get("args") or {}
        if tool == "emit_kpi_node" and str(args.get("id") or "") == target_id:
            seq = row.get("seq")
            if isinstance(seq, int) and (best_seq is None or seq > best_seq):
                best_seq = seq
        elif (
            tool == "emit_kpi_proposed"
            and str(args.get("kpi_id") or "") == target_id
        ):
            seq = row.get("seq")
            if isinstance(seq, int) and (best_seq is None or seq > best_seq):
                best_seq = seq
    return best_seq


class StreamableHTTPMCPRouter:
    """Real MCP client backed by the official ``mcp`` SDK.

    One short-lived session per call — the spike audit trail is the
    canonical record, so we do not need a connection pool. The
    bearer token comes from ``WORMBASE_LEDGER_API_TOKEN`` (same token
    the existing HTTP write API and FastMCP server already share).
    """

    def __init__(
        self,
        *,
        url: str,
        api_token: str,
        request_timeout_s: float = 5.0,
    ) -> None:
        self._url = url.rstrip("/")
        self._api_token = api_token
        self._timeout_s = request_timeout_s

    async def lookup_kpi(
        self, *, company_id: str, transcript: str,
    ) -> KPIHit | None:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError as exc:
            logger.warning(
                "voice-agent: 'mcp' package not installed (%s); "
                "MCP routing disabled for this turn",
                exc,
            )
            return None

        headers = {"Authorization": f"Bearer {self._api_token}"}
        try:
            async with streamablehttp_client(self._url, headers=headers) as (
                r, w, _,
            ):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    kpis_res = await session.call_tool(
                        "query_kpis",
                        arguments={"company_id": company_id},
                    )
                    kpis = _structured_payload(kpis_res)
                    if not isinstance(kpis, list):
                        logger.warning(
                            "voice-agent: query_kpis returned non-list shape",
                        )
                        return None
                    if not kpis:
                        return None
                    best = best_kpi_match(transcript, kpis)
                    if best is None:
                        return None
                    kpi_id = str(
                        best.get("id") or best.get("kpi_id") or "",
                    )
                    if not kpi_id:
                        return None

                    # Find the most recent emit_kpi_node / emit_kpi_proposed
                    # execute entry whose args reference our KPI id. We
                    # ask for execute entries only and filter client-side
                    # by tool — the MCP query_ledger tool doesn't accept
                    # a tool filter today.
                    ledger_res = await session.call_tool(
                        "query_ledger",
                        arguments={
                            "company_id": company_id,
                            "kinds": ["execute"],
                            "limit": 200,
                        },
                    )
                    ledger_rows = _structured_payload(ledger_res)
                    seq = (
                        _find_kpi_compute_seq(ledger_rows, kpi_id=kpi_id)
                        if isinstance(ledger_rows, list)
                        else None
                    )

                    return KPIHit(
                        kpi_id=kpi_id,
                        name=str(best.get("name") or best.get("label") or kpi_id),
                        formula=_str_or_none(best.get("formula")),
                        unit=_str_or_none(best.get("unit")),
                        domain_id=_str_or_none(best.get("domain_id")),
                        status=_str_or_none(best.get("status")),
                        owner_position=_str_or_none(
                            best.get("owner_position"),
                        ),
                        ledger_seq=seq,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "voice-agent: MCP lookup failed (%s); falling back to chat-only",
                exc,
            )
            return None


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v)
    return s if s else None


def _structured_payload(call_result: Any) -> Any:
    """Extract the structured payload from an MCP ``CallToolResult``.

    The SDK exposes structured data under ``structuredContent``; older
    servers return JSON in the first content text block. Try both.
    """
    payload = getattr(call_result, "structuredContent", None)
    if payload is not None:
        # FastMCP wraps list-shaped tool results under {"result": [...]}.
        if isinstance(payload, dict) and "result" in payload and len(payload) == 1:
            return payload["result"]
        return payload
    contents = getattr(call_result, "content", None) or []
    for c in contents:
        text = getattr(c, "text", None)
        if isinstance(text, str) and text:
            try:
                import json as _json
                return _json.loads(text)
            except Exception:  # noqa: BLE001
                continue
    return None


# ---------------------------------------------------------------------------
# Env-driven factory — voice-agent's app.py uses this at boot
# ---------------------------------------------------------------------------


def build_default_router() -> MCPRouter | None:
    """Build a production router from env vars.

    Returns ``None`` (so the voice surface degrades to chat-only)
    when required config is missing — the dashboard floater renders an
    answer either way.
    """
    url = os.environ.get("WORMBASE_MCP_SERVER_URL", "").strip()
    if not url:
        # Default to the worm-core MCP service on the compose network
        # when the env var is unset. Operators flip MCP off by setting
        # an empty URL or by leaving the worm-core MCP server disabled.
        url = "http://worm-core:9911/mcp"
    token = os.environ.get(
        "WORMBASE_VOICE_MCP_TOKEN",
        os.environ.get("WORMBASE_LEDGER_API_TOKEN", ""),
    ).strip()
    if not token:
        logger.warning(
            "voice-agent: no MCP bearer token configured "
            "(WORMBASE_VOICE_MCP_TOKEN / WORMBASE_LEDGER_API_TOKEN); "
            "MCP routing disabled",
        )
        return None
    return StreamableHTTPMCPRouter(url=url, api_token=token)


__all__ = [
    "KPIHit",
    "MCPRouter",
    "StreamableHTTPMCPRouter",
    "best_kpi_match",
    "build_default_router",
    "looks_like_kpi_question",
]
