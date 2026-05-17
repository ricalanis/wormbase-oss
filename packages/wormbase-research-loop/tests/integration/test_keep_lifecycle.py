"""End-to-end: kept ``experiment_resolved`` -> lesson + per-day keep_rate publish.

Task I.2 of the research-worm extraction plan
(docs/superpowers/plans/2026-05-03-research-worm-extraction.md, lines 1155-1213).

The second integration test for the W5b -> research-worm composition,
companion to I.1's ``test_gap_to_cycle.py``. Where I.1 proves the
*upstream* edge (gap -> trigger -> PEVR) lands purely through the ledger,
this file proves the *downstream* edges land the same way:

  * **Body 1 (lesson extraction)** — a kept ``emit_experiment_resolved``
    row drives ``LessonExtractionReactivity`` (predicate ``ResolvedKept``)
    to write exactly one ``emit_experiment_lesson``. Ledger-side dedup
    (keyed by ``prior_keep_id``) keeps the lesson count at one even
    across re-fires of the same entry. A second resolved with a
    *different* experiment_id produces a *new* lesson — different
    ``prior_keep_id`` ⇒ different novelty_key ⇒ allowed.

  * **Body 2 (keep_rate publish)** — multiple ``emit_experiment_resolved``
    rows landing throughout a UTC day drive ``KeepRatePublishReactivity``
    (Periodic(86_400) ∧ NotRecentlyFired(24h)) to fire **at most once
    per day per install**. Three scopes (person/team/company) means three
    ``emit_metrics_keep_rate_published`` rows per fire — the scope fan-out
    happens inside the publisher. The Periodic gate is the at-most-once-
    per-day enforcer; the NotRecentlyFired gate is the in-memory
    belt-and-braces.

Note on entry kinds: the spec line "exactly one ``metric_observed`` entry
with ``metric_name='composite_score'``" is the spec author's mental model
of what the publisher emits. The actual entry kind written by
``KeepRatePublisher.publish_for_day`` (lifted from the pre-Wave-C₁
``keep_rate_publisher`` module) is ``emit_metrics_keep_rate_published``
with payload keys {scope, day, kept, total, ratio, published_by,
published_at} — see ``src/wormbase_research_loop/keep_rate.py``. The
test asserts on the actual emitted kind. The spec's intent — that
``KeepRatePublishReactivity`` fires **exactly once per simulated day** —
is preserved by counting per-day fires of ``emit_metrics_keep_rate_published``
across the simulated 24h window.

Stepping model: identical to I.1 — we drive ``registry.dispatch``
directly inside a controlled "new entries since cursor" loop rather than
constructing a ``ReactivityRunner``. The runner's cursor advances past
mid-cycle writes (see runner.py:175-194), which would mask the cascade
we want to exercise. The dispatch path is byte-identical to the
runner's; only the cursor-management policy differs.

References:
  * ``tests/integration/test_gap_to_cycle.py`` — I.1, the upstream edge
    of the same composition.
  * ``tests/test_lesson_extraction_reactivity.py`` — the lesson
    Reactivity's unit tests; this file is its end-to-end counterpart.
  * ``tests/test_keep_rate_publish_reactivity.py`` — the keep_rate
    Reactivity's unit tests; this file exercises the per-day cadence
    against a real ledger + registry rather than a stub context.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

import pytest

from wormbase_chat_presence import Install

from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.registry import ReactivityRegistry
from wormbase_research_loop import wire_research_for_install
from wormbase_research_loop.loop import (
    _EXPERIMENT_NAMESPACE,
    AutoresearchLoop,
    PersonPosition,
)


# Stable identifiers so the run is hash-stable across replays.
COMPANY = UUID("00000000-0000-0000-0000-00000000ca0e")
CAROL = UUID("00000000-0000-0000-0000-0000000000c1")
NOW = datetime(2026, 5, 3, 0, 0, 0, tzinfo=UTC)  # start-of-day UTC


# ---------------------------------------------------------------------------
# Helpers (no direct calls to research-loop helpers; ledger seed only,
# except for the `_emit_proposed`/`_emit_run`/`_emit_resolved` triple
# which is the canonical way to write a complete PEVR cycle that the
# downstream Reactivities can consume — same pattern as
# test_lesson_extraction_reactivity.py's _force_keep_run).
# ---------------------------------------------------------------------------


async def _seed_person(
    ledger: InMemoryLedger,
    company_id: UUID,
    person_id: UUID,
    name: str,
    position: str,
    *,
    at: datetime = NOW,
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
                "registered_at": at.isoformat(),
            },
            "result_ref": str(person_id),
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
        timestamp=at,
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
                "at": at.isoformat(),
            },
            "result_ref": str(person_id),
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
        timestamp=at,
    )


async def _force_keep_resolution(
    ledger: InMemoryLedger,
    company_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
    *,
    person_id: UUID,
    position_id: str,
    seed_extra: str,
    at: datetime = NOW,
) -> tuple[UUID, dict[str, Any]]:
    """Drive the loop body to write a propose+run+resolved-keep triple.

    Forces the resolver to return ``keep`` so the resulting
    ``emit_experiment_resolved`` row matches the ``ResolvedKept``
    predicate that ``LessonExtractionReactivity`` listens on. Returns
    ``(experiment_id, resolved_entry)``.

    Mirrors the helper in ``tests/test_lesson_extraction_reactivity.py``
    so the wire path is identical to the unit-level coverage.
    """
    from wormbase_identity_tracker.positions import (
        get_position,
        position_candidates,
    )
    from wormbase_research_loop import loop as loop_module

    def _force_keep(experiment_id, candidate):
        # Deterministic — observed_delta scales from candidate so two
        # different candidates produce different deltas, but the SAME
        # candidate replays byte-identically.
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
        f"keep-lifecycle:{person_id}:{position_id}:{candidate.candidate_id}:{seed_extra}",
    )

    helper = AutoresearchLoop(ledger=ledger, company_id=company_id)
    await helper._emit_proposed(
        pp, candidate, experiment_id, now=at, audience=f"person:{person_id}",
    )
    finished_at = at + timedelta(seconds=60)
    await helper._emit_run(pp, candidate, experiment_id, at, finished_at)
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


async def _step_dispatch_new_entries(
    ledger: InMemoryLedger,
    registry: ReactivityRegistry,
    company_id: UUID,
    cursor: int,
) -> tuple[int, list[str]]:
    """Dispatch every entry with seq > cursor through the registry.

    Identical to I.1's helper: returns ``(new_cursor, fired_ids)``. The
    new cursor is the max seq seen BEFORE dispatch — so the next call
    processes both the cascade (entries written by fire bodies) and
    further upstream events.
    """
    rows = await ledger.fetch(company_id)
    rows_sorted = sorted(rows, key=lambda r: int(r.get("seq", 0)))
    pre_cycle_max = (
        int(rows_sorted[-1].get("seq", 0)) if rows_sorted else cursor
    )
    fired: list[str] = []
    for r in rows_sorted:
        seq = int(r.get("seq", 0))
        if seq <= cursor:
            continue
        if seq > pre_cycle_max:
            continue
        fired_ids = await registry.dispatch(r)
        fired.extend(fired_ids)
    return pre_cycle_max, fired


def _execute_rows(
    rows: list[dict[str, Any]], tool: str,
) -> list[dict[str, Any]]:
    """Filter execute envelopes whose payload.tool matches exactly."""
    out: list[dict[str, Any]] = []
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") == tool:
            out.append(r)
    return out


def _lesson_rows_for(
    rows: list[dict[str, Any]], prior_keep_id: UUID,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in _execute_rows(rows, "emit_experiment_lesson"):
        args = (r.get("payload") or {}).get("args") or {}
        if str(args.get("prior_keep_id") or "") == str(prior_keep_id):
            out.append(r)
    return out


def _original_lesson_rows_for(
    rows: list[dict[str, Any]], prior_keep_id: UUID,
) -> list[dict[str, Any]]:
    """Lessons for ``prior_keep_id`` that are EXTRACTIONS (applied_at is None).

    The ledger is append-only, so a single extracted lesson can have
    follow-up rows with ``applied_at`` populated (one per proposer that
    consumed it — see ``mark_lessons_applied`` in learn.py). Those
    follow-ups are NOT duplicates; they're the projection's "lesson was
    used at seq=X" stamps. ``extract_lesson``'s prior_keep_id dedup
    only governs the original extraction (``applied_at=None``); the
    invariant we want is "one original extraction per prior_keep_id".
    """
    return [
        r for r in _lesson_rows_for(rows, prior_keep_id)
        if (r.get("payload") or {}).get("args", {}).get("applied_at") is None
    ]


async def _build_wired_registry(
    ledger: InMemoryLedger,
    state: dict[str, Any],
    *,
    per_scope_daily_budget: int = 10,
) -> ReactivityRegistry:
    """Construct a ReactivityRegistry with the four research-loop Reactivities.

    The registry's clock reads from ``state["now"]`` so tests can fast-
    forward by mutating the state dict in-place. Production wiring
    (``wire_research_for_install``) is the single point of construction —
    same lifecycle hook the worm-core boot path uses.
    """

    def _now() -> datetime:
        return state["now"]

    registry = ReactivityRegistry(
        ledger=ledger, company_id=COMPANY, now=_now,
    )
    install = Install(id=COMPANY, platform="slack")
    await wire_research_for_install(
        install=install,
        ledger=ledger,
        reactivity_registry=registry,
        per_scope_daily_budget=per_scope_daily_budget,
    )
    return registry


# ---------------------------------------------------------------------------
# Body 1 — kept resolved -> exactly one experiment_lesson; idempotent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_kept_resolved_drives_lesson_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A kept ``experiment_resolved`` triggers ``LessonExtractionReactivity``.

    Asserts:
      * After the first kept resolved is dispatched, exactly one
        ``emit_experiment_lesson`` row exists for that prior_keep_id.
      * After a SECOND kept resolved (different experiment_id, same
        person/scope) is dispatched, exactly one *additional* lesson
        lands — novelty_key differs because prior_keep_id differs.
      * Re-dispatching the FIRST resolved row produces no new lesson —
        ledger-side dedup inside ``extract_lesson`` short-circuits.
    """
    ledger = InMemoryLedger()
    state = {"now": NOW}

    # Wire production-style. per_scope_daily_budget=10 keeps the
    # ExperimentTriggerReactivity's in-fire budget out of the way; we
    # don't want the trigger Reactivity firing on the resolved rows
    # we seed (it would write more cycles and pollute the assertion).
    registry = await _build_wired_registry(ledger, state)

    # Seed the Person + Position so any cascade (e.g. trigger Reactivity
    # firing on the cascade-resolved row) at least has somebody to drive
    # against — without this, _collect_person_positions returns empty.
    await _seed_person(ledger, COMPANY, CAROL, "Carol", "cfo")

    # 1. Force-keep resolution #1 — writes propose+run+resolved-keep.
    experiment_id_1, resolved_1 = await _force_keep_resolution(
        ledger, COMPANY, monkeypatch,
        person_id=CAROL, position_id="cfo",
        seed_extra="lesson-1",
    )

    # 2. Step the registry. The kept resolved row trips
    # LessonExtractionReactivity; extract_lesson writes one lesson.
    cursor, fired_step1 = await _step_dispatch_new_entries(
        ledger, registry, COMPANY, cursor=0,
    )
    assert "lesson_extraction" in fired_step1, (
        f"expected LessonExtractionReactivity to fire on the first kept "
        f"resolved row; got fired_ids={fired_step1!r}"
    )

    # 3. Assert exactly one ORIGINAL lesson for prior_keep_id=experiment_id_1.
    # (The ledger is append-only — follow-up rows with `applied_at`
    # populated are projection stamps, not duplicate extractions; see
    # _original_lesson_rows_for's docstring.)
    rows = await ledger.fetch(COMPANY)
    originals_1 = _original_lesson_rows_for(rows, experiment_id_1)
    assert len(originals_1) == 1, (
        f"expected exactly one extracted lesson (applied_at=None) for "
        f"prior_keep_id={experiment_id_1}; got {len(originals_1)}"
    )
    args_1 = originals_1[0]["payload"]["args"]
    assert str(args_1["prior_keep_id"]) == str(experiment_id_1)
    assert args_1["scope"] == "person"
    assert args_1["applied_at"] is None  # the original extraction

    # 4. Force-keep resolution #2 — different experiment_id (different
    # seed), same person/scope. Different prior_keep_id ⇒ different
    # novelty_key ⇒ a new lesson IS allowed.
    experiment_id_2, _resolved_2 = await _force_keep_resolution(
        ledger, COMPANY, monkeypatch,
        person_id=CAROL, position_id="cfo",
        seed_extra="lesson-2",
        at=NOW + timedelta(minutes=5),
    )

    # 5. Step the registry again. The new kept resolved row trips
    # LessonExtractionReactivity again, this time keyed by experiment_id_2.
    _cursor2, fired_step2 = await _step_dispatch_new_entries(
        ledger, registry, COMPANY, cursor=cursor,
    )
    assert "lesson_extraction" in fired_step2, (
        f"expected LessonExtractionReactivity to fire on the second kept "
        f"resolved row (different prior_keep_id ⇒ new novelty_key); "
        f"got fired_ids={fired_step2!r}"
    )

    rows_after_2 = await ledger.fetch(COMPANY)
    originals_2 = _original_lesson_rows_for(rows_after_2, experiment_id_2)
    assert len(originals_2) == 1, (
        f"expected exactly one extracted lesson (applied_at=None) for "
        f"prior_keep_id={experiment_id_2}; got {len(originals_2)}"
    )

    # The first lesson's *extraction* is unchanged — exactly one
    # applied_at=None row per prior_keep_id, regardless of how many
    # follow-up applied_at stamps the cascade may add.
    originals_1_after_step2 = _original_lesson_rows_for(
        rows_after_2, experiment_id_1,
    )
    assert len(originals_1_after_step2) == 1, (
        "the first lesson's extraction must still be exactly one row "
        "after step 2 — different prior_keep_ids must not collide on dedup"
    )

    # 6. Idempotency of the *helper* — re-dispatch the FIRST resolved row.
    # extract_lesson sees the existing lesson keyed by prior_keep_id and
    # short-circuits; no new EXTRACTION (applied_at=None) row lands. The
    # follow-up applied_at-stamped rows from the trigger Reactivity's
    # cascade aren't part of the dedup — they're projection bookkeeping.
    pre_redispatch_originals = len(
        _original_lesson_rows_for(rows_after_2, experiment_id_1)
        + _original_lesson_rows_for(rows_after_2, experiment_id_2)
    )
    # Capture every original-extraction count across all prior_keep_ids
    # so a cascade-spawned third experiment_id doesn't perturb the count.
    pre_redispatch_all_originals = [
        r for r in _execute_rows(rows_after_2, "emit_experiment_lesson")
        if (r.get("payload") or {}).get("args", {}).get("applied_at") is None
    ]
    await registry.dispatch(resolved_1)
    rows_after_redispatch = await ledger.fetch(COMPANY)
    post_redispatch_all_originals = [
        r for r in _execute_rows(rows_after_redispatch, "emit_experiment_lesson")
        if (r.get("payload") or {}).get("args", {}).get("applied_at") is None
    ]
    assert len(post_redispatch_all_originals) == len(pre_redispatch_all_originals), (
        f"re-dispatching an already-extracted resolved row must not write "
        f"a new extraction — extract_lesson's prior_keep_id dedup is the "
        f"ledger-side idempotency guarantee. "
        f"pre={len(pre_redispatch_all_originals)} "
        f"post={len(post_redispatch_all_originals)}"
    )
    assert pre_redispatch_originals >= 2, (
        "sanity: at least the two seeded extractions must be present"
    )


