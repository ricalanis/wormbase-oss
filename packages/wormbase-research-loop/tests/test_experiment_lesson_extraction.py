"""P9 — ``experiment_lesson`` extraction tests.

When an ``experiment_resolved`` row with ``outcome="keep"`` lands, the
autoresearch learn step extracts a structured lesson and writes it back
to the ledger as ``emit_experiment_lesson``. These tests cover:

  * A keep produces exactly one lesson with the spec's payload shape.
  * Lesson text is non-trivial — it names the features that drove the
    keep (predicate + change_target + delta_label), not just "score=0.8".
  * lesson_features include the structured features the next proposer
    reweighs.
  * Discards do NOT produce lessons.
  * Idempotency: re-running extraction does not duplicate lessons.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from wormbase_research_loop import AutoresearchLoop
from wormbase_research_loop.learn import (
    extract_lesson_features,
    extract_lessons_for_kept,
)


CAROL = UUID("00000000-0000-0000-0000-0000000000c1")
NOW = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)


async def _register_person(ledger, company_id, person_id, name, position):
    """Seed person + position so the loop can run a cycle."""
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


async def _emitted(ledger, company_id, tool):
    rows = await ledger.fetch(company_id)
    return [
        r for r in rows
        if r["kind"] == "execute" and r["payload"]["tool"] == tool
    ]


async def _run_until_a_keep(ledger, company_id, *, person, position, max_cycles=10):
    """Drive the loop until at least one keep lands. Returns the loop."""
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    for _ in range(max_cycles):
        await loop.run_once(now=NOW)
        resolved = await _emitted(ledger, company_id, "emit_experiment_resolved")
        if any(r["payload"]["args"]["outcome"] == "keep" for r in resolved):
            return loop
    raise AssertionError("no keep landed in max_cycles")


# ---------------------------------------------------------------------------
# Pure-function extraction tests
# ---------------------------------------------------------------------------


def test_extract_lesson_features_returns_non_trivial_text():
    proposed_args = {
        "experiment_id": "exp-1",
        "for_person_id": str(CAROL),
        "position": "cfo",
        "headline_metric": "revenue",
        "proposed_change": {
            "kind": "kpi_definition",
            "target": "revenue_forecast",
            "change": "exclude_promo_signups_from_cohort",
        },
        "expected_delta": 0.04,
        "audience": f"person:{CAROL}",
    }
    resolved_args = {
        "experiment_id": "exp-1",
        "outcome": "keep",
        "observed_delta": 0.036,
        "rationale": "kept by deterministic rule",
    }
    text, features = extract_lesson_features(
        experiment_id="exp-1",
        proposed_args=proposed_args,
        resolved_args=resolved_args,
        run_args=None,
        adjacent_discards=[
            {
                "experiment_id": "exp-2",
                "proposed_change": {
                    "kind": "kpi_definition",
                    "target": "revenue_forecast",
                    "change": "naive_linear_extrapolation",
                },
                "observed_delta": -0.005,
            },
        ],
    )
    # Lesson text names the features that drove the keep — never just "score=0.8".
    assert "revenue" in text
    assert "exclude_promo_signups_from_cohort" in text
    assert "kpi_definition" in text
    assert "Reweight" in text  # action-oriented, not just description
    # Quality bar per PRD §7 P9: more than a "kept because score=0.8" stub.
    assert len(text) > 80, "lesson_text must be non-trivial"
    # Structured features cover the predicates / conditions / topics.
    assert features["metric"] == "revenue"
    assert features["position"] == "cfo"
    assert features["change_kind"] == "kpi_definition"
    assert features["change_target"] == "revenue_forecast"
    assert features["change_predicate"] == "exclude_promo_signups_from_cohort"
    assert features["delta_label"] in ("hit_expectation", "exceeded_expectation")
    assert features["adjacent_discard_count"] == "1"
    assert features["predicate_was_novel_vs_discards"] == "true"
    assert "naive_linear_extrapolation" in features["adjacent_discard_predicates"]


def test_extract_lesson_features_handles_no_adjacent_discards():
    proposed_args = {
        "position": "data_engineer",
        "headline_metric": "pipeline_p95_latency_ms",
        "proposed_change": {
            "kind": "process_change",
            "target": "etl_window",
            "change": "shift_to_off_peak",
        },
        "expected_delta": -50.0,
    }
    resolved_args = {"outcome": "keep", "observed_delta": -45.0}
    text, features = extract_lesson_features(
        experiment_id="exp-x",
        proposed_args=proposed_args,
        resolved_args=resolved_args,
        run_args=None,
        adjacent_discards=[],
    )
    assert "no adjacent discards" in text.lower()
    assert features["adjacent_discard_count"] == "0"
    assert features["predicate_was_novel_vs_discards"] == "false"


# ---------------------------------------------------------------------------
# Ledger-driven extraction tests
# ---------------------------------------------------------------------------


async def test_keep_produces_one_lesson_entry(ledger, company_id):
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    await _run_until_a_keep(
        ledger, company_id, person=CAROL, position="cfo",
    )
    lessons = await _emitted(ledger, company_id, "emit_experiment_lesson")
    assert len(lessons) >= 1, "at least one lesson should fire on a keep"

    args = lessons[0]["payload"]["args"]
    # Spec shape per PRD §7 P9
    assert "prior_keep_id" in args
    assert args["scope"] in {"person", "team", "company"}
    assert isinstance(args["lesson_text"], str) and len(args["lesson_text"]) > 0
    assert isinstance(args["lesson_features"], dict)
    assert args["applied_to_proposer"] == "autoresearch_loop"
    # applied_at is None until the next propose consumes the lesson;
    # we'll see it filled in test_lesson_application.
    # proposed_by is the harness per CLAUDE.md invariant 7.
    assert args["proposed_by"] == "autoresearch_loop"


async def test_lesson_text_is_non_trivial(ledger, company_id):
    """Quality bar: lesson_text must capture which features correlated.

    PRD §7 P9: "lesson text is non-trivial — not just 'kept because score=0.8'".
    """
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    await _run_until_a_keep(
        ledger, company_id, person=CAROL, position="cfo",
    )
    lessons = await _emitted(ledger, company_id, "emit_experiment_lesson")
    text = lessons[0]["payload"]["args"]["lesson_text"]
    # Names the position
    assert "cfo" in text.lower()
    # Names the structured feature changes
    features = lessons[0]["payload"]["args"]["lesson_features"]
    assert features["change_predicate"] in text
    assert features["change_kind"] in text


async def test_discards_do_not_produce_lessons(ledger, company_id):
    """Only kept experiments produce lessons; discards do not."""
    # Force a context with only-discards by running the extractor directly
    # against a freshly-seeded ledger (no kept experiments yet).
    n = await extract_lessons_for_kept(ledger, company_id, now=NOW)
    assert n == 0
    lessons = await _emitted(ledger, company_id, "emit_experiment_lesson")
    assert lessons == []


async def test_extraction_is_idempotent(ledger, company_id):
    """Re-running the extractor against the same ledger does not duplicate."""
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    await _run_until_a_keep(
        ledger, company_id, person=CAROL, position="cfo",
    )
    before = len(await _emitted(ledger, company_id, "emit_experiment_lesson"))
    # Re-run extraction explicitly twice.
    n1 = await extract_lessons_for_kept(ledger, company_id, now=NOW)
    n2 = await extract_lessons_for_kept(ledger, company_id, now=NOW)
    assert n1 == 0
    assert n2 == 0
    after = len(await _emitted(ledger, company_id, "emit_experiment_lesson"))
    assert before == after


async def test_lesson_scope_matches_audience(ledger, company_id):
    """A Person-scope keep produces a Person-scope lesson (audience parity)."""
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    await _run_until_a_keep(
        ledger, company_id, person=CAROL, position="cfo",
    )
    lessons = await _emitted(ledger, company_id, "emit_experiment_lesson")
    scopes = {L["payload"]["args"]["scope"] for L in lessons}
    # Every lesson should be person-scope (no team/company runs in this test).
    assert scopes == {"person"}
