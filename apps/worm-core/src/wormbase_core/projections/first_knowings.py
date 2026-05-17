"""First-Knowing projection (Demo-day P12).

Lists phenomena the worm has detected but the org has *not* yet
confirmed — i.e. ``proposed_by`` is a worm/agent identity and the
matching ``*_confirmed`` (or accept) entry has not landed for the
referenced ``ref_id``.

This is the **institutional-AI wedge made visible** (Altman Q1):
"What does the worm know that the org's CDO doesn't, with the ledger
entry where it knew it first?"

Phenomenon kinds:

  * ``kpi_gap``       — ``phenomenon_gap_detected`` with ``gap_kind="kpi"`` and
                         no matching ``kpi_confirmed`` for the suggested ref_id.
  * ``domain_gap``    — ``phenomenon_gap_detected`` with ``gap_kind="domain"``.
  * ``process_gap``   — ``phenomenon_gap_detected`` with ``gap_kind="process"``.
  * ``reactivity_gap`` — ``phenomenon_gap_detected`` with ``gap_kind="reactivity"``
                         OR raw ``reactivity_proposed`` proposed_by a worm/agent
                         identity that has not yet been confirmed.
  * ``person_gap``    — ``person_proposed`` proposed_by a worm/agent identity
                         that has not yet reached ``person_confirmed``.

Each row carries:

  * ``kind``                — one of the above five
  * ``summary``             — one-line human-readable summary
  * ``first_detected_seq``  — the seq of the originating propose row
  * ``first_detected_ts``   — ISO-8601 UTC of the propose row
  * ``ref_id``              — the proposed entity's id
  * ``referenced_in_seq``   — the chat_received seq that triggered the
                              detection (when the propose payload carries
                              one — phenomenon_gap_detected does, raw
                              proposes do not)
  * ``confidence``          — for phenomenon-gap entries, the detector's
                              confidence in [0, 1]; ``None`` for raw proposes
  * ``novelty_key``         — for phenomenon-gap entries, the de-dup key;
                              ``""`` for raw proposes

Replay safety: the row stream is the only input. Two replays with
identical seqs produce byte-identical first-knowing lists in identical
order. Order is sequence-stable (newest seq first).

Empty-state honesty (CLAUDE.md ¶9): an empty row stream returns ``[]``.
The dashboard tab renders an honest "the worm has not detected anything
the org hasn't confirmed yet" message instead of a fixture row.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

PhenomenonKind = Literal[
    "kpi_gap",
    "domain_gap",
    "process_gap",
    "reactivity_gap",
    "person_gap",
]

#: Stable canonical ordering used for the dashboard filter chips and for
#: deterministic ordering of the per-kind projection.
PHENOMENON_KINDS: tuple[PhenomenonKind, ...] = (
    "kpi_gap",
    "domain_gap",
    "process_gap",
    "reactivity_gap",
    "person_gap",
)

ScopeFilter = Literal["mine", "team", "company"]

#: Recency window labels mirrored by the dashboard chips.
RecencyFilter = Literal["1h", "24h", "7d", "all"]


@dataclass(frozen=True)
class FirstKnowingRow:
    """One un-confirmed phenomenon discovered by the worm.

    ``ref_id`` is the natural key for the proposed entity (kpi_id /
    person_id / reactivity_id / etc.). It is stable across replays.
    """

    kind: PhenomenonKind
    summary: str
    first_detected_seq: int
    first_detected_ts: str  # ISO-8601 UTC
    ref_id: str
    referenced_in_seq: int  # 0 when no chat triggered the detection
    confidence: float | None
    novelty_key: str
    proposed_by: str
    target_kind: str
    scope: ScopeFilter

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "first_detected_seq": self.first_detected_seq,
            "first_detected_ts": self.first_detected_ts,
            "ref_id": self.ref_id,
            "referenced_in_seq": self.referenced_in_seq,
            "confidence": self.confidence,
            "novelty_key": self.novelty_key,
            "proposed_by": self.proposed_by,
            "target_kind": self.target_kind,
            "scope": self.scope,
        }


@dataclass(frozen=True)
class FirstKnowingsResult:
    """All un-confirmed first-knowings + the chatter context lookup index."""

    rows: list[FirstKnowingRow] = field(default_factory=list)
    #: ``referenced_in_seq → list[chat_received_row_dict]`` of three
    #: chat_received rows above and three below the triggering seq, in
    #: ascending seq order. Empty list when no chat context surfaces.
    chatter_context: dict[int, list[dict[str, Any]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": [r.to_dict() for r in self.rows],
            "chatter_context": {
                str(k): list(v) for k, v in self.chatter_context.items()
            },
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

#: ``proposed_by`` values that signal "the worm" rather than a human admin.
#: Rather than enumerating the full taxonomy of agent labels (which grows
#: with each reactivity), we treat any value other than a UUID-string and
#: not in this denylist as a worm identity. This keeps the projection
#: forward-compatible with new reactivities.
_HUMAN_PROPOSER_DENYLIST: frozenset[str] = frozenset({
    "admin",
    "human",
    "system",
})


def _looks_like_uuid(s: str) -> bool:
    """A loose UUID heuristic — same shape as the canonical 36-char form."""
    if len(s) != 36:
        return False
    return all(c == "-" or c.isalnum() for c in s)


def _is_worm_proposer(proposed_by: str) -> bool:
    """True iff ``proposed_by`` looks like a non-human (agent) identity."""
    if not proposed_by:
        return False
    if proposed_by in _HUMAN_PROPOSER_DENYLIST:
        return False
    if _looks_like_uuid(proposed_by):
        # Person-id strings are confirmations from a real Person, not the worm.
        return False
    return True


def _ts_of(row: Mapping[str, Any]) -> datetime:
    ts = row.get("ts")
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    if isinstance(ts, str):
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    raise TypeError(f"unparseable ts on row seq={row.get('seq')!r}: {ts!r}")


def _seq_of(row: Mapping[str, Any]) -> int:
    seq = row.get("seq", 0)
    try:
        return int(seq)
    except (TypeError, ValueError):
        return 0


def _execute_args(row: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Return ``(tool, args)`` for execute rows, else None."""
    if row.get("kind") != "execute":
        return None
    payload = row.get("payload") or {}
    tool = payload.get("tool")
    args = payload.get("args") or {}
    if not isinstance(tool, str):
        return None
    if not isinstance(args, dict):
        args = {}
    return tool, args


