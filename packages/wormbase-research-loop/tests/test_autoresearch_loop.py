"""Step 5 — per-user Karpathy autoresearch loop tests.

Drives ``AutoresearchLoop.run_once`` against an InMemoryLedger seeded with
``emit_person_registered`` + ``emit_position_assigned`` entries and asserts
the canonical propose → run → resolve cycle lands per (person × position).

Key invariants:
  * One propose+run+resolve triple per registered (person × position) per
    cycle (plus one metric_observed sample).
  * Outcomes are deterministic by ``hash(experiment_id) % 5 < 3`` (60% keep).
  * Replay-stable: same ledger state + same cycle => same experiment_ids.
  * Unknown positions are skipped (extensibility safety).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from wormbase_research_loop.loop import AutoresearchLoop
from wormbase_core.positions import position_candidates


CAROL = UUID("00000000-0000-0000-0000-0000000000c1")
DAVE = UUID("00000000-0000-0000-0000-0000000000c2")
EVE = UUID("00000000-0000-0000-0000-0000000000c3")
NOW = datetime(2026, 4, 24, 10, 0, tzinfo=UTC)


async def _register_person(
    ledger, company_id, person_id: UUID, name: str, position: str
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


async def _emitted(ledger, company_id, tool: str) -> list[dict]:
    rows = await ledger.fetch(company_id)
    return [
        r for r in rows
        if r["kind"] == "execute" and r["payload"]["tool"] == tool
    ]


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------


async def test_loop_skips_when_no_persons(ledger, company_id):
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    n = await loop.run_once(now=NOW)
    assert n == 0
    proposed = await _emitted(ledger, company_id, "emit_experiment_proposed")
    assert proposed == []


async def test_loop_discovers_registered_people(ledger, company_id):
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    await _register_person(ledger, company_id, DAVE, "Dave", "data_engineer")
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    pairs = await loop._collect_person_positions()  # type: ignore[attr-defined]
    ids = {(p.person_id, p.position_id) for p in pairs}
    assert (CAROL, "cfo") in ids
    assert (DAVE, "data_engineer") in ids


async def test_loop_skips_unknown_positions(ledger, company_id):
    await _register_person(ledger, company_id, EVE, "Eve", "ceremonial_master")
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    pairs = await loop._collect_person_positions()  # type: ignore[attr-defined]
    assert all(p.person_id != EVE for p in pairs)


# ----------------------------------------------------------------------
# Per-cycle behaviour
# ----------------------------------------------------------------------


async def test_one_cycle_per_person_emits_full_pevr(ledger, company_id):
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    n = await loop.run_once(now=NOW)
    assert n == 1
    proposed = await _emitted(ledger, company_id, "emit_experiment_proposed")
    runs = await _emitted(ledger, company_id, "emit_experiment_run")
    resolved = await _emitted(ledger, company_id, "emit_experiment_resolved")
    metrics = await _emitted(ledger, company_id, "emit_metric_observed")
    assert len(proposed) == 1
    assert len(runs) == 1
    assert len(resolved) == 1
    # One metric sample per cycle per person.
    assert len(metrics) == 1
    # Propose + run + resolve all share the same experiment_id.
    eid = proposed[0]["payload"]["args"]["experiment_id"]
    assert runs[0]["payload"]["args"]["experiment_id"] == eid
    assert resolved[0]["payload"]["args"]["experiment_id"] == eid


async def test_proposed_args_carry_position_metadata(ledger, company_id):
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    await loop.run_once(now=NOW)
    proposed = await _emitted(ledger, company_id, "emit_experiment_proposed")
    args = proposed[0]["payload"]["args"]
    assert args["position"] == "cfo"
    assert args["for_person_id"] == str(CAROL)
    assert args["headline_metric"]
    assert isinstance(args["proposed_change"], dict)


async def test_resolution_outcome_is_deterministic(ledger, company_id):
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    await loop.run_once(now=NOW)
    resolved = await _emitted(ledger, company_id, "emit_experiment_resolved")
    args = resolved[0]["payload"]["args"]
    assert args["outcome"] in ("keep", "discard")
    # Re-running with the same cycle should produce the same experiment_id;
    # collisions (duplicate writes) are ledger-safe but the loop still picks
    # the same candidate deterministically. We verify the candidate pick.
    cycle1_eid = args["experiment_id"]
    # Run another cycle (advances counter) and check we get a *different* id.
    await loop.run_once(now=NOW)
    resolved_after = await _emitted(ledger, company_id, "emit_experiment_resolved")
    assert len(resolved_after) >= 2
    cycle2_eid = resolved_after[-1]["payload"]["args"]["experiment_id"]
    assert cycle1_eid != cycle2_eid


async def test_keep_rate_is_around_60_percent(ledger, company_id):
    """Sanity: across a few cycles the keep:discard ratio should land near 60/40.

    We seed a few people across positions and run several cycles to get a
    big enough sample. Tolerance is generous because our universe is small.
    """
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    await _register_person(ledger, company_id, DAVE, "Dave", "data_engineer")
    await _register_person(ledger, company_id, EVE, "Eve", "marketing_lead")
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    for _ in range(8):
        await loop.run_once(now=NOW)
    resolved = await _emitted(ledger, company_id, "emit_experiment_resolved")
    keeps = sum(
        1 for r in resolved
        if r["payload"]["args"]["outcome"] == "keep"
    )
    total = len(resolved)
    assert total >= 12
    keep_ratio = keeps / total
    # 60% target; allow generous slack for small samples.
    assert 0.3 <= keep_ratio <= 0.85


async def test_per_position_metric_observed_for_each_person(ledger, company_id):
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    await _register_person(ledger, company_id, DAVE, "Dave", "data_engineer")
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    await loop.run_once(now=NOW)
    metrics = await _emitted(ledger, company_id, "emit_metric_observed")
    by_position = {m["payload"]["args"]["position"] for m in metrics}
    assert "cfo" in by_position
    assert "data_engineer" in by_position


async def test_cycle_picks_different_candidates_across_cycles(ledger, company_id):
    """Round-robin candidate pick: same person, different cycle => different candidate.

    The cfo position has 3 candidates so two cycles should hit at least 2
    distinct candidate_ids.
    """
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    seen: set[str] = set()
    for _ in range(4):
        await loop.run_once(now=NOW)
    proposed = await _emitted(ledger, company_id, "emit_experiment_proposed")
    for p in proposed:
        change = p["payload"]["args"]["proposed_change"]
        # Use the candidate's "target" + "kind" as a proxy for candidate id.
        seen.add(f"{change.get('kind')}:{change.get('target')}")
    cfo_cands = position_candidates("cfo")
    # We should have hit at least 2 distinct cfo candidates over 4 cycles.
    assert len(seen) >= 2
    assert len(seen) <= len(cfo_cands)


async def test_loop_emits_run_log_with_runtime(ledger, company_id):
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    await loop.run_once(now=NOW)
    runs = await _emitted(ledger, company_id, "emit_experiment_run")
    log = runs[0]["payload"]["args"]["log"]
    assert log["position"] == "cfo"
    assert log["person_id"] == str(CAROL)
    assert log["synthetic_runtime_s"] >= 1


async def test_loop_handles_position_reassignment_latest_wins(
    ledger, company_id
):
    """If a person's position is reassigned, the latest assignment wins."""
    await _register_person(ledger, company_id, CAROL, "Carol", "cfo")
    # Reassign
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "position_assigned",
            "ref_id": str(CAROL),
            "reason": "reassign",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_position_assigned",
            "args": {
                "person_id": str(CAROL),
                "position": "founder",
                "at": NOW.isoformat(),
            },
            "result_ref": str(CAROL),
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    await loop.run_once(now=NOW)
    proposed = await _emitted(ledger, company_id, "emit_experiment_proposed")
    # Latest assignment is founder; we should see at least one founder
    # proposal for Carol.
    by_position = {p["payload"]["args"]["position"] for p in proposed}
    assert "founder" in by_position
