"""Tests for ``ExperimentResolveReactivity`` (Block F.2, Wave C₁).

Second Reactivity in Block F. Predicate is ``EntryKind("experiment_run")``;
condition is ``NotRecentlyFired(seconds=60)`` belt-and-braces; fire calls
``resolve_experiment`` (which idempotently emits ``experiment_resolved``)
and, on outcome=keep, ``publish_keep_notebook``.

This Reactivity exists as **idempotency insurance** for ``experiment_run``
entries written outside the ``ExperimentTriggerReactivity.fire`` path
(replays, future external triggers). The ledger-side dedup inside
``resolve_experiment`` is the authoritative one — running the Reactivity
twice on the same ``experiment_id`` produces exactly one
``experiment_resolved`` row.
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
from wormbase_research_loop.loop import (
    _EXPERIMENT_NAMESPACE,
    AutoresearchLoop,
    PersonPosition,
)
from wormbase_research_loop.reactivities import (
    ExperimentResolveReactivity,
    publish_keep_notebook,
    resolve_experiment,
)

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


async def _emit_propose_and_run(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    person_id: UUID,
    position_id: str,
    candidate_idx: int = 0,
    seed_extra: str = "",
    now: datetime = NOW,
) -> tuple[UUID, dict[str, Any]]:
    """Drive the loop body just enough to emit propose + run rows.

    Returns ``(experiment_id, run_entry)`` so a test can hand-fire the
    resolve Reactivity against the run row exactly as the runner would.
    """
    from wormbase_identity_tracker.positions import (
        get_position,
        position_candidates,
    )

    pp = PersonPosition(person_id=person_id, position_id=position_id)
    candidates = position_candidates(position_id)
    assert candidates, f"position {position_id} has no candidates"
    position = get_position(position_id)
    assert position is not None
    candidate = candidates[candidate_idx % len(candidates)]
    experiment_id = uuid5(
        _EXPERIMENT_NAMESPACE,
        f"resolve-test:{person_id}:{position_id}:{candidate.candidate_id}:{seed_extra}",
    )

    helper = AutoresearchLoop(ledger=ledger, company_id=company_id)
    await helper._emit_proposed(
        pp, candidate, experiment_id, now=now, audience=f"person:{person_id}",
    )
    finished_at = now + timedelta(seconds=60)
    await helper._emit_run(pp, candidate, experiment_id, now, finished_at)

    rows = await ledger.fetch(company_id)
    run_entry = next(
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_experiment_run"
        and (r["payload"].get("args") or {}).get("experiment_id")
        == str(experiment_id)
    )
    return experiment_id, run_entry


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
        extras={"reactivity_id": "experiment_resolve"},
    )


def _entry(kind: str, *, args: dict[str, Any] | None = None, ts: datetime | None = None) -> dict[str, Any]:
    return {
        "kind": "execute",
        "payload": {
            "tool": f"emit_{kind}",
            "args": args or {},
        },
        "ts": ts or NOW,
        "seq": 1,
    }


async def _resolved_rows(
    ledger: InMemoryLedger, company_id: UUID, experiment_id: UUID,
) -> list[dict[str, Any]]:
    rows = await ledger.fetch(company_id)
    return [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_experiment_resolved"
        and (r["payload"].get("args") or {}).get("experiment_id")
        == str(experiment_id)
    ]


# ---------------------------------------------------------------------------
# Protocol satisfaction
# ---------------------------------------------------------------------------


async def test_satisfies_reactivity_protocol(ledger, company_id):
    r = ExperimentResolveReactivity()
    assert isinstance(r, Reactivity)
    assert r.id == "experiment_resolve"


# ---------------------------------------------------------------------------
# Predicate — matches experiment_run, rejects all other kinds
# ---------------------------------------------------------------------------


async def test_predicate_matches_experiment_run(ledger, company_id):
    r = ExperimentResolveReactivity()
    ctx = _ctx(ledger, company_id)
    entry = _entry("experiment_run")
    assert await r.predicate.match(entry, ctx) is True


@pytest.mark.parametrize(
    "kind",
    [
        "experiment_proposed",
        "experiment_resolved",
        "experiment_lesson",
        "phenomenon_gap_detected",
        "metric_observed",
        "chat_received",
        "person_proposed",
        "kpi_proposed",
    ],
)
async def test_predicate_rejects_other_kinds(ledger, company_id, kind):
    r = ExperimentResolveReactivity()
    ctx = _ctx(ledger, company_id)
    entry = _entry(kind)
    assert await r.predicate.match(entry, ctx) is False, (
        f"expected miss for {kind}"
    )


# ---------------------------------------------------------------------------
# Fire — calls resolve_experiment and publishes notebook on keep
# ---------------------------------------------------------------------------


async def test_fire_writes_one_resolved_row(ledger, company_id):
    """End-to-end fire: ledger gains exactly one experiment_resolved row."""
    await _seed_person(ledger, company_id, CAROL, "Carol", "cfo")
    experiment_id, run_entry = await _emit_propose_and_run(
        ledger, company_id, person_id=CAROL, position_id="cfo",
    )

    r = ExperimentResolveReactivity()
    ctx = _ctx(ledger, company_id, now=NOW + timedelta(seconds=120))
    result = await r.fire(run_entry, ctx)

    assert isinstance(result, ReactivityResult)
    assert result.fired is True
    resolved = await _resolved_rows(ledger, company_id, experiment_id)
    assert len(resolved) == 1


async def test_fire_publishes_keep_notebook_on_keep(
    ledger, company_id, monkeypatch,
):
    """Force a keep outcome and assert emit_notebook_published lands."""
    from wormbase_research_loop import loop as loop_module

    def _force_keep(experiment_id, candidate):
        return ("keep", "forced keep for test", float(candidate.expected_delta) * 0.9)

    monkeypatch.setattr(
        loop_module.AutoresearchLoop, "_resolve", staticmethod(_force_keep),
    )

    await _seed_person(ledger, company_id, CAROL, "Carol", "cfo")
    experiment_id, run_entry = await _emit_propose_and_run(
        ledger, company_id, person_id=CAROL, position_id="cfo",
        seed_extra="keep",
    )

    r = ExperimentResolveReactivity()
    ctx = _ctx(ledger, company_id, now=NOW + timedelta(seconds=120))
    result = await r.fire(run_entry, ctx)
    assert result.fired is True

    rows = await ledger.fetch(company_id)
    pubs = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_notebook_published"
    ]
    assert len(pubs) >= 1, "expected emit_notebook_published on keep outcome"


async def test_fire_does_not_publish_notebook_on_discard(
    ledger, company_id, monkeypatch,
):
    """Force a discard outcome — no notebook_published row may land."""
    from wormbase_research_loop import loop as loop_module

    def _force_discard(experiment_id, candidate):
        return (
            "discard",
            "forced discard for test",
            -float(candidate.expected_delta) * 0.2,
        )

    monkeypatch.setattr(
        loop_module.AutoresearchLoop, "_resolve", staticmethod(_force_discard),
    )

    await _seed_person(ledger, company_id, DAVE, "Dave", "data_engineer")
    experiment_id, run_entry = await _emit_propose_and_run(
        ledger, company_id, person_id=DAVE, position_id="data_engineer",
        seed_extra="discard",
    )

    r = ExperimentResolveReactivity()
    ctx = _ctx(ledger, company_id, now=NOW + timedelta(seconds=120))
    result = await r.fire(run_entry, ctx)
    assert result.fired is True

    rows = await ledger.fetch(company_id)
    pubs = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_notebook_published"
    ]
    assert pubs == [], "discard outcome must NOT publish a notebook"


# ---------------------------------------------------------------------------
# Idempotency — ledger-side dedup inside resolve_experiment
# ---------------------------------------------------------------------------


async def test_resolve_experiment_is_idempotent(ledger, company_id):
    """Two fires for the same experiment_id produce exactly one resolved row."""
    await _seed_person(ledger, company_id, CAROL, "Carol", "cfo")
    experiment_id, run_entry = await _emit_propose_and_run(
        ledger, company_id, person_id=CAROL, position_id="cfo",
        seed_extra="idem",
    )

    r = ExperimentResolveReactivity()
    ctx = _ctx(ledger, company_id, now=NOW + timedelta(seconds=120))

    res1 = await r.fire(run_entry, ctx)
    res2 = await r.fire(run_entry, ctx)

    assert res1.fired is True
    # Second fire still returns fired=True (resolve was attempted) but
    # writes nothing new — the ledger-side dedup short-circuits the
    # _emit_resolved write.
    assert res2.fired is True

    resolved = await _resolved_rows(ledger, company_id, experiment_id)
    assert len(resolved) == 1, (
        "ledger-side dedup must keep exactly one resolved row across two "
        "fires of the same experiment_id"
    )


async def test_two_runs_same_proposal_produce_one_resolved(
    ledger, company_id,
):
    """Per the F.2 spec acceptance bullet — a second ``experiment_run`` row
    for the same experiment_id (e.g. replay or external trigger) must NOT
    duplicate the resolved row.
    """
    await _seed_person(ledger, company_id, CAROL, "Carol", "cfo")
    experiment_id, run_entry_a = await _emit_propose_and_run(
        ledger, company_id, person_id=CAROL, position_id="cfo",
        seed_extra="dup-a",
    )

    # Synthesise a *second* run row for the same experiment_id, simulating
    # an external trigger or replay landing a duplicate.
    run_entry_b = dict(run_entry_a)
    run_entry_b["seq"] = (run_entry_a.get("seq") or 0) + 1

    r = ExperimentResolveReactivity()
    ctx = _ctx(ledger, company_id, now=NOW + timedelta(seconds=120))
    await r.fire(run_entry_a, ctx)
    await r.fire(run_entry_b, ctx)

    resolved = await _resolved_rows(ledger, company_id, experiment_id)
    assert len(resolved) == 1


async def test_resolve_experiment_module_helper_idempotency(
    ledger, company_id,
):
    """The dedup lives in ``resolve_experiment``, not in the Reactivity.

    Calling the module helper directly twice on the same run also produces
    one resolved row.
    """
    await _seed_person(ledger, company_id, CAROL, "Carol", "cfo")
    experiment_id, run_entry = await _emit_propose_and_run(
        ledger, company_id, person_id=CAROL, position_id="cfo",
        seed_extra="helper-idem",
    )

    res1 = await resolve_experiment(
        ledger=ledger, company_id=company_id, run_entry=run_entry,
        now=NOW + timedelta(seconds=120),
    )
    res2 = await resolve_experiment(
        ledger=ledger, company_id=company_id, run_entry=run_entry,
        now=NOW + timedelta(seconds=180),
    )

    assert res1.experiment_id == experiment_id
    assert res2.experiment_id == experiment_id
    # The two return values must agree on outcome (the second call returns
    # the already-resolved record unchanged, per spec).
    assert res1.outcome == res2.outcome
    assert res1.observed_delta == res2.observed_delta

    resolved = await _resolved_rows(ledger, company_id, experiment_id)
    assert len(resolved) == 1


# ---------------------------------------------------------------------------
# Skip paths — no resolved row when run row is malformed / unknown
# ---------------------------------------------------------------------------


async def test_fire_skips_when_run_payload_missing_experiment_id(
    ledger, company_id,
):
    """A malformed ``experiment_run`` row (no experiment_id) is a skip, not a crash."""
    r = ExperimentResolveReactivity()
    ctx = _ctx(ledger, company_id)
    entry = _entry("experiment_run", args={})
    pre_rows = await ledger.fetch(company_id)
    pre_count = len(pre_rows)

    result = await r.fire(entry, ctx)
    assert result.fired is False

    post_rows = await ledger.fetch(company_id)
    assert len(post_rows) == pre_count


async def test_fire_skips_when_no_matching_proposed_row(
    ledger, company_id,
):
    """An ``experiment_run`` row pointing at an unknown experiment_id is skipped.

    Resolving requires the proposed row to reconstruct the candidate /
    metric for arbitration. Without it the reactivity emits nothing.
    """
    r = ExperimentResolveReactivity()
    ctx = _ctx(ledger, company_id)
    eid = uuid5(_EXPERIMENT_NAMESPACE, "unknown-exp")
    entry = _entry(
        "experiment_run",
        args={
            "experiment_id": str(eid),
            "started_at": NOW.isoformat(),
            "finished_at": (NOW + timedelta(seconds=60)).isoformat(),
            "log": {"candidate_id": "x", "position": "cfo", "person_id": str(CAROL)},
        },
    )
    pre_rows = await ledger.fetch(company_id)
    pre_count = len(pre_rows)

    result = await r.fire(entry, ctx)
    assert result.fired is False

    post_rows = await ledger.fetch(company_id)
    assert len(post_rows) == pre_count


# ---------------------------------------------------------------------------
# publish_keep_notebook helper — only fires for keep
# ---------------------------------------------------------------------------


async def test_publish_keep_notebook_helper_writes_artifact(
    ledger, company_id, monkeypatch,
):
    """The standalone ``publish_keep_notebook`` helper writes the notebook
    artifact when handed a keep resolution.
    """
    from wormbase_research_loop import loop as loop_module

    def _force_keep(experiment_id, candidate):
        return ("keep", "forced keep", float(candidate.expected_delta) * 0.9)

    monkeypatch.setattr(
        loop_module.AutoresearchLoop, "_resolve", staticmethod(_force_keep),
    )

    await _seed_person(ledger, company_id, CAROL, "Carol", "cfo")
    experiment_id, run_entry = await _emit_propose_and_run(
        ledger, company_id, person_id=CAROL, position_id="cfo",
        seed_extra="pub-helper",
    )

    resolution = await resolve_experiment(
        ledger=ledger, company_id=company_id, run_entry=run_entry,
        now=NOW + timedelta(seconds=120),
    )
    assert resolution.outcome == "keep"

    await publish_keep_notebook(
        ledger=ledger, company_id=company_id, resolution=resolution,
        now=NOW + timedelta(seconds=180),
    )

    rows = await ledger.fetch(company_id)
    pubs = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_notebook_published"
    ]
    assert len(pubs) >= 1
