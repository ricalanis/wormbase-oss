"""MCP audit tool — ``read_audit_trail`` (P11).

A focused complement to the existing list-style ``query_audit_trail``
tool: given a specific ``entry_id`` (the canonical asset id of any
WormBase resource — ``kpi_id``, ``data_product_id``, ``person_id``,
``decision_id``, ``process_id``, ``source_id``, ``notebook_id``,
``reactivity_id``), return the full attribution chain reconstructed
from the ledger:

    {
      "entry_id": "<the asset id>",
      "target_kind": "kpi_proposed" | "data_product_proposed" | ...,
      "proposed_by": "<actor id or marker>",
      "proposed_at": "<iso8601>",
      "confirmed_by": "<actor id>" | null,
      "confirmed_at": "<iso8601>" | null,
      "ledger_range": { "first_seq": int, "last_seq": int },
      "contributing_entries": [
        { "seq": int, "ts": "<iso8601>", "kind": "propose"|"execute"|"verify"|"resolve"|...,
          "tool": "<emit_*>" | null, "outcome": "keep"|"discard"|null }
      ]
    }

Why a separate tool?

The PRD's stage script ends with:

    "show audit trail for the KPI you just proposed"

The caller has the new asset's id in hand (returned by
``propose_kpi``); they want a single, structured chain — not a paged
list of execute entries that happen to mention the id. The chain
shape (proposed_by + confirmed_by + confirmed_at) is exactly the
attribution invariant CLAUDE.md §7 enforces; surfacing it via MCP
makes it testable from an external Claude Desktop session.

Admin-gated: the audit log carries actor identifiers and gate
outcomes, so members and unknown roles get a refusal (mirrors
``query_audit_trail`` policy).
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
    resolve_user_agent,
)
from wormbase_ledger import InMemoryLedger, Ledger

logger = logging.getLogger("wormbase_core.mcp_tools.audit")

LedgerLike = Ledger | InMemoryLedger | Any

AUDIT_TOOL_NAMES = ("read_audit_trail",)


# ---------------------------------------------------------------------------
# Pure ledger fold — testable independently of the FastMCP wiring.
# ---------------------------------------------------------------------------


# Fields on execute payloads that may carry the asset's id under one of
# many names. We scan them in turn so the same audit tool works
# regardless of whether the asset is a KPI, a data product, a person, etc.
_REF_FIELDS: tuple[str, ...] = (
    "kpi_id",
    "data_product_id",
    "person_id",
    "decision_id",
    "process_id",
    "source_id",
    "notebook_id",
    "reactivity_id",
    "concept_id",
    "resource_id",
    "node_id",
    "id",
)


# Tools that mark an asset as "confirmed" — used to extract
# ``confirmed_by`` + ``confirmed_at``. Each value is the args-key the
# corresponding payload uses for the confirming actor.
_CONFIRM_TOOL_TO_ACTOR_FIELD: dict[str, str] = {
    "emit_person_confirmed": "confirmed_by",
    "emit_source_confirmed": "confirmed_by_person",
    "emit_concept_confirmed": "confirmed_by_person",
    "emit_kpi_confirmed": "confirmed_by",
    "emit_data_product_generated": "confirmed_by",
    "emit_notebook_published": "owner_person_id",
    "emit_reactivity_confirmed": "confirmed_by",
    "emit_decision_recorded": "decided_by_persons",
    "emit_process_map_confirmed": "confirmed_by",
}


def _ts_str(ts: Any) -> str:
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


def _entry_touches_id(entry: dict[str, Any], entry_id: str) -> bool:
    """Return True iff this entry references the asset under any known field.

    Checks both the propose envelope's ``ref_id`` and every execute-args
    field in :data:`_REF_FIELDS`. Stable across all proposing entry kinds.
    """
    payload = entry.get("payload") or {}
    if entry.get("kind") == "propose":
        ref_id = payload.get("ref_id")
        if ref_id is not None and str(ref_id) == entry_id:
            return True
    if entry.get("kind") == "execute":
        args = payload.get("args") or {}
        for f in _REF_FIELDS:
            v = args.get(f)
            if v is not None and str(v) == entry_id:
                return True
    return False


def _extract_confirm_actor(
    tool: str, args: dict[str, Any]
) -> str | None:
    """Pull the confirming actor id from a confirm-shaped execute entry.

    Most confirm payloads use a single UUID under one of a handful of
    keys (``confirmed_by``, ``confirmed_by_person``, ``owner_person_id``).
    ``emit_decision_recorded`` is special-cased: its ``decided_by_persons``
    is a list, and the canonical confirm-actor is the first entry.
    """
    field = _CONFIRM_TOOL_TO_ACTOR_FIELD.get(tool)
    if field is None:
        return None
    val = args.get(field)
    if val is None:
        return None
    if isinstance(val, list):
        return str(val[0]) if val else None
    return str(val)


def fold_audit_trail(
    rows: list[dict[str, Any]], *, entry_id: str,
) -> dict[str, Any] | None:
    """Reconstruct the full audit chain for ``entry_id``.

    Returns ``None`` if no entry references the id; otherwise a dict
    with ``proposed_by`` / ``confirmed_by`` / ``confirmed_at`` /
    ``ledger_range`` / ``contributing_entries``. Pure: no I/O, no
    filesystem, deterministic on identical input.

    The PEVR cycle is reconstructed by transitive closure: starting
    from any propose / execute entry that directly references the
    id, we follow the canonical PEVR back-references
    (``propose_entry_id``, ``execute_entry_id``, ``verify_entry_id``)
    forward to pick up the verify + resolve entries that complete
    the cycle. This way the contributing-entries list always shows
    the full 4-entry cycle, not just the 2 entries that mention the
    asset id directly.
    """
    proposed_by: str | None = None
    proposed_at: str | None = None
    target_kind: str | None = None
    confirmed_by: str | None = None
    confirmed_at: str | None = None

    # Step 1: identify the entries that DIRECTLY mention the id.
    direct_entry_ids: set[str] = set()
    for entry in rows:
        if _entry_touches_id(entry, entry_id):
            eid = entry.get("entry_id")
            if eid is not None:
                direct_entry_ids.add(str(eid))

    # Step 2: transitively grow the membership by walking PEVR links.
    # An execute entry whose ``propose_entry_id`` is in the membership
    # joins; a verify whose ``execute_entry_id`` is in the membership
    # joins; a resolve whose ``verify_entry_id`` is in the membership
    # joins. We iterate to a fixed point so the order rows happen to
    # arrive in does not matter.
    member_ids: set[str] = set(direct_entry_ids)
    for _ in range(4):  # PEVR is at most 4 links deep per cycle
        grew = False
        for entry in rows:
            eid = entry.get("entry_id")
            if eid is None or str(eid) in member_ids:
                continue
            kind = entry.get("kind")
            payload = entry.get("payload") or {}
            parent_field = {
                "execute": "propose_entry_id",
                "verify": "execute_entry_id",
                "resolve": "verify_entry_id",
            }.get(kind or "")
            if parent_field is None:
                continue
            parent = payload.get(parent_field)
            if parent is not None and str(parent) in member_ids:
                member_ids.add(str(eid))
                grew = True
        if not grew:
            break

    # Step 3: project into the wire shape + extract attribution.
    contributing: list[dict[str, Any]] = []
    for entry in rows:
        eid = entry.get("entry_id")
        if eid is None or str(eid) not in member_ids:
            continue
        kind = entry.get("kind")
        payload = entry.get("payload") or {}
        ts = entry.get("ts")
        seq = entry.get("seq")

        tool = payload.get("tool") if kind == "execute" else None
        outcome = payload.get("outcome") if kind == "resolve" else None
        contributing.append(
            {
                "seq": seq,
                "ts": _ts_str(ts),
                "kind": kind,
                "tool": tool,
                "outcome": outcome,
            }
        )

        # First-touched ``propose`` envelope wins for proposed_by /
        # proposed_at / target_kind. PEVR guarantees one propose per
        # cycle, so the first one we see for this ref is canonical.
        if kind == "propose" and proposed_by is None:
            proposed_by = str(payload.get("proposed_by") or "")
            proposed_at = _ts_str(ts)
            target_kind = payload.get("target_kind")

        # Latest confirm-shaped execute wins for confirmed_by /
        # confirmed_at; explicit confirm beats implicit lifecycle.
        if kind == "execute" and tool in _CONFIRM_TOOL_TO_ACTOR_FIELD:
            args = payload.get("args") or {}
            actor = _extract_confirm_actor(tool, args)
            if actor:
                confirmed_by = actor
                confirmed_at = _ts_str(ts)

    if not contributing:
        return None

    # Sort by seq so the timeline reads forward.
    contributing.sort(key=lambda c: c["seq"] if c["seq"] is not None else -1)

    seqs = [c["seq"] for c in contributing if c["seq"] is not None]
    ledger_range = {
        "first_seq": min(seqs) if seqs else None,
        "last_seq": max(seqs) if seqs else None,
    }

    return {
        "entry_id": entry_id,
        "target_kind": target_kind,
        "proposed_by": proposed_by,
        "proposed_at": proposed_at,
        "confirmed_by": confirmed_by,
        "confirmed_at": confirmed_at,
        "ledger_range": ledger_range,
        "contributing_entries": contributing,
    }


# ---------------------------------------------------------------------------
# FastMCP registration
# ---------------------------------------------------------------------------


def register_audit_tools(
    mcp: FastMCP,
    *,
    ledger: LedgerLike,
    api_token: str,
) -> None:
    """Register the ``read_audit_trail`` tool on the FastMCP instance."""

    @mcp.tool()
    async def read_audit_trail(
        company_id: str,
        entry_id: str,
        ctx: Context,
    ) -> dict[str, Any]:
        """Return the full attribution chain for an asset by id.

        Args:
            company_id: tenant slug.
            entry_id: the asset's canonical UUID — ``kpi_id`` returned
                from ``propose_kpi``, ``data_product_id`` from
                ``propose_data_product``, ``person_id``, ``decision_id``,
                ``process_id``, ``source_id``, ``notebook_id``,
                ``reactivity_id``, ``concept_id``, or ``resource_id``.

        Returns:
            ``{entry_id, target_kind, proposed_by, proposed_at,
            confirmed_by, confirmed_at, ledger_range,
            contributing_entries}``. Fields are ``null`` when the
            ledger has no matching entry of that role yet (e.g.
            a freshly-proposed KPI has ``confirmed_by: null``).

        Admin-only: members + unknown roles get an empty payload.
        """
        started_at = datetime.now(tz=UTC)
        t0 = time.perf_counter()
        request_args = {"company_id": company_id, "entry_id": entry_id}
        args_hash = canonical_args_hash(request_args)
        client_ua = resolve_user_agent(ctx)

        try:
            caller = await authorize_caller(
                ctx,
                ledger=ledger,
                api_token=api_token,
                fallback_company_id=company_id,
            )
        except PermissionError:
            elapsed = int((time.perf_counter() - t0) * 1000)
            try:
                from wormbase_core.service import tenant_to_uuid as _t
                cid = _t(company_id)
            except Exception:  # noqa: BLE001
                cid = None
            if cid is not None:
                await audit(
                    ledger,
                    company_id=cid,
                    caller_person_id=None,
                    tool_name="read_audit_trail",
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
                tool_name="read_audit_trail",
                args_hash=args_hash,
                client_ua=client_ua,
                started_at=started_at,
                outcome="denied",
                latency_ms=elapsed,
            )
            raise

        if caller["tenancy_role"] not in ("admin", "installer"):
            elapsed = int((time.perf_counter() - t0) * 1000)
            await audit(
                ledger,
                company_id=caller["company_id"],
                caller_person_id=caller["caller_person_id"],
                tool_name="read_audit_trail",
                args_hash=args_hash,
                client_ua=client_ua,
                started_at=started_at,
                outcome="denied",
                latency_ms=elapsed,
            )
            return {
                "entry_id": entry_id,
                "target_kind": None,
                "proposed_by": None,
                "proposed_at": None,
                "confirmed_by": None,
                "confirmed_at": None,
                "ledger_range": {"first_seq": None, "last_seq": None},
                "contributing_entries": [],
            }

        rows = await ledger.fetch(caller["company_id"])
        chain = fold_audit_trail(rows, entry_id=entry_id)
        if chain is None:
            chain = {
                "entry_id": entry_id,
                "target_kind": None,
                "proposed_by": None,
                "proposed_at": None,
                "confirmed_by": None,
                "confirmed_at": None,
                "ledger_range": {"first_seq": None, "last_seq": None},
                "contributing_entries": [],
            }

        elapsed = int((time.perf_counter() - t0) * 1000)
        await audit(
            ledger,
            company_id=caller["company_id"],
            caller_person_id=caller["caller_person_id"],
            tool_name="read_audit_trail",
            args_hash=args_hash,
            client_ua=client_ua,
            started_at=started_at,
            outcome="ok",
            latency_ms=elapsed,
        )
        return chain


__all__ = [
    "AUDIT_TOOL_NAMES",
    "fold_audit_trail",
    "register_audit_tools",
]
