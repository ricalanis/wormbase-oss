"""Step 5 — Karpathy autoresearch learn step (P9).

Wave C₁ Block C.1: verbatim lift from
``apps/worm-core/src/wormbase_core/autoresearch_learn.py`` into the
research-loop package. Module body unchanged; only the logger name moves
to ``wormbase_research_loop.learn``. The plan's helper-decomposition
(``extract_lesson`` / ``lookup_relevant_lessons`` / ``stamp_lesson_applied``)
is deferred to a follow-on block — same posture as B.1's lift of
``autoresearch_loop`` (verbatim now, refactor later).

When an ``experiment_resolved`` row with ``outcome="keep"`` lands, the harness
extracts a structured **lesson** describing what features (predicate,
condition, topic, scope) actually correlated with the keep — and writes it
back to the ledger as ``experiment_lesson``. The next ``experiment_proposed``
for the same scope reads recent lessons (trailing 7 days) and folds them
into its rationale string + feature weighting. The lesson's ``applied_at``
field is filled in (with the ledger height of the consuming proposer) the
first time it is read, closing the Karpathy loop empirically.

This module is the extraction half. The application half lives inline in
``autoresearch_loop._emit_proposed`` — see ``apply_pending_lessons`` below
which the loop calls before writing each propose entry.

PRD §7 P9 contract:

    payload = {
        "prior_keep_id": <experiment_resolved.entry_id>,
        "scope": "person" | "team" | "company",
        "lesson_text": str,                    # human-readable
        "lesson_features": dict[str, str],     # structured: predicates/conditions/topics
        "applied_to_proposer": str,            # which proposer module reads this
        "applied_at": int | None,              # ledger height; None until first applied
        "proposed_by": str,                    # CLAUDE.md invariant 7
        "extracted_at": datetime,
    }

Determinism (Triad C2): for the same kept experiment + same surrounding
ledger context, ``extract_lesson`` returns byte-identical lesson_text +
lesson_features. ``applied_at`` is the seq of the first ``experiment_proposed``
to consume the lesson — also stable under replay since the proposer reads
the ledger in deterministic order.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ledger.entries import ExperimentLessonPayload

logger = logging.getLogger("wormbase_research_loop.learn")


# ---------------------------------------------------------------------------
# Audience helpers (mirror autoresearch_loop._normalise_audience / _scope_of
# without creating a circular import).
# ---------------------------------------------------------------------------


def _audience_of_proposed(payload: dict[str, Any]) -> str | None:
    """Extract the audience marker from an ``emit_experiment_proposed`` payload."""
    args = payload.get("args") or {}
    audience = args.get("audience")
    if audience:
        return str(audience)
    fpid = args.get("for_person_id")
    if fpid:
        return f"person:{fpid}"
    return None


def _scope_of(audience: str | None) -> str:
    if audience is None:
        return "person"
    if audience == "company":
        return "company"
    if audience.startswith("team:"):
        return "team"
    return "person"


# ---------------------------------------------------------------------------
# Lesson extraction
# ---------------------------------------------------------------------------


def extract_lesson_features(
    *,
    experiment_id: str,
    proposed_args: dict[str, Any],
    resolved_args: dict[str, Any],
    run_args: dict[str, Any] | None,
    adjacent_discards: list[dict[str, Any]],
) -> tuple[str, dict[str, str]]:
    """Return ``(lesson_text, lesson_features)`` for a kept experiment.

    The extraction logic looks at the proposed_change shape, the headline
    metric, the observed_delta vs expected_delta gap, and the predicates of
    *adjacent* (same-position, same-metric) discarded experiments. The
    output names which features actually correlated with the keep — never
    just "score=0.8" (per the quality bar in the PRD §7 P9).

    ``adjacent_discards`` is a list of resolved-args dicts for nearby
    discarded experiments on the same metric (used to contrast: the kept
    candidate had X, the discarded ones had not-X).
    """
    metric = str(proposed_args.get("headline_metric") or "")
    position = str(proposed_args.get("position") or "")
    proposed_change = proposed_args.get("proposed_change") or {}
    if not isinstance(proposed_change, dict):
        proposed_change = {}
    change_kind = str(proposed_change.get("kind") or "")
    change_target = str(proposed_change.get("target") or "")
    change_predicate = str(proposed_change.get("change") or "")

    expected_delta = _to_float(proposed_args.get("expected_delta"), 0.0)
    observed_delta = _to_float(resolved_args.get("observed_delta"), 0.0)

    # Did the win exceed expectation, hit it, or under-deliver but still keep?
    delta_label: str
    if expected_delta == 0.0:
        delta_label = "uncalibrated_expectation"
    else:
        ratio = observed_delta / expected_delta if expected_delta else 0.0
        if ratio >= 1.0:
            delta_label = "exceeded_expectation"
        elif ratio >= 0.85:
            delta_label = "hit_expectation"
        else:
            delta_label = "under_expectation_kept"

    # Contrast against adjacent discards: what was different about the kept
    # candidate's predicate?
    discard_predicates = sorted(
        {
            str((d.get("proposed_change") or {}).get("change") or "")
            for d in adjacent_discards
            if d.get("proposed_change")
        }
    )
    # ``novel`` requires at least one adjacent discard to compare against.
    # Without any discards, novelty is undefined — we record ``false`` so
    # the proposer's heuristic "favour novel predicates" doesn't fire on
    # an evidence-free baseline.
    novel_predicate = bool(
        change_predicate
        and discard_predicates
        and change_predicate not in discard_predicates
    )

    # Structured features that the next proposer reweighs.
    features: dict[str, str] = {
        "metric": metric,
        "position": position,
        "change_kind": change_kind,
        "change_target": change_target,
        "change_predicate": change_predicate,
        "delta_label": delta_label,
        "observed_delta": f"{observed_delta:+.4f}",
        "expected_delta": f"{expected_delta:+.4f}",
        "adjacent_discard_count": str(len(adjacent_discards)),
        "predicate_was_novel_vs_discards": "true" if novel_predicate else "false",
    }
    if discard_predicates:
        # Truncated for byte-stability: at most the first 3 distinct
        # predicates, sorted, joined by ``|``.
        features["adjacent_discard_predicates"] = "|".join(discard_predicates[:3])

    # Human-readable text — captures *which* features correlated with the
    # keep, not "score=0.8". Quality bar per PRD §7 P9.
    if novel_predicate and discard_predicates:
        novelty_clause = (
            f" The predicate '{change_predicate}' was novel vs "
            f"{len(discard_predicates)} adjacent discards "
            f"({_summarise_list(discard_predicates)})."
        )
    elif discard_predicates:
        novelty_clause = (
            f" Adjacent discards on the same metric tried "
            f"{_summarise_list(discard_predicates)}; this keep used the "
            f"same predicate but with {delta_label}."
        )
    else:
        novelty_clause = " No adjacent discards on the same metric to contrast against."

    if delta_label == "exceeded_expectation":
        delta_clause = (
            f"observed {observed_delta:+.4f} vs expected {expected_delta:+.4f} "
            f"(exceeded)"
        )
    elif delta_label == "hit_expectation":
        delta_clause = (
            f"observed {observed_delta:+.4f} hit ≥85% of expected "
            f"{expected_delta:+.4f}"
        )
    elif delta_label == "under_expectation_kept":
        delta_clause = (
            f"observed {observed_delta:+.4f} under-delivered vs expected "
            f"{expected_delta:+.4f}, kept anyway"
        )
    else:
        delta_clause = (
            f"observed {observed_delta:+.4f}; expected delta uncalibrated"
        )

    text = (
        f"For position '{position}' moving '{metric}', a {change_kind} on "
        f"'{change_target}' with predicate '{change_predicate}' was kept: "
        f"{delta_clause}.{novelty_clause} "
        f"Reweight future proposals on this scope toward "
        f"({change_kind}, {change_target}) when targeting '{metric}'."
    )
    return text, features


def _summarise_list(items: list[str]) -> str:
    """Join a small list of strings for prose; bytestable across replay."""
    if not items:
        return "(none)"
    if len(items) <= 2:
        return ", ".join(repr(i) for i in items)
    head = ", ".join(repr(i) for i in items[:2])
    return f"{head}, … (+{len(items) - 2} more)"


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Ledger walking helpers
# ---------------------------------------------------------------------------


async def _fetch_rows(
    ledger: Ledger | InMemoryLedger, company_id: UUID
) -> list[dict[str, Any]]:
    return list(await ledger.fetch(company_id))


def _index_proposed(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map ``experiment_id -> emit_experiment_proposed args`` dict."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r["payload"]
        if payload.get("tool") != "emit_experiment_proposed":
            continue
        args = payload.get("args") or {}
        eid = args.get("experiment_id")
        if eid:
            out[str(eid)] = args
    return out


def _index_runs(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r["payload"]
        if payload.get("tool") != "emit_experiment_run":
            continue
        args = payload.get("args") or {}
        eid = args.get("experiment_id")
        if eid:
            out[str(eid)] = args
    return out


def _adjacent_discards(
    proposed_index: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
    *,
    metric: str,
    position: str,
    audience: str | None,
    keep_eid: str,
    lookback_days: int = 7,
    now: datetime,
) -> list[dict[str, Any]]:
    """Return resolved-args + proposed-args of discarded same-metric experiments.

    Returns a list of dicts with ``proposed_change``, ``observed_delta``, etc.
    suitable for ``extract_lesson_features``.
    """
    cutoff = now - timedelta(days=lookback_days)
    out: list[dict[str, Any]] = []
    target_scope = _scope_of(audience)
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r["payload"]
        if payload.get("tool") != "emit_experiment_resolved":
            continue
        args = payload.get("args") or {}
        if args.get("outcome") != "discard":
            continue
        eid = args.get("experiment_id")
        if not eid or eid == keep_eid:
            continue
        prop_args = proposed_index.get(str(eid))
        if not prop_args:
            continue
        if prop_args.get("headline_metric") != metric:
            continue
        if prop_args.get("position") != position:
            continue
        # Same scope only — cross-scope discards are not the right contrast.
        prop_audience = prop_args.get("audience")
        if not prop_audience and prop_args.get("for_person_id"):
            prop_audience = f"person:{prop_args['for_person_id']}"
        if _scope_of(prop_audience) != target_scope:
            continue
        ts = _coerce_ts(r.get("ts"))
        if ts is not None and ts < cutoff:
            continue
        out.append(
            {
                "experiment_id": str(eid),
                "proposed_change": prop_args.get("proposed_change") or {},
                "observed_delta": args.get("observed_delta"),
                "rationale": args.get("rationale"),
            }
        )
    # Stable ordering for replay determinism.
    out.sort(key=lambda d: d["experiment_id"])
    return out


def _coerce_ts(ts: Any) -> datetime | None:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    if isinstance(ts, str):
        try:
            v = datetime.fromisoformat(ts)
        except ValueError:
            return None
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    return None


# ---------------------------------------------------------------------------
# Public extraction entrypoint
# ---------------------------------------------------------------------------


async def extract_lesson(
    *,
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    prior_keep_id: UUID,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Extract one lesson for a single kept experiment, idempotently.

    The per-``prior_keep_id`` counterpart to ``extract_lessons_for_kept``.
    Wraps the same extraction logic but for a single target ``experiment_id``
    (the kept experiment's deterministic uuid5). Used by
    ``LessonExtractionReactivity`` (Block F.3) which fires on a specific
    ``experiment_resolved`` row and wants to materialise one lesson, not
    sweep the whole ledger.

    **Idempotency** lives here, not in the Reactivity: before writing a
    new ``emit_experiment_lesson`` row we walk the ledger for an existing
    one keyed by ``prior_keep_id`` and, if present, return ``None``. The
    spec's "returns None when no new lesson is warranted" path.

    Returns ``None`` when:
      * a lesson already exists for ``prior_keep_id`` (idempotency);
      * no kept ``experiment_resolved`` row matches the id (caller error);
      * no matching ``experiment_proposed`` row exists (unrecoverable —
        we can't reconstruct the change predicate / metric / position).

    Returns a dict carrying the lesson args (the
    ``ExperimentLessonPayload`` dump) when a new lesson is written. The
    return shape is intentionally just the payload dict — callers that
    want a typed object can validate via ``ExperimentLessonPayload``.
    """
    now = now or datetime.now(UTC)
    rows = await _fetch_rows(ledger, company_id)

    # Idempotency: dedup against existing lessons keyed by prior_keep_id.
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r["payload"]
        if payload.get("tool") != "emit_experiment_lesson":
            continue
        args = payload.get("args") or {}
        if str(args.get("prior_keep_id") or "") == str(prior_keep_id):
            return None

    # Locate the kept resolved row for this experiment_id.
    kept_resolved: dict[str, Any] | None = None
    for r in rows:
        if not _is_kept_resolved(r):
            continue
        args = (r["payload"].get("args") or {})
        if str(args.get("experiment_id") or "") == str(prior_keep_id):
            kept_resolved = r
            break
    if kept_resolved is None:
        logger.debug(
            "extract_lesson: no kept resolved row for prior_keep_id=%s; skip.",
            prior_keep_id,
        )
        return None

    proposed_index = _index_proposed(rows)
    prop_args = proposed_index.get(str(prior_keep_id))
    if not prop_args:
        logger.debug(
            "extract_lesson: no proposed row for prior_keep_id=%s; skip.",
            prior_keep_id,
        )
        return None

    audience = prop_args.get("audience")
    if not audience and prop_args.get("for_person_id"):
        audience = f"person:{prop_args['for_person_id']}"
    scope = _scope_of(audience)

    adjacents = _adjacent_discards(
        proposed_index,
        rows,
        metric=str(prop_args.get("headline_metric") or ""),
        position=str(prop_args.get("position") or ""),
        audience=audience,
        keep_eid=str(prior_keep_id),
        now=now,
    )

    resolved_args = kept_resolved["payload"].get("args") or {}
    text, features = extract_lesson_features(
        experiment_id=str(prior_keep_id),
        proposed_args=prop_args,
        resolved_args=resolved_args,
        run_args=None,
        adjacent_discards=adjacents,
    )
    extracted_at = _coerce_ts(kept_resolved.get("ts")) or now

    payload = ExperimentLessonPayload(
        prior_keep_id=prior_keep_id,
        scope=scope,
        lesson_text=text,
        lesson_features=features,
        applied_to_proposer="autoresearch_loop",
        applied_at=None,
        proposed_by="autoresearch_loop",
        extracted_at=extracted_at,
    )
    await _write_lesson(
        ledger,
        company_id,
        prior_keep_id=prior_keep_id,
        scope=scope,
        lesson_text=text,
        lesson_features=features,
        applied_to_proposer="autoresearch_loop",
        extracted_at=extracted_at,
    )
    return payload.model_dump(mode="json")