# ---------------------------------------------------------------------------
# Body 2 — multiple resolved across a day -> exactly one keep_rate publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_keep_rate_publishes_once_per_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple resolved rows across a UTC day -> one fire of
    ``KeepRatePublishReactivity`` (Periodic(86_400) ∧ NotRecentlyFired(24h)).

    Steps:
      1. Reset clock to start-of-day NOW.
      2. Seed THREE force-keep resolved rows spread across the day
         (00:00, 06:00, 18:00 UTC).
      3. Step the registry once — the first resolved row triggers the
         Reactivity; the subsequent two land in the same Periodic bucket
         and are gated.
      4. Assert exactly ONE day's worth of
         ``emit_metrics_keep_rate_published`` rows exists for the day
         (three scopes ⇒ three rows ⇒ one fire of the Reactivity).
      5. Advance the clock past 24h (next day's bucket) and re-dispatch
         the same resolved rows — the bucket has rolled, so the
         Reactivity fires again ⇒ a second day's worth of published rows.
    """
    ledger = InMemoryLedger()
    state = {"now": NOW}
    registry = await _build_wired_registry(ledger, state)
    await _seed_person(ledger, COMPANY, CAROL, "Carol", "cfo")

    # 1. Three kept resolutions spread across day-1.
    eid_a, _ = await _force_keep_resolution(
        ledger, COMPANY, monkeypatch,
        person_id=CAROL, position_id="cfo",
        seed_extra="keep-rate-a", at=NOW,
    )
    eid_b, _ = await _force_keep_resolution(
        ledger, COMPANY, monkeypatch,
        person_id=CAROL, position_id="cfo",
        seed_extra="keep-rate-b", at=NOW + timedelta(hours=6),
    )
    eid_c, _ = await _force_keep_resolution(
        ledger, COMPANY, monkeypatch,
        person_id=CAROL, position_id="cfo",
        seed_extra="keep-rate-c", at=NOW + timedelta(hours=18),
    )
    # Sanity: distinct experiment_ids so the Periodic gate's at-most-once
    # behaviour is meaningfully tested (three resolved rows, not three
    # references to the same one).
    assert len({eid_a, eid_b, eid_c}) == 3

    # 2. Step the registry. The clock is pinned to NOW (start of day).
    # Body of KeepRatePublishReactivity calls publish_for_day(today) ⇒
    # writes one emit_metrics_keep_rate_published per scope. Periodic
    # gate fires on the first kept resolved; the next two are denied
    # by Periodic (same bucket) AND NotRecentlyFired (within 24h).
    _cursor, fired = await _step_dispatch_new_entries(
        ledger, registry, COMPANY, cursor=0,
    )
    assert "keep_rate_publish" in fired, (
        f"expected KeepRatePublishReactivity to fire at least once; "
        f"got fired_ids={fired!r}"
    )

    # 3. Assert exactly ONE day's publication landed: three scopes
    # (person/team/company) ⇒ three rows for day-1.
    rows = await ledger.fetch(COMPANY)
    day1_pubs = [
        r for r in _execute_rows(rows, "emit_metrics_keep_rate_published")
        if (r.get("payload") or {}).get("args", {}).get("day")
        == NOW.date().isoformat()
    ]
    scopes_published_day1 = {
        (r["payload"]["args"]).get("scope") for r in day1_pubs
    }
    assert scopes_published_day1 == {"person", "team", "company"}, (
        f"expected publisher to fan out to all three scopes for day-1; "
        f"got {scopes_published_day1}"
    )
    assert len(day1_pubs) == 3, (
        f"expected exactly three day-1 published rows (one per scope); "
        f"got {len(day1_pubs)} — Periodic(86_400) failed to gate the "
        f"two follow-up resolutions inside the same UTC day bucket"
    )

    # 4. Count fires of the Reactivity itself via the audit log
    # (emit_reactivity_fired). At-most-once-per-day is enforced by the
    # condition; the publisher's per-(scope,day) dedup is belt-and-braces.
    fired_rows = _execute_rows(rows, "emit_reactivity_fired")
    keep_rate_fires_day1 = [
        r for r in fired_rows
        if (r["payload"]["args"]).get("reactivity_id") == "keep_rate_publish"
    ]
    assert len(keep_rate_fires_day1) == 1, (
        f"expected exactly one KeepRatePublishReactivity fire across "
        f"day-1 (Periodic gate ⇒ one fire per UTC day); "
        f"got {len(keep_rate_fires_day1)}"
    )

    # 5. Advance the clock to day-2 (25h later — past the period bucket
    # and past the NotRecentlyFired window). Re-dispatch the resolved
    # rows; both gates re-allow, so the Reactivity fires once more and
    # publishes day-2's three scope rows.
    state["now"] = NOW + timedelta(hours=25)
    # Find the resolved rows we already wrote and re-dispatch them
    # through the registry. (In production these would be NEW resolved
    # rows landing on day-2; for this assertion the trigger payload is
    # immaterial — what matters is the bucket-rollover behaviour of the
    # Periodic condition.)
    resolved_rows = _execute_rows(rows, "emit_experiment_resolved")
    assert resolved_rows, "expected at least one resolved row to re-dispatch"
    for r in resolved_rows[:1]:  # one is enough — the gate is the test
        await registry.dispatch(r)

    rows_day2 = await ledger.fetch(COMPANY)
    day2_pubs = [
        r for r in _execute_rows(rows_day2, "emit_metrics_keep_rate_published")
        if (r.get("payload") or {}).get("args", {}).get("day")
        == state["now"].date().isoformat()
    ]
    scopes_published_day2 = {
        (r["payload"]["args"]).get("scope") for r in day2_pubs
    }
    assert scopes_published_day2 == {"person", "team", "company"}, (
        f"expected publisher to fan out to all three scopes for day-2 "
        f"after the period rolled; got {scopes_published_day2}"
    )

    keep_rate_fires_total = [
        r for r in _execute_rows(rows_day2, "emit_reactivity_fired")
        if (r["payload"]["args"]).get("reactivity_id") == "keep_rate_publish"
    ]
    assert len(keep_rate_fires_total) == 2, (
        f"expected exactly two KeepRatePublishReactivity fires across "
        f"day-1 + day-2 (one per UTC day bucket); "
        f"got {len(keep_rate_fires_total)}"
    )


# ---------------------------------------------------------------------------
# Determinism — the wave's hash-stability acceptance bullet
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_keep_lifecycle_is_hash_stable_across_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Five replays produce identical post-cycle ledger shapes.

    Acceptance bullet: "Tests use deterministic clock; output is
    hash-stable across 5 runs." Same posture as I.1's hash-stability
    test — assert on (seq, kind, tool) shape rather than raw bytes
    so uuid4() inside ledger envelopes (ref_id wrappers, propose hashes)
    doesn't poison the assertion. Determinism axes that matter for
    composition correctness — entry kind sequence, lesson + publication
    cadence — are byte-stable.
    """
    shapes: list[list[tuple[int, str, str]]] = []
    for _ in range(5):
        ledger = InMemoryLedger()
        state = {"now": NOW}
        registry = await _build_wired_registry(ledger, state)
        await _seed_person(ledger, COMPANY, CAROL, "Carol", "cfo")
        await _force_keep_resolution(
            ledger, COMPANY, monkeypatch,
            person_id=CAROL, position_id="cfo",
            seed_extra="determinism", at=NOW,
        )

        cursor = 0
        for _ in range(8):
            new_cursor, _ = await _step_dispatch_new_entries(
                ledger, registry, COMPANY, cursor=cursor,
            )
            if new_cursor == cursor:
                break
            cursor = new_cursor

        rows = await ledger.fetch(COMPANY)
        shape: list[tuple[int, str, str]] = []
        for r in sorted(rows, key=lambda r: int(r.get("seq", 0))):
            kind = str(r.get("kind") or "")
            tool = ""
            if kind == "execute":
                tool = str((r.get("payload") or {}).get("tool") or "")
            shape.append((int(r.get("seq", 0)), kind, tool))
        shapes.append(shape)

    baseline = shapes[0]
    for i, candidate in enumerate(shapes[1:], start=1):
        assert candidate == baseline, (
            f"replay #{i} ledger shape diverged from baseline:\n"
            f"  baseline: {baseline}\n"
            f"  candidate: {candidate}"
        )
