"""Tests for ``KeepRatePublishReactivity`` (Block F.4, Wave C₁).

Fourth and final Reactivity in Block F. Wires the previously-unwired
``KeepRatePublisher`` (lifted in D.1) as a Reactivity. Predicate is
``EntryKind("experiment_resolved")``; condition is
``Periodic(86_400) & NotRecentlyFired(hours=24)`` for at-most-once-per-
day fire; fire delegates to ``publisher.publish_for_day(today)``.

Closes the live wiring gap the spike identified — composite_score
curves now actually populate from the ledger trail of resolved
experiments.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_reactivities import ReactivityRegistry
from wormbase_reactivities.protocol import (
    Reactivity,
    ReactivityContext,
    ReactivityResult,
)
from wormbase_research_loop.keep_rate import KeepRatePublisher
from wormbase_research_loop.reactivities import KeepRatePublishReactivity

PERSON_A = "00000000-0000-0000-0000-0000000000aa"
DAY = date(2026, 5, 3)
NOW = datetime(2026, 5, 3, 10, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_resolution(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    experiment_id: str,
    audience: str = "company",
    outcome: str = "keep",
    ts: datetime = NOW,
) -> None:
    """Seed a propose+resolve pair so the publisher sees a complete cycle."""
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "experiment_proposed",
            "ref_id": experiment_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_experiment_proposed",
            "args": {
                "experiment_id": experiment_id,
                "audience": audience,
                "headline_metric": "metric",
                "for_person_id": PERSON_A,
                "position": "cfo",
                "proposed_change": {},
                "expected_delta": -0.1,
                "proposed_at": ts.isoformat(),
            },
            "result_ref": experiment_id,
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed propose"},
        timestamp=ts,
    )
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "experiment_resolved",
            "ref_id": experiment_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_experiment_resolved",
            "args": {
                "experiment_id": experiment_id,
                "outcome": outcome,
                "observed_delta": -0.05,
                "rationale": "seed",
                "resolved_at": ts.isoformat(),
            },
            "result_ref": experiment_id,
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed resolve"},
        timestamp=ts,
    )


def _ctx(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    state: dict[str, Any] | None = None,
    registry: ReactivityRegistry | None = None,
) -> tuple[ReactivityRegistry | None, ReactivityContext]:
    state = state or {"now": NOW}

    def _now() -> datetime:
        return state["now"]

    if registry is None and state.get("with_registry", True):
        registry = ReactivityRegistry(
            ledger=ledger, company_id=company_id, now=_now,
        )
    return registry, ReactivityContext(
        ledger=ledger,
        company_id=company_id,
        registry=registry,
        now=_now,
        extras={"reactivity_id": "keep_rate_publish"},
    )


def _entry(
    kind: str = "experiment_resolved",
    *,
    args: dict[str, Any] | None = None,
    ts: datetime | None = None,
    seq: int = 1,
) -> dict[str, Any]:
    return {
        "kind": "execute",
        "seq": seq,
        "ts": ts or NOW,
        "payload": {"tool": f"emit_{kind}", "args": args or {}},
    }


def _published_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_metrics_keep_rate_published"
    ]


# ---------------------------------------------------------------------------
# Protocol satisfaction + identity
# ---------------------------------------------------------------------------


async def test_satisfies_reactivity_protocol(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    r = KeepRatePublishReactivity()
    assert isinstance(r, Reactivity)
    assert r.id == "keep_rate_publish"
    assert r.scope == "company"


# ---------------------------------------------------------------------------
# Predicate — matches experiment_resolved, rejects all other kinds
# ---------------------------------------------------------------------------


async def test_predicate_matches_experiment_resolved(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    r = KeepRatePublishReactivity()
    _, ctx = _ctx(ledger, company_id)
    assert await r.predicate.match(_entry("experiment_resolved"), ctx) is True


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
        "metrics_keep_rate_published",  # don't fire on own output
    ],
)
async def test_predicate_rejects_other_kinds(
    ledger: InMemoryLedger, company_id: UUID, kind: str,
) -> None:
    r = KeepRatePublishReactivity()
    _, ctx = _ctx(ledger, company_id)
    assert await r.predicate.match(_entry(kind), ctx) is False, (
        f"expected miss for {kind}"
    )


# ---------------------------------------------------------------------------
# Fire — calls publisher.publish_for_day with today's date
# ---------------------------------------------------------------------------


async def test_fire_publishes_for_today(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """End-to-end fire: ledger gains one published row per scope for today."""
    await _seed_resolution(
        ledger, company_id, experiment_id="e1",
        audience="company", outcome="keep", ts=NOW,
    )
    await _seed_resolution(
        ledger, company_id, experiment_id="e2",
        audience=f"person:{PERSON_A}", outcome="discard", ts=NOW,
    )

    publisher = KeepRatePublisher(ledger, company_id)
    r = KeepRatePublishReactivity(publisher=publisher)
    _, ctx = _ctx(ledger, company_id)

    result = await r.fire(_entry("experiment_resolved"), ctx)

    assert isinstance(result, ReactivityResult)
    assert result.fired is True
    assert result.novelty_key == "keep_rate_publish"

    # The publisher writes one entry per scope (person/team/company).
    rows = await ledger.fetch(company_id)
    pubs = _published_rows(rows)
    scopes_published = {
        (r["payload"].get("args") or {}).get("scope") for r in pubs
    }
    assert scopes_published == {"person", "team", "company"}


async def test_fire_uses_publisher_today_from_context_now(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """``today`` is derived from ``context.now``, not wall-clock."""
    state = {"now": datetime(2026, 5, 3, 23, 30, tzinfo=UTC)}
    await _seed_resolution(
        ledger, company_id, experiment_id="e1", ts=state["now"],
    )
    publisher = KeepRatePublisher(ledger, company_id)
    r = KeepRatePublishReactivity(publisher=publisher)
    _, ctx = _ctx(ledger, company_id, state=state)

    await r.fire(_entry("experiment_resolved", ts=state["now"]), ctx)

    rows = await ledger.fetch(company_id)
    pubs = _published_rows(rows)
    days_published = {
        (r["payload"].get("args") or {}).get("day") for r in pubs
    }
    assert days_published == {"2026-05-03"}, (
        f"expected day=2026-05-03 (from context.now), got {days_published}"
    )


async def test_fire_payload_shape_matches_pre_lift_publisher(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """The metrics_keep_rate_published payload has the same keys + types
    the pre-lift publisher produced. F.4 acceptance bullet: shape-identical
    to pre-lift output, no new entry kinds.
    """
    await _seed_resolution(
        ledger, company_id, experiment_id="e1", outcome="keep", ts=NOW,
    )
    publisher = KeepRatePublisher(ledger, company_id)
    r = KeepRatePublishReactivity(publisher=publisher)
    _, ctx = _ctx(ledger, company_id)

    await r.fire(_entry("experiment_resolved"), ctx)

    rows = await ledger.fetch(company_id)
    pubs = _published_rows(rows)
    assert pubs, "expected at least one metrics_keep_rate_published row"

    expected_keys = {
        "scope", "day", "kept", "total", "ratio",
        "published_by", "published_at",
    }
    for row in pubs:
        args = row["payload"].get("args") or {}
        assert expected_keys.issubset(set(args.keys())), (
            f"missing keys: {expected_keys - set(args.keys())}"
        )
        assert isinstance(args["scope"], str)
        assert isinstance(args["day"], str)
        assert isinstance(args["kept"], int)
        assert isinstance(args["total"], int)
        assert isinstance(args["ratio"], float)
        assert isinstance(args["published_by"], str)
        # published_at can be str (JSON) or datetime; both are pre-lift shapes.
        assert args["published_at"] is not None


# ---------------------------------------------------------------------------
# Condition — at most one fire per day via Periodic & NotRecentlyFired
# ---------------------------------------------------------------------------


async def test_condition_allows_first_fire_then_denies_within_day(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Two ``experiment_resolved`` arriving 1h apart → condition allows
    the first, denies the second. F.4 acceptance bullet.

    We exercise the condition directly (not the runner) so the test is
    self-contained — the runner integration is covered by registry tests.
    """
    state = {"now": NOW}
    registry, ctx = _ctx(ledger, company_id, state=state)
    r = KeepRatePublishReactivity()
    ctx.extras["novelty_key"] = "keep_rate_publish"

    # First fire: nothing recorded yet → allow.
    assert await r.condition.allows(_entry("experiment_resolved"), ctx) is True

    # Simulate the registry recording the fire.
    registry._mem_fires[("keep_rate_publish", "keep_rate_publish")] = (  # noqa: SLF001
        state["now"]
    )

    # 1h later — same UTC day → both Periodic and NotRecentlyFired deny.
    state["now"] = state["now"] + timedelta(hours=1)
    assert await r.condition.allows(_entry("experiment_resolved"), ctx) is False