async def extract_lessons_for_kept(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    *,
    now: datetime | None = None,
) -> int:
    """Walk the ledger, extract one ``experiment_lesson`` per unseen kept experiment.

    Idempotent: a lesson is only written once per ``prior_keep_id``. Uses
    ``entry_id`` of the resolved row as the dedup key.

    Returns the count of new lessons written.
    """
    now = now or datetime.now(UTC)
    rows = await _fetch_rows(ledger, company_id)
    proposed_index = _index_proposed(rows)

    # Dedup key: which prior_keep_ids have already produced lessons?
    already: set[str] = set()
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r["payload"]
        if payload.get("tool") != "emit_experiment_lesson":
            continue
        args = payload.get("args") or {}
        prior = args.get("prior_keep_id")
        if prior:
            already.add(str(prior))

    written = 0
    # Walk resolved-keep rows in seq order so replay produces a stable
    # ordering of lessons.
    keep_rows = sorted(
        (r for r in rows if _is_kept_resolved(r)),
        key=lambda r: int(r.get("seq") or 0),
    )
    for r in keep_rows:
        try:
            payload = r["payload"]
            args = payload.get("args") or {}
            eid = args.get("experiment_id")
            if not eid:
                continue
            # ``prior_keep_id`` is the deterministic ``experiment_id`` (uuid5)
            # of the kept experiment — replay-stable, unlike the resolved
            # row's ``entry_id`` (uuid4 generated at write time).
            prior_keep_id = str(eid)
            if prior_keep_id in already:
                continue
            prop_args = proposed_index.get(str(eid))
            if not prop_args:
                continue
            audience = prop_args.get("audience")
            if not audience and prop_args.get("for_person_id"):
                audience = f"person:{prop_args['for_person_id']}"
            scope = _scope_of(audience)
            adjacents = _adjacent_discards(
                proposed_index,
                rows,
                metric=str(prop_args.get("headline_metric") or ""),
                position=str(prop_args.get("position") or ""),
                audience=audience,
                keep_eid=str(eid),
                now=now,
            )
            text, features = extract_lesson_features(
                experiment_id=str(eid),
                proposed_args=prop_args,
                resolved_args=args,
                run_args=None,
                adjacent_discards=adjacents,
            )
            extracted_at = _coerce_ts(r.get("ts")) or now
            await _write_lesson(
                ledger,
                company_id,
                prior_keep_id=UUID(prior_keep_id),
                scope=scope,
                lesson_text=text,
                lesson_features=features,
                applied_to_proposer="autoresearch_loop",
                extracted_at=extracted_at,
            )
            already.add(prior_keep_id)
            written += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "extract_lessons_for_kept: failed for entry %s: %s",
                r.get("entry_id"), exc,
            )
    return written