def _propose_payload(row: Mapping[str, Any]) -> dict[str, Any] | None:
    if row.get("kind") != "propose":
        return None
    payload = row.get("payload") or {}
    if not isinstance(payload, dict):
        return None
    return payload


def _scope_of(target_kind: str, args: dict[str, Any]) -> ScopeFilter:
    """Infer scope from the propose payload.

    Defaults to ``company`` (org-wide) — phenomenon-gap detection is
    company-scoped by construction (W5.A3). Person-gap proposals fall
    back to ``mine`` since they always pertain to a specific Person.
    Future per-person reactivity proposals (W5.A4 audience scoping) will
    refine this; the projection stays forward-compatible by inspecting
    ``args.audience`` when present.
    """
    audience = args.get("audience") if isinstance(args, dict) else None
    if isinstance(audience, str):
        if audience.startswith("person:"):
            return "mine"
        if audience.startswith("team:"):
            return "team"
        if audience == "company":
            return "company"
    if target_kind == "person_proposed":
        return "mine"
    return "company"


def _summarize_phenomenon_gap(
    gap_kind: str,
    suggested: dict[str, Any],
    confidence: float,
) -> str:
    """One-line summary for a ``phenomenon_gap_detected`` row."""
    label = ""
    if gap_kind == "kpi":
        label = (
            suggested.get("label")
            or suggested.get("name")
            or suggested.get("kpi_label")
            or "an unknown KPI"
        )
        return f"KPI gap detected: {label} (confidence {confidence:.2f})"
    if gap_kind == "domain":
        label = suggested.get("name") or suggested.get("domain") or "an unknown domain"
        return f"Domain gap detected: {label} (confidence {confidence:.2f})"
    if gap_kind == "process":
        label = (
            suggested.get("label")
            or suggested.get("topic")
            or "a recurring workflow"
        )
        return f"Process gap detected: {label} (confidence {confidence:.2f})"
    if gap_kind == "reactivity":
        label = (
            suggested.get("name")
            or suggested.get("predicate")
            or "an unobserved trigger"
        )
        return f"Reactivity gap detected: {label} (confidence {confidence:.2f})"
    return f"Phenomenon gap ({gap_kind}) detected (confidence {confidence:.2f})"