async def test_condition_allows_again_after_period_rolls(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """After 24h+, both Periodic (new bucket) and NotRecentlyFired
    (outside window) re-allow.
    """
    state = {"now": NOW}
    registry, ctx = _ctx(ledger, company_id, state=state)
    r = KeepRatePublishReactivity()
    ctx.extras["novelty_key"] = "keep_rate_publish"

    registry._mem_fires[("keep_rate_publish", "keep_rate_publish")] = (  # noqa: SLF001
        state["now"]
    )

    # Roll past the period — 25h later, next UTC day, outside the
    # NotRecentlyFired window.
    state["now"] = state["now"] + timedelta(hours=25)
    assert await r.condition.allows(_entry("experiment_resolved"), ctx) is True


# ---------------------------------------------------------------------------
# Idempotency under burst — publisher dedup belt-and-braces
# ---------------------------------------------------------------------------


async def test_publisher_dedup_is_belt_and_braces(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Two fires for the same UTC day produce one published row per scope.

    Even if the registry's condition gating somehow misses (hypothetical),
    the publisher's own (scope, day) dedup keeps the ledger clean.
    """
    await _seed_resolution(
        ledger, company_id, experiment_id="e1", ts=NOW,
    )
    publisher = KeepRatePublisher(ledger, company_id)
    r = KeepRatePublishReactivity(publisher=publisher)
    _, ctx = _ctx(ledger, company_id)

    await r.fire(_entry("experiment_resolved", seq=1), ctx)
    await r.fire(_entry("experiment_resolved", seq=2), ctx)

    rows = await ledger.fetch(company_id)
    pubs = _published_rows(rows)
    # Three scopes × one day = exactly three rows.
    assert len(pubs) == 3


# ---------------------------------------------------------------------------
# Lazy publisher construction — F.4 spec allows passing one or building
# from context. The default (no publisher injected) wires from context.
# ---------------------------------------------------------------------------


async def test_fire_constructs_publisher_from_context_when_not_injected(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    await _seed_resolution(
        ledger, company_id, experiment_id="e1", ts=NOW,
    )
    r = KeepRatePublishReactivity()  # no publisher injected
    _, ctx = _ctx(ledger, company_id)

    result = await r.fire(_entry("experiment_resolved"), ctx)
    assert result.fired is True

    rows = await ledger.fetch(company_id)
    assert _published_rows(rows), (
        "expected publisher to be lazily constructed from context"
    )


# ---------------------------------------------------------------------------
# No new entry kinds — F.4 invariant
# ---------------------------------------------------------------------------


async def test_no_new_entry_kinds_introduced(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Fire produces only ``metrics_keep_rate_published`` entries — the
    same kind the pre-lift publisher emitted. No new tools.
    """
    await _seed_resolution(
        ledger, company_id, experiment_id="e1", ts=NOW,
    )
    pre_rows = await ledger.fetch(company_id)
    pre_tools = {
        r["payload"].get("tool") for r in pre_rows
        if r["kind"] == "execute"
    }

    publisher = KeepRatePublisher(ledger, company_id)
    r = KeepRatePublishReactivity(publisher=publisher)
    _, ctx = _ctx(ledger, company_id)
    await r.fire(_entry("experiment_resolved"), ctx)

    post_rows = await ledger.fetch(company_id)
    post_tools = {
        r["payload"].get("tool") for r in post_rows
        if r["kind"] == "execute"
    }
    new_tools = post_tools - pre_tools
    assert new_tools <= {"emit_metrics_keep_rate_published"}, (
        f"unexpected new entry kinds: {new_tools}"
    )