def _is_kept_resolved(r: dict[str, Any]) -> bool:
    if r["kind"] != "execute":
        return False
    payload = r["payload"]
    if payload.get("tool") != "emit_experiment_resolved":
        return False
    args = payload.get("args") or {}
    return args.get("outcome") == "keep"


async def _write_lesson(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    *,
    prior_keep_id: UUID,
    scope: str,
    lesson_text: str,
    lesson_features: dict[str, str],
    applied_to_proposer: str,
    extracted_at: datetime,
) -> None:
    payload = ExperimentLessonPayload(
        prior_keep_id=prior_keep_id,
        scope=scope,
        lesson_text=lesson_text,
        lesson_features=lesson_features,
        applied_to_proposer=applied_to_proposer,
        applied_at=None,  # filled by the proposer when first read
        proposed_by="autoresearch_loop",
        extracted_at=extracted_at,
    )
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "experiment_lesson",
            "ref_id": str(prior_keep_id),
            "reason": f"learn-step extraction for kept experiment ({scope})",
            "proposed_by": "autoresearch_loop",
        },
        execute_fn=lambda: {
            "tool": "emit_experiment_lesson",
            "args": payload.model_dump(mode="json"),
            "result_ref": str(prior_keep_id),
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "payload_valid", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "experiment_lesson persisted",
        },
        quadrant="active_deterministic",
        timestamp=extracted_at,
    )