def _summarize_person_propose(args: dict[str, Any]) -> str:
    name = args.get("name") or "an unidentified Person"
    platform = args.get("platform") or "unknown platform"
    return f"Person gap: '{name}' on {platform} not yet confirmed"


def _summarize_reactivity_propose(args: dict[str, Any]) -> str:
    name = args.get("name") or args.get("predicate") or "an unnamed Reactivity"
    return f"Reactivity gap: '{name}' proposed but not confirmed"


def _gap_kind_to_first_knowing(gap_kind: str) -> PhenomenonKind:
    if gap_kind == "kpi":
        return "kpi_gap"
    if gap_kind == "domain":
        return "domain_gap"
    if gap_kind == "process":
        return "process_gap"
    if gap_kind == "reactivity":
        return "reactivity_gap"
    # Default: surface as kpi_gap since the detector default kind is kpi
    # in W5.A3 — keeps the chip filtering predictable on unknown values.
    return "kpi_gap"


def _within_window(
    ts: datetime, *, now: datetime, recency: RecencyFilter,
) -> bool:
    if recency == "all":
        return True
    delta = now - ts
    if recency == "1h":
        return delta <= timedelta(hours=1)
    if recency == "24h":
        return delta <= timedelta(hours=24)
    if recency == "7d":
        return delta <= timedelta(days=7)
    return True


# ---------------------------------------------------------------------------
# Public projection
# ---------------------------------------------------------------------------


