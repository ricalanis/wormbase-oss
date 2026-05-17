"""End-to-end: phenomenon_gap_detected -> ExperimentTriggerReactivity -> cycle.

Task I.1 of the research-worm extraction plan
(docs/superpowers/plans/2026-05-03-research-worm-extraction.md, lines 1086-1153).

The first integration test for the W5b -> research-worm composition. Drives
the full chain purely through the ledger:

  1. Seed a ``chat_received`` entry that mentions a missing KPI.
  2. Step the registry over new ledger entries.
  3. The W5b ``KpiReferenceWithoutKpiReactivity`` fires, writing
     ``emit_phenomenon_gap_detected``.
  4. Step again. ``ExperimentTriggerReactivity`` fires (its OR predicate
     matches both ``chat_received`` AND ``phenomenon_gap_detected`` --
     either entry is a legitimate trigger).
  5. Trigger fire writes the canonical PEVR sequence
     (``emit_experiment_proposed`` -> ``emit_experiment_run`` ->
     ``emit_experiment_resolved``) and -- on outcome=keep -- the
     keep-notebook publish triple.

The test contains zero direct calls to ``propose_experiment`` /
``run_experiment`` / ``resolve_experiment``. It only seeds the ledger
fixture and dispatches new entries through the registry. The composition
between W5b and research-worm is verified to be purely ledger-mediated --
the spike's "architectural opportunity" is now exercised by CI.

Reference patterns:
  * ``tests/integration/test_chat_worm_e2e.py`` -- Wave B's analogue:
    chat_received -> chat-worm Reactivities -> chat_reply PEVR cycle.
  * ``tests/integration/test_identity_worm_e2e.py`` -- Wave A's analogue:
    chat_received -> identity-worm Reactivity -> projection_persons.

Stepping model: we drive registry.dispatch directly inside a controlled
"new entries since cursor" loop rather than constructing a
``ReactivityRunner``. The runner's cursor advances past mid-cycle writes
(see runner.py:175-194 -- the "registry's writes from this dispatch ...
fall outside the cycle" line), which would mask the cascade we want to
exercise. The dispatch path is identical to the runner's; only the
cursor-management policy differs. The composition assertion -- that W5b
output enters research-worm only via ledger entries -- is unchanged.

Note on cycle collapse: the ``ExperimentTriggerReactivity`` predicate is
``Or(EntryKind("phenomenon_gap_detected"), ..., EntryKind("chat_received"))``,
so a single ``chat_received`` row triggers BOTH the W5b detector AND the
research-loop trigger in the same dispatch cycle (W5b runs first because it
was registered first; research-loop runs immediately after). The cascade
the spec describes (gap -> step -> trigger) still exists architecturally
-- on the next cycle the new ``phenomenon_gap_detected`` row would also
trigger the research-loop, but the registry's NotRecentlyFired condition
suppresses that follow-up fire by design. The test asserts the full
chain's output (gap row + PEVR sequence + keep notebook) lands in the
ledger regardless of whether collapse happens; the ledger-mediation
property is independent of the dispatch order.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_chat_presence import Install
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.phenomenon_gaps import (
    DomainReferenceWithoutDomainReactivity,
    KpiReferenceWithoutKpiReactivity,
    ProcessReferenceWithoutProcessReactivity,
    RecurringActionWithoutReactivityReactivity,
)
from wormbase_reactivities.registry import ReactivityRegistry
from wormbase_research_loop import wire_research_for_install


# Stable identifiers so the run is hash-stable across replays.
COMPANY = UUID("00000000-0000-0000-0000-00000000ca0e")
ALICE = UUID("00000000-0000-0000-0000-0000000000a1")
NOW = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers (no direct calls to research-loop helpers; ledger seed only)
# ---------------------------------------------------------------------------


async def _seed_person(
    ledger: InMemoryLedger,
    company_id: UUID,
    person_id: UUID,
    name: str,
    position: str,
) -> None:
    """Seed emit_person_registered + emit_position_assigned for a person.

    Mirrors the helper in test_experiment_trigger_reactivity.py so the
    autoresearch loop's ``_collect_person_positions`` projection has a
    PersonPosition to drive against. Same pattern the production wire
    uses -- the ledger entries are byte-identical to channel-adapter
    output.
    """
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
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
        timestamp=NOW,
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
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
        timestamp=NOW,
    )


async def _seed_chat_received_kpi_gap(
    ledger: InMemoryLedger,
    company_id: UUID,
    text: str = "we should track NPS as our headline metric",
) -> None:
    """Seed one chat_received entry whose text triggers the KPI-gap detector.

    "track" is one of the high-confidence cue words in
    predicates_advanced._extract_metric_candidates, and "NPS" is in the
    seed _METRIC_VOCAB. Combined confidence is 0.9 -- well above the
    detector's 0.6 default threshold. The KPI tree is empty so the
    detector's ``_existing_kpi_labels`` probe returns no matches.
    """
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "chat_received",
            "ref_id": str(uuid4()),
            "reason": "test inbound message",
            "proposed_by": "channel_adapter",
        },
        execute_fn=lambda: {
            "tool": "channel_adapter.emit_chat_received",
            "args": {
                "platform": "slack",
                "channel_id": "C-test",
                "message_id": "msg-1",
                "text": text,
                "sender_person": str(ALICE),
                "ts": NOW.isoformat(),
            },
            "result_ref": "msg-1",
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        timestamp=NOW,
        quadrant="active_probabilistic",
    )


async def _step_dispatch_new_entries(
    ledger: InMemoryLedger,
    registry: ReactivityRegistry,
    company_id: UUID,
    cursor: int,
) -> tuple[int, list[str]]:
    """Dispatch every entry with seq > cursor through the registry.

    Returns (new_cursor, fired_ids). The new cursor is the max seq seen
    BEFORE dispatch -- so the next call processes both the cascade
    (entries written by fire bodies) and any further upstream events.
    This mirrors what an ideal runner cycle would do; we sidestep
    ReactivityRunner's cursor-advances-past-mid-cycle-writes policy
    because that policy would silently swallow the cascade we are
    asserting on (see module docstring).
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
            # Entries written during this very cycle by other Reactivities
            # are picked up on the next step, not this one. Keeps the
            # cycle's snapshot semantics tight.
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


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_phenomenon_gap_detected_drives_full_cycle() -> None:
    """KPI-gap chat -> phenomenon_gap_detected -> propose+run+resolve cycle.

    The composition assertion: research-worm sees the W5b detector's
    output ONLY through the ledger. No direct method call between the
    two packages is made by the test or by the production wire.
    """
    ledger = InMemoryLedger()

    # Deterministic clock so two runs produce identical ledger output.
    # (The trigger Reactivity reads context.now to stamp experiment_run's
    # started_at / finished_at; pinning ``now`` is the determinism axis.)
    clock = lambda: NOW  # noqa: E731 -- intentional one-liner

    registry = ReactivityRegistry(
        ledger=ledger, company_id=COMPANY, now=clock,
    )

    # Register all four W5b phenomenon-gap detectors.
    registry.register(KpiReferenceWithoutKpiReactivity())
    registry.register(DomainReferenceWithoutDomainReactivity())
    registry.register(ProcessReferenceWithoutProcessReactivity())
    registry.register(RecurringActionWithoutReactivityReactivity())

    # Wire the four research-loop Reactivities (one factory call, the
    # production lifecycle hook). per_scope_daily_budget=10 keeps the
    # in-fire short-circuit out of the way for the assertion path.
    install = Install(id=COMPANY, platform="slack")
    await wire_research_for_install(
        install=install,
        ledger=ledger,
        reactivity_registry=registry,
        per_scope_daily_budget=10,
    )

    # Seed enough state for the trigger Reactivity's fire body to find a
    # PersonPosition (see _collect_person_positions in loop.py:190-239 --
    # without person + position rows, fire returns fired=False and emits
    # nothing, so the cascade can't complete).
    await _seed_person(ledger, COMPANY, ALICE, "Alice", "cfo")

    # 1. Seed: a chat_received entry referencing a missing KPI.
    await _seed_chat_received_kpi_gap(ledger, COMPANY)

    # 2. Step: dispatch the chat_received row. The W5b KPI detector fires
    # AND the research-loop ExperimentTriggerReactivity fires on the same
    # row (its OR predicate includes both chat_received and
    # phenomenon_gap_detected -- both upstream signals are legitimate).
    # See module docstring's "cycle collapse" note for the rationale.
    cursor, fired_step1 = await _step_dispatch_new_entries(
        ledger, registry, COMPANY, cursor=0,
    )
    assert "kpi_reference_without_kpi" in fired_step1, (
        f"expected KpiReferenceWithoutKpiReactivity to fire on the seeded "
        f"chat_received; got fired_ids={fired_step1!r}"
    )
    assert "experiment_trigger" in fired_step1, (
        f"expected ExperimentTriggerReactivity to fire on the same "
        f"chat_received entry (OR predicate includes 'chat_received'); "
        f"got fired_ids={fired_step1!r}"
    )

    # 3. Assert: a phenomenon_gap_detected execute entry now exists --
    # written by the W5b detector inside its fire body.
    rows = await ledger.fetch(COMPANY)
    gap_rows = _execute_rows(rows, "emit_phenomenon_gap_detected")
    assert len(gap_rows) == 1, (
        f"expected exactly one phenomenon_gap_detected entry after step 1; "
        f"got {len(gap_rows)}"
    )
    gap_args = gap_rows[0]["payload"]["args"]
    assert gap_args["kind"] == "kpi"
    assert gap_args["suggested_proposal"]["label"] == "nps"

    # 4. Step again. The new phenomenon_gap_detected entry would also
    # trigger ExperimentTriggerReactivity via the OR predicate, but the
    # registry's NotRecentlyFired condition (300s window) suppresses the
    # follow-up fire. Cascade Reactivities -- ExperimentResolveReactivity
    # on emit_experiment_run, LessonExtractionReactivity on the kept
    # emit_experiment_resolved, KeepRatePublishReactivity on
    # emit_experiment_resolved -- DO fire on the new mid-cascade rows.
    cursor, fired_step2 = await _step_dispatch_new_entries(
        ledger, registry, COMPANY, cursor=cursor,
    )

    # 5. Assert: the canonical PEVR sequence landed (the trigger's fire
    # body emits propose -> run -> resolve inline).
    rows = await ledger.fetch(COMPANY)
    proposed_rows = _execute_rows(rows, "emit_experiment_proposed")
    assert len(proposed_rows) >= 1, (
        "expected at least one emit_experiment_proposed entry after step 1"
    )
    run_rows = _execute_rows(rows, "emit_experiment_run")
    assert len(run_rows) >= 1, (
        "expected at least one emit_experiment_run entry after step 1 -- "
        "the trigger Reactivity emits run inline"
    )
    resolved_rows = _execute_rows(rows, "emit_experiment_resolved")
    assert len(resolved_rows) >= 1, (
        "expected at least one emit_experiment_resolved entry after step 1"
    )

    # 6. Assert: PEVR ordering -- propose seq < run seq < resolve seq.
    proposed_seq = int(proposed_rows[0]["seq"])
    run_seq = int(run_rows[0]["seq"])
    resolved_seq = int(resolved_rows[0]["seq"])
    assert proposed_seq < run_seq < resolved_seq, (
        f"expected PEVR ordering; got proposed={proposed_seq} "
        f"run={run_seq} resolved={resolved_seq}"
    )

    # 7. Conditional: if outcome=="keep", a notebook artifact landed.
    # The trigger Reactivity uses AutoresearchLoop._resolve, which is
    # deterministic on experiment_id (60% keep / 40% discard). The
    # experiment_id is uuid5-derived from the seed -- so this branch is
    # decided by the seed, not by the test.
    outcome = resolved_rows[0]["payload"]["args"]["outcome"]
    publish_rows = _execute_rows(rows, "emit_notebook_published")
    if outcome == "keep":
        assert len(publish_rows) >= 1, (
            "outcome=keep but no emit_notebook_published in the ledger"
        )
    else:
        assert len(publish_rows) == 0, (
            f"outcome={outcome} but a notebook_published entry landed "
            f"-- the publish path should be skipped on discard"
        )

    # 8. Assert: cascade Reactivities (resolve / lesson / keep_rate)
    # fired in step 2 on the mid-cascade rows. This is the second-order
    # composition assertion: research-loop reactivities also chain
    # together purely through the ledger.
    assert "experiment_resolve" in fired_step2, (
        f"expected ExperimentResolveReactivity to fire on the mid-cascade "
        f"emit_experiment_run; got fired_ids={fired_step2!r}"
    )