# ---------------------------------------------------------------------------
# Lesson reading (for the propose path) + applied_at materialisation
# ---------------------------------------------------------------------------


async def recent_lessons_for_scope(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    *,
    scope: str,
    now: datetime,
    lookback_days: int = 7,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return the most recent ``experiment_lesson`` entries for a scope.

    Trailing 7 days, newest-first, up to ``limit``. Each item carries the
    ``args`` dict + ``seq`` + ``entry_id`` so callers can both read content
    and back-write ``applied_at`` later.

    **Per-prior dedup:** the ledger is append-only, so each
    ``applied_at``-stamp materialises as a new ``experiment_lesson`` row
    with the same ``prior_keep_id``. We take only the latest row per
    ``prior_keep_id`` (highest seq wins) so the read view reflects the
    canonical post-application state. Without this, the stamp loop would
    re-stamp every cycle (the un-stamped extraction row never disappears).
    """
    cutoff = now - timedelta(days=lookback_days)
    rows = await _fetch_rows(ledger, company_id)
    candidates: list[dict[str, Any]] = []
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r["payload"]
        if payload.get("tool") != "emit_experiment_lesson":
            continue
        args = payload.get("args") or {}
        if args.get("scope") != scope:
            continue
        ts = _coerce_ts(r.get("ts"))
        if ts is not None and ts < cutoff:
            continue
        candidates.append({
            "entry_id": r.get("entry_id"),
            "seq": int(r.get("seq") or 0),
            "ts": ts,
            "args": args,
        })
    # Latest per prior_keep_id wins.
    by_prior: dict[str, dict[str, Any]] = {}
    for c in candidates:
        prior = str(c["args"].get("prior_keep_id") or "")
        cur = by_prior.get(prior)
        if cur is None or c["seq"] > cur["seq"]:
            by_prior[prior] = c
    out = list(by_prior.values())
    # Newest first by seq (stable, replay-deterministic).
    out.sort(key=lambda d: d["seq"], reverse=True)
    return out[:limit]


async def mark_lessons_applied(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    *,
    lessons: list[dict[str, Any]],
    applied_at_seq: int,
    now: datetime,
) -> int:
    """Stamp ``applied_at = applied_at_seq`` on lessons that are still None.

    Writes a fresh ``experiment_lesson`` row carrying the same content but
    with ``applied_at`` populated. We do not mutate prior entries — the
    ledger is append-only — so the projection layer must read the lesson
    set as "the latest entry per ``prior_keep_id`` wins."

    Returns count of stamps written.
    """
    written = 0
    for L in lessons:
        args = L.get("args") or {}
        if args.get("applied_at") is not None:
            continue
        try:
            payload = ExperimentLessonPayload(
                prior_keep_id=UUID(str(args["prior_keep_id"])),
                scope=str(args["scope"]),
                lesson_text=str(args["lesson_text"]),
                lesson_features={
                    str(k): str(v) for k, v in (args.get("lesson_features") or {}).items()
                },
                applied_to_proposer=str(args["applied_to_proposer"]),
                applied_at=int(applied_at_seq),
                proposed_by=str(args.get("proposed_by") or "autoresearch_loop"),
                extracted_at=_coerce_ts(args.get("extracted_at")) or now,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("mark_lessons_applied: skip malformed lesson: %s", exc)
            continue
        await ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "experiment_lesson",
                "ref_id": str(payload.prior_keep_id),
                "reason": (
                    f"applied_at update for prior_keep {payload.prior_keep_id} "
                    f"(seq={applied_at_seq})"
                ),
                "proposed_by": "autoresearch_loop",
            },
            execute_fn=lambda p=payload: {
                "tool": "emit_experiment_lesson",
                "args": p.model_dump(mode="json"),
                "result_ref": str(p.prior_keep_id),
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "payload_valid", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "applied_at stamped",
            },
            quadrant="active_deterministic",
            timestamp=now,
        )
        written += 1
    return written


def render_lesson_for_rationale(lesson_args: dict[str, Any]) -> str:
    """Compact one-line render of a lesson, suitable for a propose rationale.

    The proposer concatenates these into the rationale string so the
    rendered experiment carries visible attribution to the prior keeps that
    informed it (Triad C5 + invariant 7).
    """
    metric = (lesson_args.get("lesson_features") or {}).get("metric") or "?"
    kind = (lesson_args.get("lesson_features") or {}).get("change_kind") or "?"
    target = (lesson_args.get("lesson_features") or {}).get("change_target") or "?"
    predicate = (lesson_args.get("lesson_features") or {}).get("change_predicate") or "?"
    return (
        f"prior keep on '{metric}': ({kind}, {target}, {predicate})"
    )


__all__ = [
    "extract_lesson",
    "extract_lesson_features",
    "extract_lessons_for_kept",
    "mark_lessons_applied",
    "recent_lessons_for_scope",
    "render_lesson_for_rationale",
]
