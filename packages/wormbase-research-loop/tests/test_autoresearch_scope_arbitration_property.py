"""Hypothesis property tests for autoresearch scope arbitration (W6.A1).

Invariants
----------
**SA1. Higher-scope dominance.** Within a 7-day window, a ``keep``
outcome at a higher scope ALWAYS supersedes a same-metric ``keep`` at
a lower scope. Specificity-inverted: ``Company > Team > Person``.
``_check_higher_scope_conflict`` returns the highest-rank superseding
audience marker.

**SA2. Apex stability.** Company-scope outcomes are NEVER superseded
(``own_scope="company"`` short-circuits to None).

**SA3. Window respect.** Outcomes older than ``lookback_days`` (default
7) do NOT supersede.

**SA4. Metric isolation.** A higher-scope ``keep`` on metric X does NOT
supersede a lower-scope outcome on metric Y. Arbitration is per-metric.

These are the invariants the dashboard's /research tab relies on to
display scope-coherent experiment outcomes.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from hypothesis import HealthCheck, given, settings, strategies as st

from wormbase_research_loop.loop import (
    _check_higher_scope_conflict,
    _scope_of,
)
from wormbase_ledger import InMemoryLedger


_COMPANY = UUID("00000000-0000-0000-0000-000000000099")
NOW = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helper: write a propose+resolve pair into the ledger so
# _check_higher_scope_conflict has something to walk.
# ---------------------------------------------------------------------------


async def _write_experiment_resolved(
    ledger: InMemoryLedger,
    *,
    audience: str,  # "person:<uuid>" | "team:<uuid>" | "company"
    metric: str,
    outcome: str,
    proposed_at: datetime,
    resolved_at: datetime,
) -> UUID:
    """Emit emit_experiment_proposed + emit_experiment_resolved."""
    experiment_id = uuid4()
    person_id = uuid4()
    await ledger.write(
        company_id=_COMPANY,
        propose={
            "target_kind": "experiment_proposed",
            "ref_id": str(experiment_id),
            "reason": "test",
            "proposed_by": "autoresearch_loop",
        },
        execute_fn=lambda: {
            "tool": "emit_experiment_proposed",
            "args": {
                "experiment_id": str(experiment_id),
                "for_person_id": str(person_id),
                "position": "cfo",
                "headline_metric": metric,
                "proposed_change": {"kind": "noop"},
                "expected_delta": 0.05,
                "proposed_at": proposed_at.isoformat(),
                "audience": audience,
            },
            "result_ref": str(experiment_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        timestamp=proposed_at,
    )
    await ledger.write(
        company_id=_COMPANY,
        propose={
            "target_kind": "experiment_resolved",
            "ref_id": str(experiment_id),
            "reason": "test",
            "proposed_by": "autoresearch_loop",
        },
        execute_fn=lambda: {
            "tool": "emit_experiment_resolved",
            "args": {
                "experiment_id": str(experiment_id),
                "outcome": outcome,
                "observed_delta": 0.04,
                "rationale": "test",
                "resolved_at": resolved_at.isoformat(),
            },
            "result_ref": str(experiment_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        timestamp=resolved_at,
    )
    return experiment_id


# ---------------------------------------------------------------------------
# SA1 — higher-scope dominance
# ---------------------------------------------------------------------------


def _audience_with_scope(scope: str) -> str:
    if scope == "company":
        return "company"
    if scope == "team":
        return f"team:{uuid4()}"
    return f"person:{uuid4()}"


@given(
    higher_scope=st.sampled_from(["team", "company"]),
    lower_scope=st.sampled_from(["person", "team"]),
    metric=st.sampled_from(["revenue", "nps", "retention_m3"]),
)
@settings(max_examples=80, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
def test_higher_scope_keep_supersedes_lower_scope(
    higher_scope: str, lower_scope: str, metric: str,
) -> None:
    """Invariant SA1: a higher-scope keep always supersedes a lower-scope same-metric.

    The arbitrator returns a non-None audience marker iff a higher-rank
    keep on the same metric exists within the lookback window.
    """
    from wormbase_research_loop.loop import _SCOPE_RANK

    if _SCOPE_RANK[higher_scope] <= _SCOPE_RANK[lower_scope]:
        return  # not actually a higher scope

    async def _go() -> str | None:
        ledger = InMemoryLedger()
        higher_audience = _audience_with_scope(higher_scope)
        await _write_experiment_resolved(
            ledger,
            audience=higher_audience,
            metric=metric,
            outcome="keep",
            proposed_at=NOW - timedelta(days=2),
            resolved_at=NOW - timedelta(days=2),
        )
        return await _check_higher_scope_conflict(
            ledger, _COMPANY, metric=metric,
            own_scope=lower_scope, now=NOW,
        )

    result = asyncio.run(_go())
    assert result is not None, (
        f"expected {higher_scope} keep to supersede {lower_scope} on {metric}"
    )
    assert _scope_of(result) == higher_scope


# ---------------------------------------------------------------------------
# SA2 — Company is the apex, never superseded
# ---------------------------------------------------------------------------


@given(other_scope=st.sampled_from(["person", "team"]),
       metric=st.sampled_from(["revenue", "nps"]))
@settings(max_examples=40, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
def test_company_scope_is_never_superseded(
    other_scope: str, metric: str,
) -> None:
    """Invariant SA2: ``own_scope="company"`` short-circuits to None.

    Even if a person or team-scope keep exists, the arbitrator returns
    None when own_scope="company" — Company is the apex and is never
    superseded.
    """

    async def _go() -> str | None:
        ledger = InMemoryLedger()
        other_audience = _audience_with_scope(other_scope)
        await _write_experiment_resolved(
            ledger,
            audience=other_audience,
            metric=metric,
            outcome="keep",
            proposed_at=NOW - timedelta(days=1),
            resolved_at=NOW - timedelta(days=1),
        )
        return await _check_higher_scope_conflict(
            ledger, _COMPANY, metric=metric,
            own_scope="company", now=NOW,
        )

    assert asyncio.run(_go()) is None


# ---------------------------------------------------------------------------
# SA3 — outcomes older than 7 days do not supersede
# ---------------------------------------------------------------------------


@given(days_old=st.integers(min_value=8, max_value=60),
       metric=st.sampled_from(["revenue", "nps"]))
@settings(max_examples=40, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
def test_outcomes_outside_window_do_not_supersede(
    days_old: int, metric: str,
) -> None:
    """Invariant SA3: a keep older than lookback_days returns None.

    The conflict arbitrator's ``cutoff = now - timedelta(days=lookback_days)``
    excludes any keep older than that. A 30-day-old Company keep does NOT
    supersede a fresh Person keep on the same metric.
    """

    async def _go() -> str | None:
        ledger = InMemoryLedger()
        old_at = NOW - timedelta(days=days_old)
        await _write_experiment_resolved(
            ledger,
            audience="company",
            metric=metric,
            outcome="keep",
            proposed_at=old_at,
            resolved_at=old_at,
        )
        return await _check_higher_scope_conflict(
            ledger, _COMPANY, metric=metric,
            own_scope="person", now=NOW, lookback_days=7,
        )

    assert asyncio.run(_go()) is None


# ---------------------------------------------------------------------------
# SA4 — different metric does not supersede
# ---------------------------------------------------------------------------


@given(higher_metric=st.sampled_from(["revenue", "nps", "retention_m3"]),
       lower_metric=st.sampled_from(["revenue", "nps", "retention_m3"]))
@settings(max_examples=60, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
def test_different_metric_does_not_supersede(
    higher_metric: str, lower_metric: str,
) -> None:
    """Invariant SA4: a higher-scope keep on metric X does not supersede metric Y.

    Arbitration is per-metric. If the metrics differ, the arbitrator
    returns None regardless of scope.
    """
    if higher_metric == lower_metric:
        return  # tautology — covered by SA1

    async def _go() -> str | None:
        ledger = InMemoryLedger()
        await _write_experiment_resolved(
            ledger,
            audience="company",
            metric=higher_metric,
            outcome="keep",
            proposed_at=NOW - timedelta(days=1),
            resolved_at=NOW - timedelta(days=1),
        )
        return await _check_higher_scope_conflict(
            ledger, _COMPANY, metric=lower_metric,
            own_scope="person", now=NOW,
        )

    assert asyncio.run(_go()) is None


# ---------------------------------------------------------------------------
# Bonus — multiple kept outcomes pick the HIGHEST rank
# ---------------------------------------------------------------------------


def test_arbitrator_picks_highest_rank_when_team_and_company_both_kept() -> None:
    """Invariant SA1 (max rule): when Team and Company both kept the same
    metric, the arbitrator returns the Company marker (apex).

    Hand-rolled rather than fuzzed because the property is a direct
    pick-the-max rule: max(scope rank) wins, with ties broken by
    enumeration order (Company > Team).
    """

    async def _go() -> str | None:
        ledger = InMemoryLedger()
        team_audience = f"team:{uuid4()}"
        await _write_experiment_resolved(
            ledger, audience=team_audience, metric="revenue",
            outcome="keep",
            proposed_at=NOW - timedelta(days=2),
            resolved_at=NOW - timedelta(days=2),
        )
        await _write_experiment_resolved(
            ledger, audience="company", metric="revenue",
            outcome="keep",
            proposed_at=NOW - timedelta(days=1),
            resolved_at=NOW - timedelta(days=1),
        )
        return await _check_higher_scope_conflict(
            ledger, _COMPANY, metric="revenue",
            own_scope="person", now=NOW,
        )

    result = asyncio.run(_go())
    assert result == "company", (
        f"expected company to win when team+company both kept; got {result!r}"
    )


def test_discard_outcomes_do_not_supersede() -> None:
    """Invariant: a higher-scope ``discard`` does not supersede.

    Only ``keep`` outcomes carry authority. A Company-scope discard on
    metric X does NOT block a Person-scope keep on the same metric.
    """

    async def _go() -> str | None:
        ledger = InMemoryLedger()
        await _write_experiment_resolved(
            ledger, audience="company", metric="revenue",
            outcome="discard",
            proposed_at=NOW - timedelta(days=1),
            resolved_at=NOW - timedelta(days=1),
        )
        return await _check_higher_scope_conflict(
            ledger, _COMPANY, metric="revenue",
            own_scope="person", now=NOW,
        )

    assert asyncio.run(_go()) is None