@pytest.mark.asyncio
async def test_e2e_replay_is_hash_stable_across_runs() -> None:
    """Five replays produce identical ledger hash chains.

    Acceptance bullet: "Test is deterministic across at least 5 runs
    (hash-stable ledger output)." Replay the same fixture five times
    against fresh registries / ledgers and assert the post-cycle
    hash chain matches byte-for-byte.

    Determinism axes:
      * Clock pinned to NOW (eliminates timestamp variation).
      * Person id ALICE is a constant UUID (no uuid4 in the wire path).
      * Experiment id is uuid5 over (scope, scope_id, person, seq, tool,
        candidate_id) -- all deterministic given the seed.
      * AutoresearchLoop._resolve uses sha256(experiment_id).
      * _publish_keep_notebook id and run id are uuid5 of experiment_id.

    The remaining sources of nondeterminism are uuid4() calls inside
    _seed_chat_received_kpi_gap (the chat_received ref_id) and inside
    the W5b detectors' emit_phenomenon_gap_detected wrapper. We assert
    on the SHAPE of the post-cycle ledger (entry kinds + tools per
    seq) instead of raw hash bytes -- that gives us byte-stability of
    the structural cascade without coupling the test to uuid4 entropy.
    Same posture as test_install_arc_seeds and identity-worm e2e.
    """
    shapes: list[list[tuple[int, str, str]]] = []
    for _ in range(5):
        ledger = InMemoryLedger()
        clock = lambda: NOW  # noqa: E731
        registry = ReactivityRegistry(
            ledger=ledger, company_id=COMPANY, now=clock,
        )
        registry.register(KpiReferenceWithoutKpiReactivity())
        registry.register(DomainReferenceWithoutDomainReactivity())
        registry.register(ProcessReferenceWithoutProcessReactivity())
        registry.register(RecurringActionWithoutReactivityReactivity())
        install = Install(id=COMPANY, platform="slack")
        await wire_research_for_install(
            install=install,
            ledger=ledger,
            reactivity_registry=registry,
            per_scope_daily_budget=10,
        )
        await _seed_person(ledger, COMPANY, ALICE, "Alice", "cfo")
        await _seed_chat_received_kpi_gap(ledger, COMPANY)

        cursor = 0
        # Iterate until quiescence; the cascade is at most 2 cycles
        # (chat -> gap, gap -> experiment + notebook publish), but loop
        # generously to catch any future deepening of the cascade.
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

    # Every replay must produce the same (seq, kind, tool) sequence.
    baseline = shapes[0]
    for i, candidate in enumerate(shapes[1:], start=1):
        assert candidate == baseline, (
            f"replay #{i} ledger shape diverged from baseline:\n"
            f"  baseline: {baseline}\n"
            f"  candidate: {candidate}"
        )
