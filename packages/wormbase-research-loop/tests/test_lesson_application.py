"""P9 — lesson application test.

After a lesson lands, the next ``experiment_proposed`` for the same scope
must:

  1. Read recent (trailing-7-day) ``experiment_lesson`` entries.
  2. Include them in its propose-row reason + ``proposed_change.priors_applied``.
  3. Stamp ``applied_at`` on each consumed lesson with the seq of the
     consuming propose row (closes the loop empirically).

This file exercises the full propose path through ``AutoresearchLoop``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from wormbase_research_loop import AutoresearchLoop
from wormbase_research_loop.learn import recent_lessons_for_scope


CAROL = UUID("00000000-0000-0000-0000-0000000000c1")
NOW = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)


async def _register_person(ledger, company_id, person_id, name, position):
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


async def _drive_until_keep_then_one_more(
    ledger, company_id, *, max_cycles=20,
):
    """Run cycles until a keep lands, then run one more so a propose
    can consume the resulting lesson.

    Returns (loop, cycles_run).
    """
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    n = 0
    while n < max_cycles:
        await loop.run_once(now=NOW)
        n += 1
        resolved = await _emitted(ledger, company_id, "emit_experiment_resolved")
        if any(r["payload"]["args"]["outcome"] == "keep" for r in resolved):
            # One more cycle so the next propose consumes the just-extracted lesson.
            await loop.run_once(now=NOW)
            n += 1
            return loop, n
    raise AssertionError("no keep landed within max_cycles")


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------


async def test_recent_lessons_for_scope_returns_only_same_scope(ledger, company_id):
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    await _drive_until_keep_then_one_more(ledger, company_id)
    person_lessons = await recent_lessons_for_scope(
        ledger, company_id, scope="person", now=NOW,
    )
    team_lessons = await recent_lessons_for_scope(
        ledger, company_id, scope="team", now=NOW,
    )
    company_lessons = await recent_lessons_for_scope(
        ledger, company_id, scope="company", now=NOW,
    )
    # The default loop only fires Person-scope, so there must be no leak
    # across scopes.
    assert len(person_lessons) >= 1
    assert team_lessons == []
    assert company_lessons == []


# ---------------------------------------------------------------------------
# Application: lesson is folded into proposer's rationale + applied_at filled
# ---------------------------------------------------------------------------


async def test_next_proposer_reads_lesson_into_rationale(ledger, company_id):
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    await _drive_until_keep_then_one_more(ledger, company_id)
    propose_rows = [
        r for r in await ledger.fetch(company_id)
        if r["kind"] == "propose"
        and r["payload"].get("target_kind") == "experiment_proposed"
    ]
    # At least one propose row written *after* the lesson exists. We look
    # for the most recent propose row whose reason includes the prior-lesson
    # marker.
    reasons_with_priors = [
        r for r in propose_rows
        if "applying" in (r["payload"].get("reason") or "").lower()
        and "prior lesson" in (r["payload"].get("reason") or "").lower()
    ]
    assert reasons_with_priors, (
        "expected at least one propose row to carry a 'applying ... prior lesson' "
        "rationale once a lesson exists for the scope"
    )


async def test_next_propose_carries_priors_applied_in_proposed_change(ledger, company_id):
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    await _drive_until_keep_then_one_more(ledger, company_id)
    proposed = await _emitted(ledger, company_id, "emit_experiment_proposed")
    with_priors = [
        p for p in proposed
        if "priors_applied" in (p["payload"]["args"].get("proposed_change") or {})
    ]
    assert with_priors, (
        "expected at least one propose to fold lessons into proposed_change"
    )
    priors = with_priors[-1]["payload"]["args"]["proposed_change"]["priors_applied"]
    assert isinstance(priors, list) and priors
    assert all(isinstance(p, str) and p for p in priors)


async def test_applied_at_is_filled_on_first_application(ledger, company_id):
    """After the first propose consumes the lesson, applied_at is non-None."""
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    await _drive_until_keep_then_one_more(ledger, company_id)
    lessons = await _emitted(ledger, company_id, "emit_experiment_lesson")
    # The latest entry per prior_keep_id must carry applied_at != None.
    by_prior: dict[str, dict] = {}
    for L in lessons:
        args = L["payload"]["args"]
        # Track latest by seq so we get the post-application stamp.
        seq = int(L.get("seq") or 0)
        prior = str(args["prior_keep_id"])
        cur = by_prior.get(prior)
        if cur is None or seq > int(cur["seq"]):
            by_prior[prior] = {**L, "seq": seq}
    assert by_prior, "no lessons found"
    stamped = [L for L in by_prior.values() if L["payload"]["args"].get("applied_at") is not None]
    assert stamped, (
        "after at least one post-extraction propose, the lesson's latest "
        "version must carry applied_at != None"
    )
    # applied_at points at a real propose row's seq.
    seqs_of_proposed = {
        int(p["seq"])
        for p in await _emitted(ledger, company_id, "emit_experiment_proposed")
    }
    for L in stamped:
        applied = L["payload"]["args"]["applied_at"]
        assert applied in seqs_of_proposed, (
            f"applied_at={applied} must reference an actual propose row's seq "
            f"(seqs={sorted(seqs_of_proposed)})"
        )


async def test_applied_at_only_stamps_once_per_lesson(ledger, company_id):
    """Stamps only un-stamped lessons; never re-stamps an already-applied one."""
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    await _drive_until_keep_then_one_more(ledger, company_id)
    # Run a few more cycles. Each cycle re-reads the (now-stamped) lesson;
    # it must NOT re-stamp.
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    for _ in range(3):
        await loop.run_once(now=NOW)
    lessons = await _emitted(ledger, company_id, "emit_experiment_lesson")
    # Group by prior_keep_id; per prior, we expect exactly one un-stamped
    # extraction + at most one stamp.
    by_prior: dict[str, list[dict]] = {}
    for L in lessons:
        prior = str(L["payload"]["args"]["prior_keep_id"])
        by_prior.setdefault(prior, []).append(L)
    for prior, group in by_prior.items():
        none_count = sum(
            1 for L in group
            if L["payload"]["args"].get("applied_at") is None
        )
        stamped_count = sum(
            1 for L in group
            if L["payload"]["args"].get("applied_at") is not None
        )
        # One extraction (None), at most one stamp.
        assert none_count == 1, (
            f"prior {prior}: expected exactly one None-applied lesson; "
            f"got {none_count}"
        )
        assert stamped_count <= 1, (
            f"prior {prior}: expected at most one stamped lesson; "
            f"got {stamped_count}"
        )
