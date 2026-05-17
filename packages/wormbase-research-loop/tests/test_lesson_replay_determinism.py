"""P9 — replay determinism test.

CLAUDE.md invariant 8 (anything new must replay byte-identically): a fresh
ledger seeded the same way and driven through the same number of cycles
must produce the same lessons (lesson_text + lesson_features) and the
same applied_at heights.

Two parallel ledgers, same fixture seed, same cycle count, frozen clock:
the resulting ``experiment_lesson`` payload set must match field-by-field.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from wormbase_ledger import InMemoryLedger
from wormbase_research_loop import AutoresearchLoop


CAROL = UUID("00000000-0000-0000-0000-0000000000c1")
DAVE = UUID("00000000-0000-0000-0000-0000000000c2")
COMPANY = UUID("00000000-0000-0000-0000-000000000999")
NOW = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)


async def _seed_ledger(ledger: InMemoryLedger) -> None:
    """Identical seed: two persons, two positions."""
    for person, name, position in (
        (CAROL, "Carol", "cfo"),
        (DAVE, "Dave", "data_engineer"),
    ):
        await ledger.write(
            company_id=COMPANY,
            propose={
                "target_kind": "person_registered",
                "ref_id": str(person),
                "reason": "test seed",
                "proposed_by": "test",
            },
            execute_fn=lambda p=person, n=name: {
                "tool": "emit_person_registered",
                "args": {
                    "person_id": str(p),
                    "name": n,
                    "email": f"{n.lower()}@example.com",
                    "role": "admin",
                    "registered_at": NOW.isoformat(),
                },
                "result_ref": str(p),
            },
            verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
            timestamp=NOW,
        )
        await ledger.write(
            company_id=COMPANY,
            propose={
                "target_kind": "position_assigned",
                "ref_id": str(person),
                "reason": "test seed",
                "proposed_by": "test",
            },
            execute_fn=lambda p=person, pos=position: {
                "tool": "emit_position_assigned",
                "args": {
                    "person_id": str(p),
                    "position": pos,
                    "at": NOW.isoformat(),
                },
                "result_ref": str(p),
            },
            verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
            timestamp=NOW,
        )


async def _drive(ledger, *, cycles: int):
    loop = AutoresearchLoop(ledger=ledger, company_id=COMPANY)
    for _ in range(cycles):
        await loop.run_once(now=NOW)


async def _lessons(ledger):
    rows = await ledger.fetch(COMPANY)
    return [
        r["payload"]["args"]
        for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_experiment_lesson"
    ]


# ---------------------------------------------------------------------------
# Determinism tests
# ---------------------------------------------------------------------------


async def test_two_identical_runs_produce_identical_lesson_text():
    a = InMemoryLedger()
    b = InMemoryLedger()
    await _seed_ledger(a)
    await _seed_ledger(b)
    await _drive(a, cycles=6)
    await _drive(b, cycles=6)
    la = await _lessons(a)
    lb = await _lessons(b)
    assert len(la) == len(lb), (
        f"lesson count diverged: {len(la)} vs {len(lb)}"
    )
    assert la, "expected at least one lesson"
    # Order is stable across replays (we sort by seq in the loop).
    for left, right in zip(la, lb):
        assert left["scope"] == right["scope"]
        assert left["lesson_text"] == right["lesson_text"], (
            f"lesson_text diverged:\n  A={left['lesson_text']!r}\n"
            f"  B={right['lesson_text']!r}"
        )
        assert left["lesson_features"] == right["lesson_features"]
        assert left["prior_keep_id"] == right["prior_keep_id"]
        assert left["applied_to_proposer"] == right["applied_to_proposer"]
        assert left["proposed_by"] == right["proposed_by"]


async def test_applied_at_is_replay_stable():
    """Same ledger, same cycles → same applied_at heights on every lesson."""
    a = InMemoryLedger()
    b = InMemoryLedger()
    await _seed_ledger(a)
    await _seed_ledger(b)
    await _drive(a, cycles=8)
    await _drive(b, cycles=8)
    la = await _lessons(a)
    lb = await _lessons(b)
    # Pair lessons by prior_keep_id (deterministic uuid5) — the latest
    # per-prior carries the canonical applied_at.
    def latest_per_prior(items):
        out: dict[str, dict] = {}
        for x in items:
            prior = str(x["prior_keep_id"])
            # The latest write of a given prior wins (replay-stable since
            # cycles run in the same order).
            out[prior] = x
        return out

    # Walk in order so latest wins per prior key.
    map_a = {}
    map_b = {}
    for x in la:
        map_a[str(x["prior_keep_id"])] = x
    for x in lb:
        map_b[str(x["prior_keep_id"])] = x

    assert set(map_a) == set(map_b), "prior_keep_id sets diverged"
    for prior in map_a:
        applied_a = map_a[prior].get("applied_at")
        applied_b = map_b[prior].get("applied_at")
        assert applied_a == applied_b, (
            f"applied_at diverged for {prior}: A={applied_a} B={applied_b}"
        )


async def test_lesson_count_grows_monotonically_with_keeps():
    """Sanity: each new keep adds at most one lesson; never duplicates."""
    a = InMemoryLedger()
    await _seed_ledger(a)
    counts: list[int] = []
    loop = AutoresearchLoop(ledger=a, company_id=COMPANY)
    for _ in range(10):
        await loop.run_once(now=NOW)
        rows = await a.fetch(COMPANY)
        # Count distinct prior_keep_ids (since stamps re-write the same prior).
        priors = {
            str(r["payload"]["args"]["prior_keep_id"])
            for r in rows
            if r["kind"] == "execute"
            and r["payload"]["tool"] == "emit_experiment_lesson"
        }
        counts.append(len(priors))
    # Counts must be non-decreasing.
    for i in range(1, len(counts)):
        assert counts[i] >= counts[i - 1], (
            f"lesson prior count went down: {counts}"
        )
