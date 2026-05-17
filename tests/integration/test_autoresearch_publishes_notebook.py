"""F7 — Autoresearch keep → published notebook.

Each "keep" experiment from the autoresearch loop publishes a notebook
(propose + run + publish). The notebook owner is the Person the loop ran
for (PRD §16.7). Container-free — uses InMemoryLedger.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_research_loop import AutoresearchLoop, PersonPosition

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_autoresearch_keep_publishes_notebook() -> None:
    ledger = InMemoryLedger()
    company_id = uuid4()
    person_id = uuid4()

    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    pp = PersonPosition(person_id=person_id, position_id="cfo")

    # Drive enough cycles that at least one keep happens. The deterministic
    # outcome rule is hash(experiment_id) % 5 < 3 → 60% keep, so on average
    # 3 of every 5 cycles will keep. Five cycles → at least 1 keep.
    now = datetime.now(UTC)
    keeps = 0
    for cycle in range(5):
        loop.cycle_count = cycle
        ran = await loop._run_for_person(pp, now=now)
        if ran:
            # Check whether the resolve outcome was keep.
            rows = await ledger.fetch(company_id)
            resolved_args = [
                r["payload"]["args"]
                for r in rows
                if r["kind"] == "execute"
                and r["payload"].get("tool") == "emit_experiment_resolved"
            ]
            if resolved_args and resolved_args[-1].get("outcome") == "keep":
                keeps += 1

    assert keeps >= 1, "expected at least one keep across 5 cycles"

    rows = await ledger.fetch(company_id)
    tools = [
        r["payload"].get("tool")
        for r in rows
        if r["kind"] == "execute"
    ]
    assert "emit_notebook_proposed" in tools
    assert "emit_notebook_run" in tools
    assert "emit_notebook_published" in tools

    # The published notebook must owner == the person we ran the loop for.
    publish_args = [
        r["payload"]["args"]
        for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_notebook_published"
    ]
    assert any(
        args["owner_person_id"] == str(person_id) for args in publish_args
    )


@pytest.mark.asyncio
async def test_autoresearch_discard_does_not_publish_notebook() -> None:
    """A discard cycle should NOT trigger a notebook publish."""
    ledger = InMemoryLedger()
    company_id = uuid4()
    person_id = uuid4()
    loop = AutoresearchLoop(ledger=ledger, company_id=company_id)
    pp = PersonPosition(person_id=person_id, position_id="cfo")
    now = datetime.now(UTC)

    # Find a cycle that produces a discard outcome (40% so 1-2 of 5).
    discard_cycle = None
    for cycle in range(20):
        loop.cycle_count = cycle
        # Pre-compute the outcome before actually running so we can pick
        # only a discard cycle for this test.
        from wormbase_core.positions import position_candidates

        candidates = position_candidates("cfo")
        candidate = loop._pick_candidate(pp, candidates)
        # This mirrors the deterministic experiment_id derivation in
        # _run_cycle_for; if it diverges, this test will need updating.
        from uuid import uuid5

        from wormbase_research_loop.loop import _EXPERIMENT_NAMESPACE

        experiment_id = uuid5(
            _EXPERIMENT_NAMESPACE,
            f"{pp.person_id}:{cycle}:{candidate.candidate_id}",
        )
        outcome, _, _ = AutoresearchLoop._resolve(experiment_id, candidate)
        if outcome == "discard":
            discard_cycle = cycle
            break

    if discard_cycle is None:
        pytest.skip("no discard cycle in the first 20 — random skipped")

    loop.cycle_count = discard_cycle
    await loop._run_for_person(pp, now=now)

    rows = await ledger.fetch(company_id)
    # No notebook publish from a discard cycle.
    publishes = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_notebook_published"
    ]
    assert len(publishes) == 0
