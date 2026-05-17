"""``composite_score`` projection (Demo-day P1).

A single scalar in [0, 1] folded from four ratio-shaped signals over a
trailing 7-day window per scope. The demo wants the *loss-style*
display value (``1 - normalized_score``) to descend across Beats 1-9 of
the install arc, mirroring Karpathy's autoresearch intuition: the
research community of agents drives a headline metric monotonically.

Inputs (all read from the ledger, never derived from anywhere else):

  * **Gate-fire precision** — for ``gate_fired`` entries with outcome
    ``allowed``, the fraction whose subject-ref later landed as
    ``experiment_kept`` (vs ``experiment_discarded``). ``blocked`` and
    ``warned`` outcomes are not counted in the denominator. When no
    ``gate_fired`` entries exist in the window the signal contributes
    a neutral 0.5.
  * **Propose→keep ratio** — fraction of ``experiment_proposed`` entries
    whose corresponding ``experiment_resolved`` outcome is ``keep`` vs
    ``discard``. Pending experiments (no resolution) are not in the
    denominator. Empty → 0.5.
  * **Ramp-gauge delta** — sum of monotonic increments on the three
    ramp axes (ontology, conversational, kpi_relational) over the
    window, normalized to [0, 1] by capping at 30 increments (a full
    install arc). Empty → 0.0.
  * **Reactivity confirm rate** — fraction of ``reactivity_proposed``
    entries that reached ``reactivity_confirmed`` within the window.
    Empty → 0.5.

Equal weights (0.25 each) for v1. Configurable per-tenant via a
``composite_score_weights`` ledger entry — admin-emit only. The latest
weights entry observed before ``until_seq`` wins.

Output normalised to [0, 1]; the dashboard renders ``1 - score`` as
the descending loss curve. The series accessor returns ≥9 points by
default so the install arc draws a clean curve.

Replay safety: every input is a deterministic function of the ledger
row stream. Two replays with identical seqs produce byte-identical
scores down to the last float bit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

# Default 7-day rolling window per the PRD §7 P1 contract.
DEFAULT_WINDOW_DAYS: int = 7

# Default equal weights (0.25 each) for v1. Sum must be 1.0.
DEFAULT_WEIGHTS: Mapping[str, float] = {
    "gate_precision": 0.25,
    "propose_keep_ratio": 0.25,
    "ramp_delta": 0.25,
    "reactivity_confirm_rate": 0.25,
}

# Empty-signal fallbacks. 0.5 is "neutral" for ratio-shaped signals so
# an empty ledger doesn't make the loss curve plummet to 1.0 spuriously
# at the start of the arc. Ramp delta starts at 0.0 because the install
# arc is *expected* to grow it from empty.
_NEUTRAL_RATIO: float = 0.5
_NEUTRAL_RAMP: float = 0.0

# Cap for ramp-delta normalization — a full install arc emits ~30 ramp
# increments across the three axes, so 30 maps to 1.0. Constant; future
# tenants with longer arcs may override via config entry (out of scope
# for v1).
_RAMP_DELTA_CAP: int = 30


@dataclass(frozen=True)
class CompositeScorePoint:
    """A single (ledger_height, score) sample plus its top contributor.

    ``top_contributor_reactivity_id`` is the reactivity_id that fired
    the most ``reactivity_fired`` entries within the contributing range
    (the trailing 7-day window anchored at ``ts``). Empty string when
    no reactivities fired in the window.
    """

    ledger_height: int
    ts: str  # ISO-8601 UTC
    score: float
    components: dict[str, float]
    top_contributor_reactivity_id: str
    contributing_seq_lo: int
    contributing_seq_hi: int


@dataclass(frozen=True)
class CompositeScoreSeries:
    """≥9 points across the trailing window, sampled at uniform stride."""

    tenant_id: str
    points: list[CompositeScorePoint] = field(default_factory=list)
    window_days: int = DEFAULT_WINDOW_DAYS
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


@dataclass(frozen=True)
class CompositeScore:
    """Single-point composite score evaluated at ``ledger_height``."""

    tenant_id: str
    ledger_height: int
    score: float
    components: dict[str, float]
    weights: dict[str, float]


# ---------------------------------------------------------------------------
# Helpers — pure functions over the ledger row stream
# ---------------------------------------------------------------------------


def _is_execute_with_tool(row: Mapping[str, Any], tool: str) -> bool:
    return (
        row.get("kind") == "execute"
        and row.get("payload", {}).get("tool") == tool
    )


def _is_kind(row: Mapping[str, Any], kind: str) -> bool:
    return row.get("kind") == kind


def _ts_of(row: Mapping[str, Any]) -> datetime:
    ts = row.get("ts")
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    if isinstance(ts, str):
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    raise TypeError(f"unparseable ts on row seq={row.get('seq')!r}: {ts!r}")


def _gate_fire_precision(
    rows_in_window: list[Mapping[str, Any]],
) -> float:
    """Allowed gate-fires whose subject was later kept vs discarded."""
    allowed = [
        r
        for r in rows_in_window
        if _is_kind(r, "gate_fired")
        and r.get("payload", {}).get("outcome") == "allowed"
    ]
    if not allowed:
        return _NEUTRAL_RATIO

    # Subject-refs that resolved as keep / discard.
    kept_refs: set[str] = set()
    discarded_refs: set[str] = set()
    for r in rows_in_window:
        if _is_execute_with_tool(r, "emit_experiment_resolved"):
            args = r["payload"].get("args", {}) or {}
            subj = str(args.get("experiment_id", ""))
            if not subj:
                continue
            outcome = args.get("outcome")
            if outcome == "keep":
                kept_refs.add(subj)
            elif outcome == "discard":
                discarded_refs.add(subj)

    upheld = 0
    rejected = 0
    for g in allowed:
        subj = str(g.get("payload", {}).get("subject_ref", ""))
        if subj in kept_refs:
            upheld += 1
        elif subj in discarded_refs:
            rejected += 1
    total = upheld + rejected
    if total == 0:
        return _NEUTRAL_RATIO
    return upheld / total


def _propose_keep_ratio(rows_in_window: list[Mapping[str, Any]]) -> float:
    """``experiment_kept`` / (``experiment_kept`` + ``experiment_discarded``)."""
    kept = 0
    discarded = 0
    for r in rows_in_window:
        if not _is_execute_with_tool(r, "emit_experiment_resolved"):
            continue
        outcome = r.get("payload", {}).get("args", {}).get("outcome")
        if outcome == "keep":
            kept += 1
        elif outcome == "discard":
            discarded += 1
    total = kept + discarded
    if total == 0:
        return _NEUTRAL_RATIO
    return kept / total


def _ramp_delta(rows_in_window: list[Mapping[str, Any]]) -> float:
    """Count monotonic ramp increments across ontology + conversational + relational.

    Mirrors the canonical builder's ramp formula at a coarse level:
    each memory_written ticks ontology, each chat_received ticks
    conversational, each kpi_proposed ticks relational. Capped at
    ``_RAMP_DELTA_CAP`` and normalized to [0, 1].
    """
    increments = 0
    for r in rows_in_window:
        kind = r.get("kind")
        if kind == "chat_received":
            increments += 1
        elif _is_execute_with_tool(r, "emit_memory_written"):
            increments += 1
        elif _is_execute_with_tool(r, "emit_kpi_proposed"):
            increments += 1
    if increments <= 0:
        return _NEUTRAL_RAMP
    return min(1.0, increments / float(_RAMP_DELTA_CAP))


def _reactivity_confirm_rate(rows_in_window: list[Mapping[str, Any]]) -> float:
    """proposed → confirmed within the window."""
    proposed: set[str] = set()
    confirmed: set[str] = set()
    for r in rows_in_window:
        if _is_execute_with_tool(r, "emit_reactivity_proposed"):
            rid = r["payload"].get("args", {}).get("reactivity_id")
            if rid:
                proposed.add(str(rid))
        elif _is_execute_with_tool(r, "emit_reactivity_confirmed"):
            rid = r["payload"].get("args", {}).get("reactivity_id")
            if rid:
                confirmed.add(str(rid))
    if not proposed:
        return _NEUTRAL_RATIO
    intersect = len(proposed & confirmed)
    return intersect / len(proposed)


def _top_contributor_reactivity(
    rows_in_window: list[Mapping[str, Any]],
) -> str:
    """reactivity_id that fired the most times in the window. ``""`` if none."""
    counts: dict[str, int] = {}
    for r in rows_in_window:
        if not _is_execute_with_tool(r, "emit_reactivity_fired"):
            continue
        rid = r["payload"].get("args", {}).get("reactivity_id")
        if rid:
            key = str(rid)
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return ""
    # Deterministic tie-break: highest count, then lex-sorted reactivity_id.
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _resolve_weights(
    rows: list[Mapping[str, Any]],
    *,
    until_seq: int | None = None,
) -> dict[str, float]:
    """Latest ``composite_score_weights`` entry before ``until_seq`` wins.

    The entry is admin-emit only; we look at the execute payload's args.
    Missing keys fall back to the equal-weight default. Sum is normalized
    to 1.0 so a malformed entry can't tip the scalar out of [0, 1].
    """
    seen_weights: dict[str, float] | None = None
    for r in rows:
        if until_seq is not None and r.get("seq", 0) > until_seq:
            break
        if not _is_execute_with_tool(r, "emit_composite_score_weights"):
            continue
        args = r.get("payload", {}).get("args", {}) or {}
        w = {k: float(v) for k, v in args.items() if k in DEFAULT_WEIGHTS}
        if w:
            seen_weights = w
    weights = dict(DEFAULT_WEIGHTS)
    if seen_weights:
        weights.update(seen_weights)
    total = sum(weights.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in weights.items()}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def composite_score(
    tenant_id: str,
    rows: list[Mapping[str, Any]],
    *,
    ledger_height: int | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
) -> CompositeScore:
    """Evaluate the composite_score scalar at ``ledger_height``.

    ``rows`` must be the full ledger row stream for ``tenant_id``,
    sorted by seq ascending. ``ledger_height`` defaults to the highest
    seq observed in ``rows``. ``now`` defaults to the timestamp of the
    last row (or ``datetime.now(UTC)`` for an empty ledger), which
    keeps replays byte-stable.
    """
    if ledger_height is None:
        ledger_height = max((int(r.get("seq", 0)) for r in rows), default=0)
    in_scope = [r for r in rows if int(r.get("seq", 0)) <= ledger_height]
    if not in_scope:
        weights = _resolve_weights(rows, until_seq=ledger_height)
        # No ledger → emit neutral score so the curve renders empty-state.
        return CompositeScore(
            tenant_id=tenant_id,
            ledger_height=ledger_height,
            score=0.5,
            components={k: _NEUTRAL_RATIO for k in DEFAULT_WEIGHTS},
            weights=weights,
        )

    anchor_ts = now or _ts_of(in_scope[-1])
    cutoff = anchor_ts - timedelta(days=window_days)
    in_window = [r for r in in_scope if _ts_of(r) >= cutoff]

    components = {
        "gate_precision": _gate_fire_precision(in_window),
        "propose_keep_ratio": _propose_keep_ratio(in_window),
        "ramp_delta": _ramp_delta(in_window),
        "reactivity_confirm_rate": _reactivity_confirm_rate(in_window),
    }
    weights = _resolve_weights(rows, until_seq=ledger_height)
    score = sum(components[k] * weights[k] for k in components)
    # Clamp defensively — float drift can push slightly outside [0, 1].
    score = max(0.0, min(1.0, score))
    return CompositeScore(
        tenant_id=tenant_id,
        ledger_height=ledger_height,
        score=score,
        components=components,
        weights=weights,
    )


def composite_score_series(
    tenant_id: str,
    rows: list[Mapping[str, Any]],
    *,
    points: int = 9,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> CompositeScoreSeries:
    """Sample ``points`` composite_score values at uniform seq strides.

    The PRD requires ≥9 points so the install arc draws a clean curve.
    Strides are chosen so the first sample sits at the earliest seq
    where ≥1 row exists and the last sample sits at the highest seq.
    Identical inputs → identical outputs (deterministic).
    """
    if not rows:
        # Empty ledger: emit a single neutral point so the chart can
        # render an honest empty-state without crashing the renderer.
        zero = composite_score(tenant_id, rows, ledger_height=0, window_days=window_days)
        return CompositeScoreSeries(
            tenant_id=tenant_id,
            points=[
                CompositeScorePoint(
                    ledger_height=0,
                    ts=datetime.now(UTC).isoformat(),
                    score=zero.score,
                    components=zero.components,
                    top_contributor_reactivity_id="",
                    contributing_seq_lo=0,
                    contributing_seq_hi=0,
                )
            ],
            window_days=window_days,
            weights=zero.weights,
        )

    seqs = [int(r.get("seq", 0)) for r in rows]
    lo, hi = min(seqs), max(seqs)
    points = max(2, points)

    # Uniform stride from lo..hi inclusive. Integer-only to keep replays
    # byte-stable.
    if hi == lo:
        sampled = [hi]
    else:
        step = (hi - lo) / (points - 1)
        sampled = sorted({int(round(lo + i * step)) for i in range(points)})
        # Pad to ``points`` length if rounding collapsed adjacent strides.
        # Walk from hi backwards adding any unique seq until we hit ``points``.
        if len(sampled) < points:
            for s in range(hi, lo - 1, -1):
                if s not in sampled:
                    sampled.append(s)
                    if len(sampled) >= points:
                        break
            sampled = sorted(sampled)

    series_points: list[CompositeScorePoint] = []
    for height in sampled:
        cs = composite_score(
            tenant_id, rows, ledger_height=height, window_days=window_days,
        )
        # Recompute the in-window slice for top-contributor + range output.
        in_scope = [r for r in rows if int(r.get("seq", 0)) <= height]
        anchor_ts = _ts_of(in_scope[-1])
        cutoff = anchor_ts - timedelta(days=window_days)
        in_window = [r for r in in_scope if _ts_of(r) >= cutoff]
        contributing_seqs = [int(r.get("seq", 0)) for r in in_window]
        contrib_lo = min(contributing_seqs) if contributing_seqs else height
        contrib_hi = max(contributing_seqs) if contributing_seqs else height
        series_points.append(
            CompositeScorePoint(
                ledger_height=height,
                ts=anchor_ts.isoformat(),
                score=cs.score,
                components=cs.components,
                top_contributor_reactivity_id=_top_contributor_reactivity(
                    in_window,
                ),
                contributing_seq_lo=contrib_lo,
                contributing_seq_hi=contrib_hi,
            )
        )

    weights = _resolve_weights(rows, until_seq=hi)
    return CompositeScoreSeries(
        tenant_id=tenant_id,
        points=series_points,
        window_days=window_days,
        weights=weights,
    )
