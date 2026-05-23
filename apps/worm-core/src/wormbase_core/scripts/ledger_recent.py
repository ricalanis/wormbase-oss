"""wormbase-ledger-recent — print recent ledger rows for a given tenant.

Usage
-----
::

    $ uv run wormbase-ledger-recent --tenant altis --limit 50
    seq   ts                        kind      tool                                  summary
    4567  2026-05-25T09:01:12+00:00 propose   emit_chat_received                    whatsapp inbound from +52181... ("hello team")
    4568  2026-05-25T09:01:12+00:00 execute   channel_adapter.emit_chat_received    text="hello team" channel=120363...@g.us
    4569  2026-05-25T09:01:12+00:00 verify    -                                     passed=true
    4570  2026-05-25T09:01:12+00:00 resolve   -                                     keep
    ...

Flags
-----
--tenant <slug>   (required) — resolves slug → company_id via uuid5
--limit N         (default 50) — return the LAST N rows, oldest first
--kind <k>[,<k>]  (optional) — filter to rows matching kind or payload.target_kind
--dsn <url>       (optional) — postgres DSN; default: WORMBASE_LEDGER_DSN env var
--json            (optional) — emit JSONL instead of a table

Tenant slug → UUID
------------------
Cross-reference: ``apps/voice-agent/src/wormbase_voice_agent/app.py``
defines ``_tenant_to_company_uuid`` using the identical namespace +
``uuid5`` logic. Both must stay in sync; the namespace UUID is the
canonical constant defined in ``_WORMBASE_TENANT_NAMESPACE`` in both
files. If the voice-agent ever changes its namespace this file must
follow.

    namespace = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")
    company_id = uuid5(namespace, slug.strip().lower())

Known resolved slugs (for quick cross-check):
    altis    → 7f032a92-7036-5126-a957-8d2607126169
    baseworm → (derived from same formula)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

# ---------------------------------------------------------------------------
# Tenant resolution — mirrors apps/voice-agent/src/wormbase_voice_agent/app.py
# _WORMBASE_TENANT_NAMESPACE and _tenant_to_company_uuid MUST stay in sync.
# ---------------------------------------------------------------------------

WORMBASE_TENANT_NAMESPACE: str = "6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f"
"""String form of the tenant namespace UUID.

