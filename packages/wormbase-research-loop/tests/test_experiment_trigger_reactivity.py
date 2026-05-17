"""Tests for ``ExperimentTriggerReactivity`` (Block F.1, Wave C₁).

The Reactivity wraps the lifted Block B helpers (``AutoresearchLoop``'s
``_emit_proposed``/``_emit_run``/``_emit_resolved``/``_publish_keep_notebook``)
as a W5a-style Reactivity. Predicate is OR over five upstream entry kinds;
condition is per-scope DailyBudget + NotRecentlyFired. Fire writes the
full propose → run → resolve sequence, plus the keep-notebook publish on
``outcome == "keep"``. Skips on budget / cooldown emit nothing — the
acceptance bullet "no new entry kinds" is enforced.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.protocol import (
    Reactivity,
    ReactivityContext,
    ReactivityResult,
)
from wormbase_reactivities.registry import ReactivityRegistry
from wormbase_research_loop.reactivities import ExperimentTriggerReactivity

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


def _entry(kind: str, *, args: dict[str, Any] | None = None, ts: datetime | None = None) -> dict[str, Any]:
    """Build a synthetic execute envelope for a given trailing-emit kind."""
    return {
        "kind": "execute",
        "payload": {
            "tool": f"emit_{kind}",
            "args": args or {},
        },
        "ts": ts or NOW,
        "seq": 1,
    }


def _ctx(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    registry: Any = None,
    now: datetime = NOW,
) -> ReactivityContext:
    return ReactivityContext(
        ledger=ledger,
        company_id=company_id,
        registry=registry,
        now=lambda: now,
        extras={"reactivity_id": "experiment_trigger"},
    )


# ---------------------------------------------------------------------------
# Protocol satisfaction + registration
# ---------------------------------------------------------------------------


async def test_satisfies_reactivity_protocol(ledger, company_id):
    r = ExperimentTriggerReactivity()
    assert isinstance(r, Reactivity)
    assert r.id == "experiment_trigger"


async def test_registers_cleanly_with_reactivity_registry(ledger, company_id):
    """Smoke: register + list returns the expected binding."""
    r = ExperimentTriggerReactivity()
    reg = ReactivityRegistry(ledger=ledger, company_id=company_id, now=lambda: NOW)
    reg.register(r)
    bindings = reg.list()
    ids = {b.id for b in bindings}
    assert "experiment_trigger" in ids


# ---------------------------------------------------------------------------
# Predicate — OR over five kinds (and rejects others)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "phenomenon_gap_detected",
        "metric_observed",
        "experiment_lesson",
        "experiment_resolved",
        "chat_received",
    ],
)
async def test_predicate_matches_each_upstream_kind(ledger, company_id, kind):
    r = ExperimentTriggerReactivity()
    ctx = _ctx(ledger, company_id)
    entry = _entry(kind)
    assert await r.predicate.match(entry, ctx) is True, f"expected match for {kind}"


@pytest.mark.parametrize(
    "kind",
    [
        "person_proposed",
        "source_proposed",
        "kpi_proposed",
        "experiment_proposed",  # propose, not the trigger kinds
        "experiment_run",
    ],
)
async def test_predicate_rejects_unrelated_kinds(ledger, company_id, kind):
    r = ExperimentTriggerReactivity()
    ctx = _ctx(ledger, company_id)
    entry = _entry(kind)
    assert await r.predicate.match(entry, ctx) is False, f"expected miss for {kind}"


# ---------------------------------------------------------------------------
# Condition — DailyBudget + NotRecentlyFired
# ---------------------------------------------------------------------------


async def test_condition_skips_when_daily_budget_exhausted(ledger, company_id):
    """When the registry records `(scope_kind, scope_id)` already at the
    budget, ``condition.allows`` returns False so dispatch never fires."""
    r = ExperimentTriggerReactivity(per_scope_daily_budget=2)
    reg = ReactivityRegistry(ledger=ledger, company_id=company_id, now=lambda: NOW)
    reg.register(r)
    # The reactivity routes its budget against the per-tenant axis (scope key
    # = company_id stringified). Pre-load the counter to the cap.
    day = NOW.date().isoformat()
    for _ in range(2):
        await reg._inc_budget(  # type: ignore[attr-defined]
            reactivity_id=r.id,
            axis="tenant",
            key=str(company_id),
            day=day,
            by=1,
        )
    entry = _entry("phenomenon_gap_detected", args={"novelty_key": "x"})
    fired = await reg.dispatch(entry)
    assert fired == [], "over-budget — must not fire"


async def test_condition_skips_when_recently_fired(ledger, company_id):
    """Two dispatches inside the cooldown window — second one suppressed."""
    r = ExperimentTriggerReactivity(
        per_scope_daily_budget=10,
        recently_fired_window_seconds=300,
    )
    state = {"now": NOW}
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=lambda: state["now"],
    )
    reg.register(r)
    # Seed a person so the fire body has a position to drive against.
    await _seed_person(ledger, company_id, CAROL, "Carol", "cfo")

    entry = _entry(
        "phenomenon_gap_detected",
        args={"person_id": str(CAROL), "novelty_key": "k1"},
    )
    fired1 = await reg.dispatch(entry)
    assert fired1 == [r.id], "first fire should land"

    # Re-dispatch immediately — within the cooldown window.
    fired2 = await reg.dispatch(entry)
    assert fired2 == [], "second fire suppressed by NotRecentlyFired"


# ---------------------------------------------------------------------------
# Fire body — calls the full propose → run → resolve sequence
# ---------------------------------------------------------------------------


async def _experiment_seq(ledger: InMemoryLedger, company_id: UUID) -> dict[str, list[dict[str, Any]]]:
    """Group emitted experiment_* execute rows by their tool name."""
    rows = await ledger.fetch(company_id)
    by_tool: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r["kind"] != "execute":
            continue
        tool = r["payload"].get("tool", "")
        if tool in (
            "emit_experiment_proposed",
            "emit_experiment_run",
            "emit_experiment_resolved",
        ):
            by_tool.setdefault(tool, []).append(r)
    return by_tool


async def test_fire_writes_propose_run_resolve_sequence(ledger, company_id):
    """End-to-end fire: ledger gains exactly one propose+run+resolve triple."""
    await _seed_person(ledger, company_id, CAROL, "Carol", "cfo")
    r = ExperimentTriggerReactivity()
    ctx = _ctx(ledger, company_id)
    entry = _entry(
        "phenomenon_gap_detected",
        args={"person_id": str(CAROL), "novelty_key": "kpi:nps"},
    )

    result = await r.fire(entry, ctx)

    assert isinstance(result, ReactivityResult)
    assert result.fired is True

    by_tool = await _experiment_seq(ledger, company_id)
    assert len(by_tool.get("emit_experiment_proposed", [])) == 1
    assert len(by_tool.get("emit_experiment_run", [])) == 1
    assert len(by_tool.get("emit_experiment_resolved", [])) == 1

    # Sequence ordering: proposed.seq < run.seq < resolved.seq
    proposed_seq = by_tool["emit_experiment_proposed"][0]["seq"]
    run_seq = by_tool["emit_experiment_run"][0]["seq"]
    resolved_seq = by_tool["emit_experiment_resolved"][0]["seq"]
    assert proposed_seq < run_seq < resolved_seq


async def test_fire_publishes_keep_notebook_when_outcome_is_keep(
    ledger, company_id, monkeypatch,
):
    """Force a keep outcome via monkeypatch and assert notebook_published lands."""
    from wormbase_research_loop import loop as loop_module

    def _force_keep(experiment_id, candidate):
        return ("keep", "forced keep for test", float(candidate.expected_delta) * 0.9)

    monkeypatch.setattr(
        loop_module.AutoresearchLoop, "_resolve", staticmethod(_force_keep),
    )

    await _seed_person(ledger, company_id, CAROL, "Carol", "cfo")
    r = ExperimentTriggerReactivity()
    ctx = _ctx(ledger, company_id)
    entry = _entry(
        "phenomenon_gap_detected",
        args={"person_id": str(CAROL), "novelty_key": "kpi:nps:keep"},
    )

    result = await r.fire(entry, ctx)
    assert result.fired is True

    rows = await ledger.fetch(company_id)
    pubs = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_notebook_published"
    ]
    assert len(pubs) >= 1, "expected emit_notebook_published on keep outcome"


async def test_fire_does_not_publish_notebook_when_outcome_is_discard(
    ledger, company_id, monkeypatch,
):
    """Force a discard outcome — no notebook_published row may land."""
    from wormbase_research_loop import loop as loop_module

    def _force_discard(experiment_id, candidate):
        return ("discard", "forced discard for test", -float(candidate.expected_delta) * 0.2)

    monkeypatch.setattr(
        loop_module.AutoresearchLoop, "_resolve", staticmethod(_force_discard),
    )

    await _seed_person(ledger, company_id, DAVE, "Dave", "data_engineer")
    r = ExperimentTriggerReactivity()
    ctx = _ctx(ledger, company_id)
    entry = _entry(
        "phenomenon_gap_detected",
        args={"person_id": str(DAVE), "novelty_key": "kpi:nps:discard"},
    )

    result = await r.fire(entry, ctx)
    assert result.fired is True

    rows = await ledger.fetch(company_id)
    pubs = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_notebook_published"
    ]
    assert pubs == [], "discard outcome must NOT publish a notebook"


# ---------------------------------------------------------------------------
# "No new entry kinds" — skipped fires must emit nothing
# ---------------------------------------------------------------------------


async def test_skipped_fire_emits_nothing(ledger, company_id):
    """When no person is registered, fire returns fired=False AND writes 0 rows."""
    r = ExperimentTriggerReactivity()
    ctx = _ctx(ledger, company_id)
    pre_rows = await ledger.fetch(company_id)
    pre_count = len(pre_rows)

    entry = _entry(
        "phenomenon_gap_detected",
        args={"person_id": str(uuid4()), "novelty_key": "no-such-person"},
    )
    result = await r.fire(entry, ctx)

    assert result.fired is False
    post_rows = await ledger.fetch(company_id)
    assert len(post_rows) == pre_count, (
        "skip path must not write any ledger rows (no new entry kinds)"
    )


async def test_skipped_fire_when_budget_exhausted_writes_no_marker(
    ledger, company_id,
):
    """Budget-exhausted fire path must not invent a 'skipped' entry."""
    r = ExperimentTriggerReactivity(per_scope_daily_budget=0)
    await _seed_person(ledger, company_id, CAROL, "Carol", "cfo")
    ctx = _ctx(ledger, company_id)
    pre_rows = await ledger.fetch(company_id)
    pre_count = len(pre_rows)

    entry = _entry(
        "phenomenon_gap_detected",
        args={"person_id": str(CAROL), "novelty_key": "any"},
    )
    result = await r.fire(entry, ctx)

    assert result.fired is False
    post_rows = await ledger.fetch(company_id)
    assert len(post_rows) == pre_count, (
        "budget-exhausted skip must NOT write any ledger rows"
    )
