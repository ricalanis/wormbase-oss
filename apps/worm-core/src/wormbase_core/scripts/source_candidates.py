"""wormbase-source-candidates — operator CLI for L1 source-candidate triage.

Silent-mode operator surface: the agent emits candidates to the ledger;
the operator (Ricardo) lists / promotes / rejects via this CLI.

Usage
-----
::

    $ uv run wormbase-source-candidates list --tenant altis
    candidate_id        confidence  kind       identifier    strategy         status   evidence
    c8f3a2b1e4d5...     0.75        notion     notion-altis  channel_mention  PENDING  [seq 4823] "…Poncho dijo…"
    ...
    3 pending, 2 promoted, 1 rejected

    $ uv run wormbase-source-candidates promote c8f3a2b1... --tenant altis
    candidate: notion (channel_mention, confidence 0.75)
    evidence: [seq 4823] "…Poncho dijo…"
    proceed? [y/N] y
    promoted: candidate_id=c8f3a2b1... -> source_candidate_promoted at seq 4901

    $ uv run wormbase-source-candidates reject c8f3a2b1... --tenant altis --reason duplicate
    candidate: notion (channel_mention, confidence 0.75)
    proceed? [y/N] y
    rejected: candidate_id=c8f3a2b1... reason=duplicate seq=4901

Subcommands
-----------
list        List source candidates for a tenant with optional filters.
promote     Promote a pending candidate to approved.
reject      Reject a pending candidate with a categorical reason.

Flags (common)
--------------
--tenant <slug>   (required) — resolves slug → company_id via uuid5
--dsn <url>       (optional) — falls back to WORMBASE_LEDGER_DSN env var

Tenant slug → UUID
------------------
Mirrors ``apps/voice-agent/src/wormbase_voice_agent/app.py``
and the other scripts in this directory:

    namespace = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")
    company_id = uuid5(namespace, slug.strip().lower())
"""
from __future__ import annotations

import argparse
import asyncio
import builtins
import json
import os
import sys
from typing import Any, get_args
from uuid import UUID, uuid5

# ---------------------------------------------------------------------------
# Tenant resolution — mirrors ledger_recent.py, ingest_transcript.py, etc.
# ---------------------------------------------------------------------------

WORMBASE_TENANT_NAMESPACE: str = "6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f"
"""String form of the tenant namespace UUID.

Cross-reference: ``apps/voice-agent/src/wormbase_voice_agent/app.py``
uses the identical constant.
"""


def _tenant_to_company_uuid(slug: str) -> UUID:
    """Convert a tenant slug to a deterministic company UUID.

    Mirrors ``ledger_recent._tenant_to_company_uuid`` exactly.
    """
    if not slug or not slug.strip():
        raise ValueError("tenant slug must be non-empty")
    return uuid5(UUID(WORMBASE_TENANT_NAMESPACE), slug.strip().lower())


# ---------------------------------------------------------------------------
# Valid reject reasons — derived from the Literal at import time so the
# CLI stays in sync with the schema without hardcoding values.
# ---------------------------------------------------------------------------

def _valid_reject_reasons() -> tuple[str, ...]:
    """Return valid SourceCandidateRejectReason values from the Literal.

    Lazy import so tests that inject InMemoryLedger do not need DB deps.
    """
    from wormbase_ledger.entries import SourceCandidateRejectReason  # noqa: PLC0415
    return get_args(SourceCandidateRejectReason)


# ---------------------------------------------------------------------------
# Ledger fold — derive current status of each candidate
# ---------------------------------------------------------------------------

# Tool names written by the write_actions helpers.
_TOOL_PROPOSED = "emit_source_candidate_proposed"
_TOOL_PROMOTED = "emit_source_candidate_promoted"
_TOOL_REJECTED = "emit_source_candidate_rejected"

_STATUS_PENDING = "PENDING"
_STATUS_PROMOTED = "PROMOTED"
_STATUS_REJECTED = "REJECTED"