Cross-reference: ``apps/voice-agent/src/wormbase_voice_agent/app.py``
uses the identical constant. If voice-agent ever changes its namespace,
update both files in the same commit.
"""


def _tenant_to_company_uuid(slug: str) -> UUID:
    """Convert a tenant slug to a deterministic company UUID.

    Replicates the logic from voice-agent ``_tenant_to_company_uuid``
    to keep company_id consistent without coupling to that package.

    Cross-reference: ``apps/voice-agent/src/wormbase_voice_agent/app.py``
    """
    if not slug or not slug.strip():
        raise ValueError("tenant slug must be non-empty")
    return uuid5(UUID(WORMBASE_TENANT_NAMESPACE), slug.strip().lower())


# ---------------------------------------------------------------------------
# Summary extraction heuristics
# ---------------------------------------------------------------------------

_SUMMARY_MAX = 80


def _truncate(s: str, maxlen: int = _SUMMARY_MAX) -> str:
    if len(s) <= maxlen:
        return s
    return s[: maxlen - 1] + "…"


def _payload_summary(kind: str, payload: dict[str, Any]) -> str:
    """Produce a human-readable summary string from a ledger payload.

    Heuristic by kind / payload shape:
    - propose: use target_kind + representative fields
    - execute: render key fields
    - verify: passed=<bool>
    - resolve: decision value
    - chat_received / chat_sent: text preview
    - reply_suppressed: surface + tool
    - emit_chat_received: text + channel
    - fallback: json.dumps(payload)[:80]
    """
    if payload is None:
        return "-"

    if kind == "verify":
        passed = payload.get("passed", payload.get("passed_str", None))
        if passed is None:
            return "passed=?"
        return f"passed={str(passed).lower()}"

    if kind == "resolve":
        decision = payload.get("decision") or payload.get("resolution") or payload.get("action")
        if decision:
            return _truncate(str(decision))
        return _truncate(json.dumps(payload))

    if kind == "propose":
        target_kind = payload.get("target_kind") or payload.get("kind", "")
        if target_kind in ("chat_received", "chat_sent", "emit_chat_received"):
            text = payload.get("text", "")
            channel = payload.get("channel", "")
            caller = payload.get("caller_id", "")
            number = payload.get("phone_number", "") or caller
            snippet = _truncate(str(text), 40)
            if channel:
                return f"inbound from {number}... ({snippet!r})" if number else f"inbound ({snippet!r}) channel={channel}"
            return snippet or _truncate(json.dumps(payload))
        if target_kind == "reply_suppressed":
            surface = payload.get("surface", "")
            tool = payload.get("tool", "")
            return f"surface={surface} tool={tool}" if surface or tool else _truncate(json.dumps(payload))
        # generic propose
        tool = payload.get("tool", "")
        return _truncate(f"{target_kind} {tool}".strip() if target_kind or tool else json.dumps(payload))

    if kind == "execute":
        text = payload.get("text")
        channel = payload.get("channel", "")
        if text is not None:
            snippet = _truncate(str(text), 40)
            if channel:
                return f'text={snippet!r} channel={channel}'
            return f'text={snippet!r}'
        # Fallback: first non-meta key
        skip = {"propose_entry_id", "execute_entry_id", "verify_entry_id", "kind"}
        for k, v in payload.items():
            if k not in skip:
                return _truncate(f"{k}={v}")
        return _truncate(json.dumps(payload))

    if kind in ("chat_received", "chat_sent"):
        text = payload.get("text", "")
        return _truncate(str(text))

    if kind == "reply_suppressed":
        surface = payload.get("surface", "")
        tool = payload.get("tool", "")
        return f"surface={surface} tool={tool}"

    if kind == "emit_chat_received":
        text = payload.get("text", "")
        channel = payload.get("channel", "")
        snippet = _truncate(str(text), 40)
        return f'text={snippet!r} channel={channel}'

    return _truncate(json.dumps(payload))


def _row_tool(row: dict[str, Any]) -> str:
    """Extract a tool name from a ledger row for display."""
    payload = row.get("payload") or {}
    tool = payload.get("tool") or payload.get("target_tool") or ""
    if not tool:
        kind = row.get("kind", "")
        if kind == "verify":
            return "-"
        if kind == "resolve":
            return "-"
    return str(tool) if tool else "-"


def _row_ts(row: dict[str, Any]) -> str:
    """Format the timestamp field for display."""
    ts = row.get("ts")
    if ts is None:
        return "-"
    if isinstance(ts, datetime):
        return ts.isoformat(timespec="seconds")
    return str(ts)


# ---------------------------------------------------------------------------
# Kind filtering
# ---------------------------------------------------------------------------

_PEVR_KINDS = {"propose", "execute", "verify", "resolve"}


def _row_matches_kind_filter(row: dict[str, Any], kinds: set[str]) -> bool:
    """True if this row matches any of the requested kind filters.

    Matching rules:
    - If the row's own ``kind`` field is in ``kinds`` → match.
    - If the row is a propose row AND its ``payload.target_kind`` is in
      ``kinds`` → match (lets callers filter by logical event type).
    """
    row_kind = row.get("kind", "")
    if row_kind in kinds:
        return True
    # Check target_kind on propose rows
    if row_kind == "propose":
        payload = row.get("payload") or {}
        target_kind = payload.get("target_kind") or payload.get("kind") or ""
        if target_kind in kinds:
            return True
    return False


# ---------------------------------------------------------------------------
# Core fetch
# ---------------------------------------------------------------------------


async def fetch_rows(
    ledger: Any,
    company_id: UUID,
    *,
    limit: int,
    kinds: set[str] | None,
) -> list[dict[str, Any]]:
    """Fetch recent ledger rows for a company, applying limit and kind filter.

    Returns the LAST ``limit`` rows in chronological order (oldest first
    within the returned slice).

    Args:
        ledger:     A Ledger or InMemoryLedger instance.
        company_id: Tenant company UUID.
        limit:      Maximum number of rows to return.
        kinds:      Optional set of kind values to filter on (see
                    ``_row_matches_kind_filter``). None means no filter.
    """
    rows = await ledger.fetch(company_id)

    if kinds:
        rows = [r for r in rows if _row_matches_kind_filter(r, kinds)]

    # Return last N rows, oldest first
    return rows[-limit:] if len(rows) > limit else rows


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_COL_SEQ = 6
_COL_TS = 26
_COL_KIND = 10
_COL_TOOL = 38
_COL_SUMMARY = 80


def _cell(text: str, width: int) -> str:
    """Left-justify ``text`` in a cell of ``width`` chars, truncating if needed."""
    s = str(text)
    if len(s) > width:
        s = s[: width - 1] + "…"
    return s.ljust(width)


def format_table(rows: list[dict[str, Any]]) -> str:
    """Render ``rows`` as a fixed-width table string."""
    header = (
        _cell("seq", _COL_SEQ)
        + _cell("ts", _COL_TS)
        + _cell("kind", _COL_KIND)
        + _cell("tool", _COL_TOOL)
        + "summary"
    )
    lines = [header]
    for row in rows:
        kind = str(row.get("kind", ""))
        payload = row.get("payload") or {}
        seq = str(row.get("seq", ""))
        ts = _row_ts(row)
        tool = _row_tool(row)
        summary = _payload_summary(kind, payload)
        lines.append(
            _cell(seq, _COL_SEQ)
            + _cell(ts, _COL_TS)
            + _cell(kind, _COL_KIND)
            + _cell(tool, _COL_TOOL)
            + summary
        )
    return "\n".join(lines)


def format_jsonl(rows: list[dict[str, Any]]) -> str:
    """Render ``rows`` as JSONL (one JSON object per line)."""
    lines = []
    for row in rows:
        obj: dict[str, Any] = {
            "seq": row.get("seq"),
            "ts": _row_ts(row),
            "kind": row.get("kind"),
            "company_id": str(row.get("company_id", "")),
            "tool": _row_tool(row),
            "summary": _payload_summary(str(row.get("kind", "")), row.get("payload") or {}),
            "payload": row.get("payload"),
        }
        lines.append(json.dumps(obj, default=str))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    *,
    ledger: Any = None,
) -> None:
    """Entry point for the ``wormbase-ledger-recent`` command.

    Args:
        argv:   Argument list (defaults to ``sys.argv[1:]`` when None).
        ledger: Optional pre-constructed Ledger or InMemoryLedger. When
                supplied (typically from tests), the --dsn flag is parsed
                but ignored and no DB connection is opened. When None, a
                ``wormbase_ledger.Ledger`` is constructed from ``--dsn``
                or ``WORMBASE_LEDGER_DSN``.
    """
    parser = argparse.ArgumentParser(
        prog="wormbase-ledger-recent",
        description="Print recent ledger rows for a given tenant.",
    )
    parser.add_argument(
        "--tenant",
        required=True,
        metavar="SLUG",
        help="Tenant slug (e.g. 'altis'). Resolved to a company UUID via uuid5.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        metavar="N",
        help="Return the last N rows (oldest-first within the slice). Default: 50.",
    )
    parser.add_argument(
        "--kind",
        default=None,
        metavar="KIND[,KIND...]",
        help=(
            "Comma-separated list of kinds to include. Matches a row's own "
            "'kind' field OR (for propose rows) the payload's 'target_kind'. "
            "Example: --kind propose,execute"
        ),
    )
    parser.add_argument(
        "--dsn",
        default=None,
        metavar="URL",
        help=(
            "PostgreSQL DSN (SQLAlchemy URL). Reads WORMBASE_LEDGER_DSN env "
            "var when not supplied. Ignored when a 'ledger' object is injected."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit JSONL instead of a fixed-width table.",
    )

    args = parser.parse_args(argv)

    # --- Tenant resolution ---
    try:
        company_id = _tenant_to_company_uuid(args.tenant)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # --- Kind filter ---
    kinds: set[str] | None = None
    if args.kind:
        kinds = {k.strip() for k in args.kind.split(",") if k.strip()}

    # --- Ledger construction (skipped when injected for testing) ---
    _owned_ledger = False
    if ledger is None:
        dsn = args.dsn or os.environ.get("WORMBASE_LEDGER_DSN")
        if not dsn:
            print(
                "ERROR: no DSN configured. Supply --dsn or set WORMBASE_LEDGER_DSN.",
                file=sys.stderr,
            )
            sys.exit(1)
        # Lazy import so tests that inject a ledger don't need DB deps.
        from wormbase_ledger import Ledger  # noqa: PLC0415

        ledger = Ledger(dsn)
        _owned_ledger = True

    async def _run() -> None:
        try:
            rows = await fetch_rows(ledger, company_id, limit=args.limit, kinds=kinds)
            if args.as_json:
                output = format_jsonl(rows)
            else:
                output = format_table(rows)
            print(output)
        finally:
            if _owned_ledger:
                await ledger.dispose()

    asyncio.run(_run())


__all__ = [
    "WORMBASE_TENANT_NAMESPACE",
    "_tenant_to_company_uuid",
    "fetch_rows",
    "format_table",
    "format_jsonl",
    "main",
]
