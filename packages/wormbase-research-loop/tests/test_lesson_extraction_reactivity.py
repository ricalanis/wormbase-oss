"""Tests for ``LessonExtractionReactivity`` (Block F.3, Wave C₁).

Third Reactivity in Block F. Predicate is ``ResolvedKept()`` (matches
``experiment_resolved`` execute envelopes whose payload args carry
``outcome="keep"``); condition is ``NotRecentlyFired(seconds=60)``
belt-and-braces; fire calls ``extract_lesson`` (the per-prior_keep_id
helper added to ``learn.py`` alongside the existing bulk
``extract_lessons_for_kept``) and writes at most one
``emit_experiment_lesson`` row per ``experiment_resolved`` row.

Closes the Karpathy autoresearch loop on itself: kept experiments →
lessons → applied to the next proposer's rationale (the application
half is already wired in ``loop._emit_proposed`` via
``recent_lessons_for_scope``).

Idempotency lives inside ``extract_lesson`` (ledger-side dedup keyed by
``prior_keep_id``), so two consecutive fires on the same
``experiment_resolved`` row produce exactly one ``experiment_lesson``
row.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.protocol import (
    Reactivity,
    ReactivityContext,
    ReactivityResult,
)
from wormbase_research_loop.learn import extract_lesson
from wormbase_research_loop.loop import (
    _EXPERIMENT_NAMESPACE,
    AutoresearchLoop,
    PersonPosition,
)
from wormbase_research_loop.reactivities import LessonExtractionReactivity

CAROL = UUID("00000000-0000-0000-0000-0000000000c1")
DAVE = UUID("00000000-0000-0000-0000-0000000000c2")
NOW = datetime(2026, 5, 3, 10, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_person(
    ledger: InMemoryLedger,
    company_id: UUID,
    person_id: UUID,
    name: str,
    position: str,
) -> None:
    """Seed emit_person_registered + emit_position_assigned for a person."""
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "person_registered",
            "ref_id": str(person_id),
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_person_registered",
            "args": {
                "person_id": str(person_id),
                "name": name,
                "email": f"{name.lower()}@example.com",
                "role": "admin",
                "registered_at": NOW.isoformat(),
            },
            "result_ref": str(person_id),
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "position_assigned",
            "ref_id": str(person_id),
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_position_assigned",
            "args": {
                "person_id": str(person_id),
                "position": position,
                "at": NOW.isoformat(),
            },
            "result_ref": str(person_id),
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )


async def _force_keep_run(
    ledger: InMemoryLedger,
    company_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
    *,
    person_id: UUID,
    position_id: str,
    seed_extra: str = "",
    now: datetime = NOW,
) -> tuple[UUID, dict[str, Any]]:
    """Drive the loop body to write propose + run + resolved-keep rows.

    Forces the resolver to return ``keep`` so the ledger ends up with an
    ``experiment_resolved`` row whose ``outcome="keep"`` — the predicate
    target for ``LessonExtractionReactivity``.

    Returns ``(experiment_id, resolved_entry)`` so a test can fire the
    Reactivity against the resolved row exactly as the runner would.
    """
    from wormbase_identity_tracker.positions import (
        get_position,
        position_candidates,
    )
    from wormbase_research_loop import loop as loop_module

    def _force_keep(experiment_id, candidate):
        return ("keep", "forced keep for test", float(candidate.expected_delta) * 0.9)

    monkeypatch.setattr(
        loop_module.AutoresearchLoop, "_resolve", staticmethod(_force_keep),
    )

    pp = PersonPosition(person_id=person_id, position_id=position_id)
    candidates = position_candidates(position_id)
    assert candidates, f"position {position_id} has no candidates"
    position = get_position(position_id)
    assert position is not None
    candidate = candidates[0]
    experiment_id = uuid5(
        _EXPERIMENT_NAMESPACE,
        f"lesson-test:{person_id}:{position_id}:{candidate.candidate_id}:{seed_extra}",
    )

    helper = AutoresearchLoop(ledger=ledger, company_id=company_id)
    await helper._emit_proposed(
        pp, candidate, experiment_id, now=now, audience=f"person:{person_id}",
    )
    finished_at = now + timedelta(seconds=60)
    await helper._emit_run(pp, candidate, experiment_id, now, finished_at)
    outcome, rationale, observed_delta = AutoresearchLoop._resolve(
        experiment_id, candidate,
    )
    await helper._emit_resolved(
        experiment_id,
        outcome=outcome,
        observed_delta=observed_delta,
        rationale=rationale,
        now=finished_at,
    )

    rows = await ledger.fetch(company_id)
    resolved_entry = next(
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_experiment_resolved"
        and (r["payload"].get("args") or {}).get("experiment_id")
        == str(experiment_id)
    )
    return experiment_id, resolved_entry


def _ctx(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    now: datetime = NOW,
) -> ReactivityContext:
    return ReactivityContext(
        ledger=ledger,
        company_id=company_id,
        registry=None,
        now=lambda: now,
        extras={"reactivity_id": "lesson_extraction"},
    )


def _entry(
    kind: str, *, args: dict[str, Any] | None = None, ts: datetime | None = None,
) -> dict[str, Any]:
    return {
        "kind": "execute",
        "payload": {
            "tool": f"emit_{kind}",
            "args": args or {},
        },
        "ts": ts or NOW,
        "seq": 1,
    }


async def _lesson_rows(
    ledger: InMemoryLedger, company_id: UUID, prior_keep_id: UUID,
) -> list[dict[str, Any]]:
    rows = await ledger.fetch(company_id)
    return [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_experiment_lesson"
        and str((r["payload"].get("args") or {}).get("prior_keep_id") or "")
        == str(prior_keep_id)
    ]


# ---------------------------------------------------------------------------
# Protocol satisfaction
# ---------------------------------------------------------------------------


async def test_satisfies_reactivity_protocol():
    r = LessonExtractionReactivity()
    assert isinstance(r, Reactivity)
    assert r.id == "lesson_extraction"


# ---------------------------------------------------------------------------
# Predicate — matches kept experiment_resolved only
# ---------------------------------------------------------------------------


async def test_predicate_matches_kept_resolved(ledger, company_id):
    r = LessonExtractionReactivity()
    ctx = _ctx(ledger, company_id)
    entry = _entry("experiment_resolved", args={"outcome": "keep"})
    assert await r.predicate.match(entry, ctx) is True


async def test_predicate_rejects_discarded_resolved(ledger, company_id):
    r = LessonExtractionReactivity()
    ctx = _ctx(ledger, company_id)
    entry = _entry("experiment_resolved", args={"outcome": "discard"})
    assert await r.predicate.match(entry, ctx) is False


@pytest.mark.parametrize(
    "kind",
    [
        "experiment_proposed",
        "experiment_run",
        "experiment_lesson",
        "phenomenon_gap_detected",
        "metric_observed",
        "chat_received",
        "person_proposed",
    ],
)
async def test_predicate_rejects_other_kinds(ledger, company_id, kind):
    r = LessonExtractionReactivity()
    ctx = _ctx(ledger, company_id)
    entry = _entry(kind, args={"outcome": "keep"})  # outcome irrelevant for non-resolved
    assert await r.predicate.match(entry, ctx) is False, (
        f"expected miss for {kind}"
    )


# ---------------------------------------------------------------------------
# Fire — writes one experiment_lesson row per kept resolved row
# ---------------------------------------------------------------------------


async def test_fire_writes_one_lesson_row(ledger, company_id, monkeypatch):
    """End-to-end fire: ledger gains exactly one experiment_lesson row."""
    await _seed_person(ledger, company_id, CAROL, "Carol", "cfo")
    experiment_id, resolved_entry = await _force_keep_run(
        ledger, company_id, monkeypatch,
        person_id=CAROL, position_id="cfo",
    )

    r = LessonExtractionReactivity()
    ctx = _ctx(ledger, company_id, now=NOW + timedelta(seconds=120))
    result = await r.fire(resolved_entry, ctx)

    assert isinstance(result, ReactivityResult)
    assert result.fired is True

    lessons = await _lesson_rows(ledger, company_id, experiment_id)
    assert len(lessons) == 1, "exactly one lesson per kept experiment"

    args = lessons[0]["payload"]["args"]
    assert str(args["prior_keep_id"]) == str(experiment_id)
    assert args["scope"] == "person"
    assert args["applied_to_proposer"] == "autoresearch_loop"
    assert args["applied_at"] is None  # not yet consumed by a proposer


async def test_two_fires_same_resolved_produce_one_lesson(
    ledger, company_id, monkeypatch,
):
    """The acceptance-bullet test: two consecutive fires on the same
    ``experiment_resolved`` entry produce exactly one ``experiment_lesson``
    row — idempotency lives inside ``extract_lesson`` via the
    prior_keep_id dedup.
    """
    await _seed_person(ledger, company_id, CAROL, "Carol", "cfo")
    experiment_id, resolved_entry = await _force_keep_run(
        ledger, company_id, monkeypatch,
        person_id=CAROL, position_id="cfo",
        seed_extra="idem",
    )

    r = LessonExtractionReactivity()
    ctx = _ctx(ledger, company_id, now=NOW + timedelta(seconds=120))

    res1 = await r.fire(resolved_entry, ctx)
    res2 = await r.fire(resolved_entry, ctx)

    assert res1.fired is True
    # Second fire returns fired=False (no new lesson written) — the
    # extract_lesson helper saw the existing row and short-circuited.
    assert res2.fired is False

    lessons = await _lesson_rows(ledger, company_id, experiment_id)
    assert len(lessons) == 1, (
        "ledger-side dedup must keep exactly one lesson row across two "
        "fires of the same experiment_resolved entry"
    )


async def test_fire_skips_when_resolved_payload_missing_experiment_id(
    ledger, company_id,
):
    """A malformed ``experiment_resolved`` row (no experiment_id) is a skip."""
    r = LessonExtractionReactivity()
    ctx = _ctx(ledger, company_id)
    entry = _entry("experiment_resolved", args={"outcome": "keep"})
    pre_rows = await ledger.fetch(company_id)
    pre_count = len(pre_rows)

    result = await r.fire(entry, ctx)
    assert result.fired is False

    post_rows = await ledger.fetch(company_id)
    assert len(post_rows) == pre_count


async def test_fire_skips_when_no_matching_proposed_row(
    ledger, company_id,
):
    """A kept ``experiment_resolved`` pointing at an unknown experiment_id is skipped.

    Lesson extraction needs the proposed row to read the change predicate /
    metric / position. Without it the Reactivity emits nothing.
    """
    r = LessonExtractionReactivity()
    ctx = _ctx(ledger, company_id)
    eid = uuid5(_EXPERIMENT_NAMESPACE, "unknown-exp-for-lesson")
    entry = _entry(
        "experiment_resolved",
        args={
            "experiment_id": str(eid),
            "outcome": "keep",
            "observed_delta": 0.04,
            "rationale": "mock",
        },
    )
    pre_rows = await ledger.fetch(company_id)
    pre_count = len(pre_rows)

    result = await r.fire(entry, ctx)
    assert result.fired is False

    post_rows = await ledger.fetch(company_id)
    assert len(post_rows) == pre_count


# ---------------------------------------------------------------------------
# Helper-level idempotency — extract_lesson is the source of truth
# ---------------------------------------------------------------------------


async def test_extract_lesson_module_helper_idempotency(
    ledger, company_id, monkeypatch,
):
    """The dedup lives in ``extract_lesson``, not in the Reactivity.

    Calling the module helper directly twice for the same prior_keep_id
    writes exactly one lesson row.
    """
    await _seed_person(ledger, company_id, CAROL, "Carol", "cfo")
    experiment_id, _resolved_entry = await _force_keep_run(
        ledger, company_id, monkeypatch,
        person_id=CAROL, position_id="cfo",
        seed_extra="helper-idem",
    )

    res1 = await extract_lesson(
        ledger=ledger, company_id=company_id,
        prior_keep_id=experiment_id,
        now=NOW + timedelta(seconds=120),
    )
    res2 = await extract_lesson(
        ledger=ledger, company_id=company_id,
        prior_keep_id=experiment_id,
        now=NOW + timedelta(seconds=180),
    )

    assert res1 is not None
    # Second call returns None because the lesson already exists for this
    # prior_keep_id — the spec's "returns None when no new lesson is
    # warranted" path.
    assert res2 is None

    lessons = await _lesson_rows(ledger, company_id, experiment_id)
    assert len(lessons) == 1