def compute_first_knowings(
    rows: Iterable[Mapping[str, Any]],
    *,
    kinds: tuple[PhenomenonKind, ...] | None = None,
    scope: ScopeFilter | None = None,
    recency: RecencyFilter = "all",
    chatter_context_radius: int = 3,
    now: datetime | None = None,
) -> FirstKnowingsResult:
    """Fold a tenant's ledger row stream into un-confirmed first-knowings.

    Parameters
    ----------
    rows
        Full row stream for a tenant. Caller is responsible for tenant
        filtering (the projection is tenant-agnostic by design).
    kinds
        If given, only return rows of these phenomenon kinds. ``None``
        returns all five.
    scope
        If given, only return rows matching this scope.
    recency
        ``"1h" | "24h" | "7d" | "all"``. Filters by ``first_detected_ts``
        relative to ``now``. Default ``"all"``.
    chatter_context_radius
        Number of chat_received rows to include above and below each
        ``referenced_in_seq``. Default 3 (per PRD §7 P12).
    now
        Pin the recency horizon for tests; defaults to ``datetime.now(UTC)``.

    Returns
    -------
    FirstKnowingsResult
        ``rows`` newest-seq-first; ``chatter_context`` keyed by
        ``referenced_in_seq``.
    """
    now_dt = now if now is not None else datetime.now(UTC)
    rows_list = list(rows)

    # Pass 1 — index confirmations (kpi/person/reactivity/domain/process)
    # so we can answer "is ref_id confirmed?" in O(1).
    confirmed_refs: set[str] = set()
    archived_refs: set[str] = set()
    chat_rows_by_seq: dict[int, dict[str, Any]] = {}

    for row in rows_list:
        kind = row.get("kind")
        seq = _seq_of(row)
        # Track chat rows for the chatter-context lookup.
        if kind == "chat_received":
            chat_rows_by_seq[seq] = dict(row)
            continue
        ex = _execute_args(row)
        if ex is None:
            continue
        tool, args = ex
        if tool in (
            "emit_chat_received",
            "channel_adapter.emit_chat_received",
        ):
            chat_rows_by_seq[seq] = dict(row)
            continue
        # Confirmation entries; track by the canonical id-field.
        if tool == "emit_person_confirmed":
            pid = str(args.get("person_id") or "")
            if pid:
                confirmed_refs.add(pid)
        elif tool in (
            "emit_kpi_confirmed",
            "emit_kpi_resolved",
        ):
            kid = str(args.get("kpi_id") or "")
            if kid:
                confirmed_refs.add(kid)
        elif tool in (
            "emit_reactivity_confirmed",
            "emit_reactivity_disabled",
        ):
            rid = str(args.get("reactivity_id") or "")
            if rid:
                confirmed_refs.add(rid)
        elif tool == "emit_domain_confirmed":
            did = str(args.get("domain_id") or "")
            if did:
                confirmed_refs.add(did)
        elif tool in (
            "emit_data_product_confirmed",
            "emit_data_product_published",
        ):
            pid = str(args.get("data_product_id") or args.get("artifact_id") or "")
            if pid:
                confirmed_refs.add(pid)
        elif tool == "emit_phenomenon_gap_resolved":
            # Resolution entry — explicit close on a phenomenon-gap row.
            nk = str(args.get("novelty_key") or "")
            if nk:
                confirmed_refs.add(f"phenomenon_gap:{nk}")
        elif tool == "emit_person_archived":
            pid = str(args.get("person_id") or "")
            if pid:
                archived_refs.add(pid)

    # Pass 2 — collect candidate first-knowings from propose rows + the
    # canonical phenomenon_gap_detected execute rows.
    out_rows: list[FirstKnowingRow] = []

    # Track per-(target_kind, ref_id) so we surface only the FIRST detection
    # (smallest seq); that's the "where it knew it first" semantics.
    seen_keys: set[tuple[str, str]] = set()

    # First, fold phenomenon_gap_detected execute rows. These are richer —
    # they carry referenced_in_seq + suggested_proposal + confidence + novelty_key.
    for row in rows_list:
        ex = _execute_args(row)
        if ex is None:
            continue
        tool, args = ex
        if tool != "emit_phenomenon_gap_detected":
            continue
        seq = _seq_of(row)
        ts = _ts_of(row)
        # Pydantic serialises with field_alias=kind; canonical fold checks both.
        gap_kind = (
            args.get("gap_kind")
            or args.get("kind")
            or ""
        )
        if not isinstance(gap_kind, str):
            continue
        novelty_key = str(args.get("novelty_key") or "")
        # Use novelty_key as the natural ref so re-detections coalesce.
        ref_id = f"phenomenon_gap:{novelty_key}" if novelty_key else f"phenomenon_gap:{seq}"
        key = ("phenomenon_gap_detected", ref_id)
        if key in seen_keys:
            continue
        if ref_id in confirmed_refs:
            continue
        seen_keys.add(key)

        try:
            confidence = float(args.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        try:
            ref_in_seq = int(args.get("referenced_in_seq") or 0)
        except (TypeError, ValueError):
            ref_in_seq = 0
        suggested = args.get("suggested_proposal") or {}
        if not isinstance(suggested, dict):
            suggested = {}

        kind = _gap_kind_to_first_knowing(gap_kind)
        scope_v = _scope_of("phenomenon_gap_detected", args)
        out_rows.append(
            FirstKnowingRow(
                kind=kind,
                summary=_summarize_phenomenon_gap(gap_kind, suggested, confidence),
                first_detected_seq=seq,
                first_detected_ts=ts.isoformat(),
                ref_id=ref_id,
                referenced_in_seq=ref_in_seq,
                confidence=confidence,
                novelty_key=novelty_key,
                proposed_by="phenomenon_gap_detector",
                target_kind="phenomenon_gap_detected",
                scope=scope_v,
            )
        )

    # Second, fold raw proposes — person_proposed / reactivity_proposed —
    # whose proposed_by signals a worm/agent identity and whose ref_id has
    # not been confirmed (or archived).
    for row in rows_list:
        propose = _propose_payload(row)
        if propose is None:
            continue
        target_kind = str(propose.get("target_kind") or "")
        ref_id = str(propose.get("ref_id") or "")
        proposed_by = str(propose.get("proposed_by") or "")
        if not ref_id or not target_kind:
            continue
        if not _is_worm_proposer(proposed_by):
            continue
        # Only Person- and Reactivity-shaped raw proposes; phenomenon_gap
        # is handled above.
        if target_kind == "person_proposed":
            kind: PhenomenonKind = "person_gap"
        elif target_kind == "reactivity_proposed":
            kind = "reactivity_gap"
        else:
            continue
        if ref_id in confirmed_refs or ref_id in archived_refs:
            continue
        key = (target_kind, ref_id)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        seq = _seq_of(row)
        ts = _ts_of(row)
        # Pull the matching execute row's args (next row in canonical PEVR
        # order) for a richer summary; fall back to the propose payload.
        args = _find_matching_execute_args(rows_list, seq, target_kind)

        if target_kind == "person_proposed":
            summary = _summarize_person_propose(args)
            scope_v: ScopeFilter = "mine"
        else:  # reactivity_proposed
            summary = _summarize_reactivity_propose(args)
            scope_v = _scope_of(target_kind, args)

        out_rows.append(
            FirstKnowingRow(
                kind=kind,
                summary=summary,
                first_detected_seq=seq,
                first_detected_ts=ts.isoformat(),
                ref_id=ref_id,
                referenced_in_seq=0,
                confidence=None,
                novelty_key="",
                proposed_by=proposed_by,
                target_kind=target_kind,
                scope=scope_v,
            )
        )

    # Filter by chip selectors.
    filtered: list[FirstKnowingRow] = []
    wanted_kinds = set(kinds) if kinds else set(PHENOMENON_KINDS)
    for r in out_rows:
        if r.kind not in wanted_kinds:
            continue
        if scope is not None and r.scope != scope:
            continue
        ts = datetime.fromisoformat(r.first_detected_ts)
        if not _within_window(ts, now=now_dt, recency=recency):
            continue
        filtered.append(r)

    # Newest seq first.
    filtered.sort(key=lambda r: r.first_detected_seq, reverse=True)

    # Build chatter context for each unique referenced_in_seq.
    chatter: dict[int, list[dict[str, Any]]] = {}
    sorted_chat_seqs = sorted(chat_rows_by_seq.keys())
    for r in filtered:
        anchor = r.referenced_in_seq
        if anchor <= 0:
            continue
        if anchor in chatter:
            continue
        # Find the position of `anchor` (or the closest chat row preceding it)
        # in the sorted chat-seq list, then take ±radius around it.
        # Bisect-style scan keeps the projection dependency-free.
        pos = -1
        for i, s in enumerate(sorted_chat_seqs):
            if s == anchor:
                pos = i
                break
            if s > anchor:
                pos = i  # anchor falls between rows; treat next-newer as anchor
                break
        if pos < 0:
            # Anchor seq not in our chat index.
            chatter[anchor] = []
            continue
        lo = max(0, pos - chatter_context_radius)
        hi = min(len(sorted_chat_seqs), pos + chatter_context_radius + 1)
        window_seqs = sorted_chat_seqs[lo:hi]
        chatter[anchor] = [chat_rows_by_seq[s] for s in window_seqs]

    return FirstKnowingsResult(rows=filtered, chatter_context=chatter)


def _find_matching_execute_args(
    rows: list[Mapping[str, Any]],
    propose_seq: int,
    target_kind: str,
) -> dict[str, Any]:
    """Locate the execute row matching a propose's PEVR cycle.

    Walks forward from ``propose_seq``; the canonical PEVR shape places
    the matching execute at ``propose_seq + 1``. We tolerate gaps so an
    interleaved write does not break the lookup.
    """
    needed_tool = f"emit_{target_kind}"
    for r in rows:
        s = _seq_of(r)
        if s <= propose_seq:
            continue
        if s > propose_seq + 8:
            # PEVR is 4 rows; if we haven't found the execute by 8 rows
            # forward, the propose was rolled back.
            break
        ex = _execute_args(r)
        if ex is None:
            continue
        tool, args = ex
        if tool == needed_tool:
            return dict(args)
    return {}


__all__ = [
    "FirstKnowingRow",
    "FirstKnowingsResult",
    "PHENOMENON_KINDS",
    "PhenomenonKind",
    "RecencyFilter",
    "ScopeFilter",
    "compute_first_knowings",
]