# Mapping from tool name to the status it establishes.
_TOOL_TO_STATUS: dict[str, str] = {
    _TOOL_PROPOSED: _STATUS_PENDING,
    _TOOL_PROMOTED: _STATUS_PROMOTED,
    _TOOL_REJECTED: _STATUS_REJECTED,
}


def _fold_candidates(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fold the ledger rows into a candidate_id → candidate dict.

    Only execute rows whose payload.tool is one of the three
    source_candidate tools are considered. Last write wins for the
    status field (forward-only semantics).

    Returns a dict keyed by candidate_id with the following structure::

        {
            "candidate_id": str,
            "proposed_kind": str,          # from latest proposed entry
            "proposed_identifier": str,
            "strategy": str,
            "confidence": float,
            "reasoning": str,
            "evidence": dict,
            "status": str,                 # PENDING | PROMOTED | REJECTED
            "seq": int,                    # seq of the status-setting entry
            "reject_reason": str | None,   # set when status=REJECTED
        }

    The proposed fields are taken from the most-recent
    ``source_candidate_proposed`` execute row for the candidate_id (in
    case re-emission updated evidence/confidence). Status and seq come
    from the most-recent terminal entry (promoted or rejected), or from
    the proposed entry when no terminal entry exists yet.
    """
    # candidate_id → accumulated data dict.
    candidates: dict[str, dict[str, Any]] = {}

    for row in rows:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        tool = payload.get("tool")
        if tool not in _TOOL_TO_STATUS:
            continue
        args = payload.get("args") or {}
        if not isinstance(args, dict):
            continue
        candidate_id = str(args.get("candidate_id") or "")
        if not candidate_id:
            continue

        seq = row.get("seq", 0)
        status = _TOOL_TO_STATUS[tool]

        if candidate_id not in candidates:
            candidates[candidate_id] = {
                "candidate_id": candidate_id,
                "proposed_kind": "",
                "proposed_identifier": "",
                "strategy": "",
                "confidence": 0.0,
                "reasoning": "",
                "evidence": {},
                "status": _STATUS_PENDING,
                "seq": seq,
                "reject_reason": None,
            }

        entry = candidates[candidate_id]

        if tool == _TOOL_PROPOSED:
            # Update the proposed fields with the latest proposed entry.
            entry["proposed_kind"] = str(args.get("proposed_kind") or "")
            entry["proposed_identifier"] = str(args.get("proposed_identifier") or "")
            entry["strategy"] = str(args.get("strategy") or "")
            entry["confidence"] = float(args.get("confidence") or 0.0)
            entry["reasoning"] = str(args.get("reasoning") or "")
            entry["evidence"] = args.get("evidence") or {}
            # Only set status/seq for proposed if no terminal entry yet.
            if entry["status"] == _STATUS_PENDING:
                entry["seq"] = seq
        elif tool == _TOOL_PROMOTED:
            # Terminal — last write wins.
            entry["status"] = _STATUS_PROMOTED
            entry["seq"] = seq
            entry["reject_reason"] = None
        elif tool == _TOOL_REJECTED:
            # Terminal — last write wins.
            entry["status"] = _STATUS_REJECTED
            entry["seq"] = seq
            entry["reject_reason"] = str(args.get("reason") or "")

    return candidates


# ---------------------------------------------------------------------------
# Evidence formatting
# ---------------------------------------------------------------------------

def _format_evidence(evidence: dict[str, Any], seq: int) -> str:
    """Render the evidence dict as a compact single-line string."""
    msg_refs = evidence.get("message_refs") or []
    excerpt = evidence.get("matched_text_excerpt") or ""
    if excerpt:
        excerpt_short = (excerpt[:60] + "…") if len(excerpt) > 60 else excerpt
        return f'[seq {seq}] "{excerpt_short}"'
    if msg_refs:
        refs_str = ", ".join(str(r) for r in msg_refs[:3])
        suffix = "…" if len(msg_refs) > 3 else ""
        return f"[seq {seq}] refs={refs_str}{suffix}"
    return f"[seq {seq}]"


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------

_COL_CANDIDATE_ID = 36
_COL_CONFIDENCE = 12
_COL_KIND = 16
_COL_IDENTIFIER = 16
_COL_STRATEGY = 17
_COL_STATUS = 9
# evidence: rest of line


def _cell(text: str, width: int) -> str:
    """Left-justify ``text`` in a cell of ``width`` chars, truncating if needed."""
    s = str(text)
    if len(s) > width:
        s = s[: width - 1] + "…"
    return s.ljust(width)


def _format_table(candidates: list[dict[str, Any]]) -> str:
    """Render a list of candidate dicts as a fixed-width table."""
    header = (
        _cell("candidate_id", _COL_CANDIDATE_ID)
        + _cell("confidence", _COL_CONFIDENCE)
        + _cell("kind", _COL_KIND)
        + _cell("identifier", _COL_IDENTIFIER)
        + _cell("strategy", _COL_STRATEGY)
        + _cell("status", _COL_STATUS)
        + "evidence"
    )
    lines = [header]
    for c in candidates:
        evidence_str = _format_evidence(c.get("evidence") or {}, c.get("seq", 0))
        confidence_str = f"{c.get('confidence', 0.0):.2f}"
        lines.append(
            _cell(c["candidate_id"], _COL_CANDIDATE_ID)
            + _cell(confidence_str, _COL_CONFIDENCE)
            + _cell(c.get("proposed_kind", ""), _COL_KIND)
            + _cell(c.get("proposed_identifier", ""), _COL_IDENTIFIER)
            + _cell(c.get("strategy", ""), _COL_STRATEGY)
            + _cell(c.get("status", ""), _COL_STATUS)
            + evidence_str
        )
    return "\n".join(lines)


def _format_jsonl(candidates: list[dict[str, Any]]) -> str:
    """Render a list of candidate dicts as JSONL (one JSON object per line)."""
    lines = []
    for c in candidates:
        lines.append(json.dumps(c, default=str))
    return "\n".join(lines)


def _summary_line(candidates: list[dict[str, Any]]) -> str:
    """Return the N pending, N promoted, N rejected summary string."""
    pending = sum(1 for c in candidates if c.get("status") == _STATUS_PENDING)
    promoted = sum(1 for c in candidates if c.get("status") == _STATUS_PROMOTED)
    rejected = sum(1 for c in candidates if c.get("status") == _STATUS_REJECTED)
    return f"{pending} pending, {promoted} promoted, {rejected} rejected"


# ---------------------------------------------------------------------------
# Subcommand: list
# ---------------------------------------------------------------------------


async def _do_list(
    ledger: Any,
    company_id: UUID,
    *,
    status_filter: str,
    strategy_filter: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """Fetch + fold the ledger and display matching candidates."""
    rows = await ledger.fetch(company_id)
    candidates_map = _fold_candidates(rows)
    all_candidates = list(candidates_map.values())

    # Sort newest-first by seq.
    all_candidates.sort(key=lambda c: c.get("seq", 0), reverse=True)

    # Status filter.
    if status_filter != "all":
        status_val = status_filter.upper()
        filtered = [c for c in all_candidates if c.get("status") == status_val]
    else:
        filtered = all_candidates

    # Strategy filter.
    if strategy_filter:
        filtered = [c for c in filtered if c.get("strategy") == strategy_filter]

    # Limit.
    filtered = filtered[:limit]

    # Summary (over all candidates, not filtered).
    summary = _summary_line(all_candidates)

    if as_json:
        output = _format_jsonl(filtered)
        if output:
            print(output)
    else:
        output = _format_table(filtered)
        print(output)

    print(summary)


def _cmd_list(args: argparse.Namespace, ledger: Any) -> None:
    """Handle the ``list`` subcommand."""
    try:
        company_id = _tenant_to_company_uuid(args.tenant)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(
        _do_list(
            ledger,
            company_id,
            status_filter=args.status,
            strategy_filter=args.strategy,
            limit=args.limit,
            as_json=args.as_json,
        )
    )


# ---------------------------------------------------------------------------
# Subcommand: promote
# ---------------------------------------------------------------------------


async def _do_promote(
    ledger: Any,
    company_id: UUID,
    *,
    candidate_id: str,
    yes: bool,
    via: str,
) -> None:
    """Load, confirm, and write the promote entry."""
    rows = await ledger.fetch(company_id)
    candidates_map = _fold_candidates(rows)

    if candidate_id not in candidates_map:
        print(
            f"ERROR: candidate {candidate_id!r} not found for this tenant. "
            "No source_candidate_proposed entry exists.",
            file=sys.stderr,
        )
        sys.exit(1)

    candidate = candidates_map[candidate_id]
    current_status = candidate["status"]

    if current_status == _STATUS_PROMOTED:
        print(
            f"ERROR: candidate {candidate_id!r} is already promoted (at seq {candidate['seq']}); "
            "cannot promote again.",
            file=sys.stderr,
        )
        sys.exit(1)

    if current_status == _STATUS_REJECTED:
        print(
            f"ERROR: candidate {candidate_id!r} is already rejected (at seq {candidate['seq']}); "
            "promote rejected candidates by re-proposing, not re-promoting.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Display candidate info.
    print(
        f"candidate: {candidate['proposed_kind']} "
        f"({candidate['strategy']}, confidence {candidate['confidence']:.2f})"
    )
    evidence_str = _format_evidence(candidate.get("evidence") or {}, candidate.get("seq", 0))
    print(f"evidence: {evidence_str}")

    if not yes:
        try:
            answer = builtins.input("proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer != "y":
            print("aborted.")
            return

    # Call the write_action.
    from wormbase_core.write_actions import promote_source_candidate  # noqa: PLC0415

    result = await promote_source_candidate(
        ledger,
        company_id,
        candidate_id=candidate_id,
        promoted_by_person_id=via,
    )

    # Report the new seq(s).
    # The PEVR result carries 4 entry_ids; the execute row (index 1) is the
    # canonical audit entry. We fetch the updated ledger to find the seq.
    rows_after = await ledger.fetch(company_id)
    promoted_seq: int | None = None
    for row in reversed(rows_after):
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        if payload.get("tool") != _TOOL_PROMOTED:
            continue
        args = payload.get("args") or {}
        if str(args.get("candidate_id") or "") == candidate_id:
            promoted_seq = row.get("seq")
            break

    seq_str = str(promoted_seq) if promoted_seq is not None else "?"
    print(
        f"promoted: candidate_id={candidate_id} "
        f"-> source_candidate_promoted at seq {seq_str}"
    )

    # Report downstream source_proposed if present.
    # (In CLI context, downstream_source_proposed_id is not wired because
    # the SourceBuilder dual-write is owned by the HTTP handler. The promote
    # write_action still records the L1 audit entry correctly.)
    _ = result  # WriteResult consumed; seq surfaced via ledger scan above.


def _cmd_promote(args: argparse.Namespace, ledger: Any) -> None:
    """Handle the ``promote`` subcommand."""
    try:
        company_id = _tenant_to_company_uuid(args.tenant)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(
        _do_promote(
            ledger,
            company_id,
            candidate_id=args.candidate_id,
            yes=args.yes,
            via=args.via,
        )
    )


# ---------------------------------------------------------------------------
# Subcommand: reject
# ---------------------------------------------------------------------------


async def _do_reject(
    ledger: Any,
    company_id: UUID,
    *,
    candidate_id: str,
    reason: str,
    note: str | None,
    yes: bool,
    via: str,
) -> None:
    """Load, confirm, and write the reject entry."""
    rows = await ledger.fetch(company_id)
    candidates_map = _fold_candidates(rows)

    if candidate_id not in candidates_map:
        print(
            f"ERROR: candidate {candidate_id!r} not found for this tenant. "
            "No source_candidate_proposed entry exists.",
            file=sys.stderr,
        )
        sys.exit(1)

    candidate = candidates_map[candidate_id]
    current_status = candidate["status"]

    if current_status == _STATUS_REJECTED:
        print(
            f"ERROR: candidate {candidate_id!r} is already rejected (at seq {candidate['seq']}, "
            f"reason={candidate.get('reject_reason')!r}); cannot reject again.",
            file=sys.stderr,
        )
        sys.exit(1)

    if current_status == _STATUS_PROMOTED:
        print(
            f"ERROR: candidate {candidate_id!r} is already promoted (at seq {candidate['seq']}); "
            "cannot reject a promoted candidate.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Display candidate info.
    print(
        f"candidate: {candidate['proposed_kind']} "
        f"({candidate['strategy']}, confidence {candidate['confidence']:.2f})"
    )

    if not yes:
        try:
            answer = builtins.input("proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer != "y":
            print("aborted.")
            return

    # Call the write_action.
    from wormbase_core.write_actions import reject_source_candidate  # noqa: PLC0415

    await reject_source_candidate(
        ledger,
        company_id,
        candidate_id=candidate_id,
        rejected_by_person_id=via,
        reason=reason,
        notes=note,
    )

    # Report the new seq.
    rows_after = await ledger.fetch(company_id)
    rejected_seq: int | None = None
    for row in reversed(rows_after):
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        if payload.get("tool") != _TOOL_REJECTED:
            continue
        args = payload.get("args") or {}
        if str(args.get("candidate_id") or "") == candidate_id:
            rejected_seq = row.get("seq")
            break

    seq_str = str(rejected_seq) if rejected_seq is not None else "?"
    print(
        f"rejected: candidate_id={candidate_id} reason={reason} seq={seq_str}"
    )


def _cmd_reject(args: argparse.Namespace, ledger: Any) -> None:
    """Handle the ``reject`` subcommand."""
    try:
        company_id = _tenant_to_company_uuid(args.tenant)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # Validate reason against the Literal.
    valid_reasons = _valid_reject_reasons()
    if args.reason not in valid_reasons:
        valid_str = ", ".join(valid_reasons)
        print(
            f"ERROR: invalid --reason {args.reason!r}. "
            f"Valid reasons: {valid_str}",
            file=sys.stderr,
        )
        sys.exit(1)

    asyncio.run(
        _do_reject(
            ledger,
            company_id,
            candidate_id=args.candidate_id,
            reason=args.reason,
            note=args.note,
            yes=args.yes,
            via=args.via,
        )
    )


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    *,
    ledger: Any = None,
) -> None:
    """Entry point for ``wormbase-source-candidates``.

    Args:
        argv:   Argument list (defaults to ``sys.argv[1:]`` when None).
        ledger: Optional pre-constructed Ledger or InMemoryLedger. When
                supplied (typically from tests), the --dsn flag is parsed
                but ignored. When None, a ``wormbase_ledger.Ledger`` is
                constructed from ``--dsn`` or ``WORMBASE_LEDGER_DSN``.
    """
    parser = argparse.ArgumentParser(
        prog="wormbase-source-candidates",
        description=(
            "Operator CLI for L1 lake-side-compounding source-candidate triage. "
            "List, promote, or reject candidates proposed by the agent."
        ),
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # ---- list ----------------------------------------------------------------

    list_parser = subparsers.add_parser(
        "list",
        help="List source candidates for a tenant.",
    )
    list_parser.add_argument(
        "--tenant",
        required=True,
        metavar="SLUG",
        help="Tenant slug (e.g. 'altis'). Resolved to a company UUID via uuid5.",
    )
    list_parser.add_argument(
        "--status",
        default="pending",
        choices=["pending", "promoted", "rejected", "all"],
        help="Filter by status. Default: pending.",
    )
    list_parser.add_argument(
        "--strategy",
        default=None,
        metavar="STRATEGY",
        help="Filter by strategy name (e.g. channel_mention, kpi_gap, complementarity).",
    )
    list_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        metavar="N",
        help="Maximum number of candidates to display. Default: 50.",
    )
    list_parser.add_argument(
        "--dsn",
        default=None,
        metavar="URL",
        help=(
            "PostgreSQL DSN. Reads WORMBASE_LEDGER_DSN env var when not supplied. "
            "Ignored when a ledger object is injected."
        ),
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit JSONL instead of a fixed-width table.",
    )

    # ---- promote -------------------------------------------------------------

    promote_parser = subparsers.add_parser(
        "promote",
        help="Promote a pending source candidate.",
    )
    promote_parser.add_argument(
        "candidate_id",
        metavar="CANDIDATE_ID",
        help="The candidate_id to promote.",
    )
    promote_parser.add_argument(
        "--tenant",
        required=True,
        metavar="SLUG",
        help="Tenant slug.",
    )
    promote_parser.add_argument(
        "--dsn",
        default=None,
        metavar="URL",
        help="PostgreSQL DSN. Reads WORMBASE_LEDGER_DSN env var when not supplied.",
    )
    promote_parser.add_argument(
        "--yes", "-y",
        action="store_true",
        dest="yes",
        help="Skip the interactive confirmation prompt.",
    )
    promote_parser.add_argument(
        "--via",
        default="operator-cli",
        metavar="FLOW_LABEL",
        help=(
            "Label recorded as promoted_by_person_id in the ledger. "
            "Default: 'operator-cli'."
        ),
    )

    # ---- reject --------------------------------------------------------------

    reject_parser = subparsers.add_parser(
        "reject",
        help="Reject a pending source candidate.",
    )
    reject_parser.add_argument(
        "candidate_id",
        metavar="CANDIDATE_ID",
        help="The candidate_id to reject.",
    )
    reject_parser.add_argument(
        "--tenant",
        required=True,
        metavar="SLUG",
        help="Tenant slug.",
    )
    reject_parser.add_argument(
        "--reason",
        required=True,
        metavar="REASON",
        help=(
            "Categorical reject reason. "
            "Valid values: duplicate, false_positive, low_value, out_of_scope, other."
        ),
    )
    reject_parser.add_argument(
        "--note",
        default=None,
        metavar="TEXT",
        help="Optional free-text note recorded in the ledger.",
    )
    reject_parser.add_argument(
        "--dsn",
        default=None,
        metavar="URL",
        help="PostgreSQL DSN. Reads WORMBASE_LEDGER_DSN env var when not supplied.",
    )
    reject_parser.add_argument(
        "--yes", "-y",
        action="store_true",
        dest="yes",
        help="Skip the interactive confirmation prompt.",
    )
    reject_parser.add_argument(
        "--via",
        default="operator-cli",
        metavar="FLOW_LABEL",
        help=(
            "Label recorded as rejected_by_person_id in the ledger. "
            "Default: 'operator-cli'."
        ),
    )

    # --------------------------------------------------------------------------

    args = parser.parse_args(argv)

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

    try:
        if args.subcommand == "list":
            _cmd_list(args, ledger)
        elif args.subcommand == "promote":
            _cmd_promote(args, ledger)
        elif args.subcommand == "reject":
            _cmd_reject(args, ledger)
    finally:
        if _owned_ledger:
            async def _dispose() -> None:
                await ledger.dispose()
            asyncio.run(_dispose())


__all__ = [
    "WORMBASE_TENANT_NAMESPACE",
    "_tenant_to_company_uuid",
    "_valid_reject_reasons",
    "_fold_candidates",
    "_format_table",
    "_format_jsonl",
    "_summary_line",
    "main",
]
