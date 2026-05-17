"""Conditions: budget rollover, novelty windows, composability."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from wormbase_reactivities import (
    AlwaysAllow,
    DailyBudget,
    DomainEnabled,
    NotRecentlyFired,
    Periodic,
    ReactivityContext,
    ReactivityRegistry,
)
from wormbase_reactivities.conditions import And, Or


def _now_factory(state: dict) -> object:
    """Return a callable that resolves to the current state['now']."""
    def _now() -> datetime:
        return state["now"]

    return _now


def _ctx(ledger, company_id: UUID, state: dict, reactivity_id: str = "test"):
    now_fn = _now_factory(state)
    registry = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=now_fn,
    )
    return registry, ReactivityContext(
        ledger=ledger,
        company_id=company_id,
        registry=registry,
        now=now_fn,
        extras={"reactivity_id": reactivity_id},
    )


def _entry_with(args: dict[str, Any], seq: int = 1) -> dict[str, Any]:
    return {
        "kind": "execute",
        "seq": seq,
        "payload": {"tool": "emit_x", "args": args},
    }


# ---------------------------------------------------------------------------
# DailyBudget
# ---------------------------------------------------------------------------


async def test_daily_budget_allows_when_under_cap(ledger, company_id: UUID) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    _, ctx = _ctx(ledger, company_id, state)
    cond = DailyBudget(per_owner=3)
    entry = _entry_with({"owner_person_id": "p-1"})
    assert await cond.allows(entry, ctx) is True


async def test_daily_budget_denies_at_per_owner_cap(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    registry, ctx = _ctx(ledger, company_id, state)
    cond = DailyBudget(per_owner=3, per_domain=999, per_tenant=999)
    # Pre-populate the owner counter at cap.
    day = state["now"].date().isoformat()
    await registry._inc_budget(  # noqa: SLF001
        reactivity_id="test", axis="owner", key="p-1", day=day, by=3,
    )
    entry = _entry_with({"owner_person_id": "p-1"})
    assert await cond.allows(entry, ctx) is False


async def test_daily_budget_denies_at_per_domain_cap(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    registry, ctx = _ctx(ledger, company_id, state)
    cond = DailyBudget(per_owner=999, per_domain=2, per_tenant=999)
    day = state["now"].date().isoformat()
    await registry._inc_budget(  # noqa: SLF001
        reactivity_id="test", axis="domain", key="d-1", day=day, by=2,
    )
    entry = _entry_with({"domain_id": "d-1"})
    assert await cond.allows(entry, ctx) is False


async def test_daily_budget_denies_at_per_tenant_cap(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    registry, ctx = _ctx(ledger, company_id, state)
    cond = DailyBudget(per_owner=999, per_domain=999, per_tenant=1)
    day = state["now"].date().isoformat()
    await registry._inc_budget(  # noqa: SLF001
        reactivity_id="test", axis="tenant", key=str(company_id),
        day=day, by=1,
    )
    entry = _entry_with({"owner_person_id": "p-1"})
    assert await cond.allows(entry, ctx) is False


async def test_daily_budget_rolls_over_at_midnight(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 23, 59, tzinfo=UTC)}
    registry, ctx = _ctx(ledger, company_id, state)
    cond = DailyBudget(per_tenant=1)
    # Burn the day's budget.
    day_today = state["now"].date().isoformat()
    await registry._inc_budget(  # noqa: SLF001
        reactivity_id="test", axis="tenant", key=str(company_id),
        day=day_today, by=1,
    )
    entry = _entry_with({"owner_person_id": "p-1"})
    assert await cond.allows(entry, ctx) is False
    # Cross midnight.
    state["now"] = datetime(2026, 4, 29, 0, 1, tzinfo=UTC)
    assert await cond.allows(entry, ctx) is True


async def test_daily_budget_skips_axis_when_key_missing(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    _, ctx = _ctx(ledger, company_id, state)
    cond = DailyBudget(per_owner=0)  # 0/day on per_owner = always-block
    # Entry has no owner — the per_owner axis is skipped.
    entry = _entry_with({"text": "no owner"})
    assert await cond.allows(entry, ctx) is True


async def test_daily_budget_denies_with_missing_reactivity_id(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    now_fn = _now_factory(state)
    registry = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=now_fn,
    )
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id, registry=registry,
        now=now_fn, extras={},  # NO reactivity_id
    )
    cond = DailyBudget()
    assert await cond.allows(_entry_with({"owner_person_id": "p-1"}), ctx) is False


async def test_daily_budget_with_no_registry_passes_through(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    now_fn = _now_factory(state)
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id, registry=None,
        now=now_fn, extras={"reactivity_id": "test"},
    )
    cond = DailyBudget(per_owner=0, per_domain=0, per_tenant=0)
    assert await cond.allows(_entry_with({"owner_person_id": "p-1"}), ctx) is True


# ---------------------------------------------------------------------------
# NotRecentlyFired
# ---------------------------------------------------------------------------


async def test_not_recently_fired_allows_first_time(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    _, ctx = _ctx(ledger, company_id, state)
    cond = NotRecentlyFired("topic:owner", hours=4.0)
    ctx.extras["novelty_key"] = "churn:p-1"
    entry = _entry_with({"topic": "churn"})
    assert await cond.allows(entry, ctx) is True


async def test_not_recently_fired_denies_within_window(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    registry, ctx = _ctx(ledger, company_id, state)
    cond = NotRecentlyFired(hours=4.0)
    ctx.extras["novelty_key"] = "churn:p-1"
    # Record a fire 1h ago.
    registry._mem_fires[("test", "churn:p-1")] = (  # noqa: SLF001
        state["now"] - timedelta(hours=1)
    )
    assert await cond.allows(_entry_with({}), ctx) is False


async def test_not_recently_fired_allows_outside_window(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    registry, ctx = _ctx(ledger, company_id, state)
    cond = NotRecentlyFired(hours=4.0)
    ctx.extras["novelty_key"] = "churn:p-1"
    # Record a fire 5h ago.
    registry._mem_fires[("test", "churn:p-1")] = (  # noqa: SLF001
        state["now"] - timedelta(hours=5)
    )
    assert await cond.allows(_entry_with({}), ctx) is True


async def test_not_recently_fired_no_key_is_vacuously_true(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    _, ctx = _ctx(ledger, company_id, state)
    cond = NotRecentlyFired()  # empty novelty_key
    assert await cond.allows(_entry_with({}), ctx) is True


# ---------------------------------------------------------------------------
# Periodic
# ---------------------------------------------------------------------------


async def test_periodic_allows_first_time(ledger, company_id: UUID) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    _, ctx = _ctx(ledger, company_id, state)
    cond = Periodic(period_seconds=86_400)
    ctx.extras["novelty_key"] = "keep_rate_publish"
    assert await cond.allows(_entry_with({}), ctx) is True


async def test_periodic_denies_in_same_bucket(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    registry, ctx = _ctx(ledger, company_id, state)
    cond = Periodic(period_seconds=86_400)
    ctx.extras["novelty_key"] = "keep_rate_publish"
    # Record a prior fire 1h ago — same UTC day.
    registry._mem_fires[("test", "keep_rate_publish")] = (  # noqa: SLF001
        state["now"] - timedelta(hours=1)
    )
    assert await cond.allows(_entry_with({}), ctx) is False


async def test_periodic_allows_in_next_bucket(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 29, 0, 1, tzinfo=UTC)}
    registry, ctx = _ctx(ledger, company_id, state)
    cond = Periodic(period_seconds=86_400)
    ctx.extras["novelty_key"] = "keep_rate_publish"
    # Prior fire was 23:59 UTC the previous day — a different bucket.
    registry._mem_fires[("test", "keep_rate_publish")] = (  # noqa: SLF001
        datetime(2026, 4, 28, 23, 59, tzinfo=UTC)
    )
    assert await cond.allows(_entry_with({}), ctx) is True


async def test_periodic_no_key_is_vacuously_true(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    _, ctx = _ctx(ledger, company_id, state)
    cond = Periodic(period_seconds=86_400)  # empty novelty_key
    assert await cond.allows(_entry_with({}), ctx) is True


async def test_periodic_with_no_registry_passes_through(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    now_fn = _now_factory(state)
    ctx = ReactivityContext(
        ledger=ledger, company_id=company_id, registry=None,
        now=now_fn, extras={"reactivity_id": "test", "novelty_key": "x"},
    )
    cond = Periodic(period_seconds=86_400)
    assert await cond.allows(_entry_with({}), ctx) is True


async def test_periodic_composes_with_not_recently_fired(
    ledger, company_id: UUID,
) -> None:
    """Two experiment_resolved entries 1h apart → second is gated.

    Mirrors the F.4 KeepRatePublishReactivity composition exactly:
    ``Periodic(86_400) & NotRecentlyFired(hours=24)`` permits the first
    fire and denies the second when both arrive in the same UTC day.
    """
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    registry, ctx = _ctx(ledger, company_id, state)
    cond = Periodic(period_seconds=86_400) & NotRecentlyFired(hours=24)
    ctx.extras["novelty_key"] = "keep_rate_publish"

    # First fire: no prior record, both conditions allow.
    assert await cond.allows(_entry_with({}), ctx) is True

    # Simulate the registry recording the fire.
    registry._mem_fires[("test", "keep_rate_publish")] = state["now"]  # noqa: SLF001

    # Second arrival 1h later — both Periodic (same UTC bucket) and
    # NotRecentlyFired (within 24h) deny.
    state["now"] = state["now"] + timedelta(hours=1)
    assert await cond.allows(_entry_with({}), ctx) is False


# ---------------------------------------------------------------------------
# DomainEnabled
# ---------------------------------------------------------------------------


async def test_domain_enabled_allows_default(ledger, company_id: UUID) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    _, ctx = _ctx(ledger, company_id, state)
    cond = DomainEnabled()
    assert await cond.allows(_entry_with({"domain_id": "d-1"}), ctx) is True


async def test_domain_enabled_denies_disabled_domain(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    registry, ctx = _ctx(ledger, company_id, state)
    registry.disable_domain("d-1")
    cond = DomainEnabled()
    assert await cond.allows(_entry_with({"domain_id": "d-1"}), ctx) is False


async def test_domain_enabled_skips_when_no_domain(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    _, ctx = _ctx(ledger, company_id, state)
    cond = DomainEnabled()
    assert await cond.allows(_entry_with({"text": "no domain"}), ctx) is True


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


async def test_and_short_circuits(ledger, company_id: UUID) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    registry, ctx = _ctx(ledger, company_id, state)
    cond = DailyBudget(per_tenant=0) & DomainEnabled()
    # Tenant cap=0 means always-block.
    assert await cond.allows(_entry_with({"domain_id": "d-1"}), ctx) is False


async def test_or_short_circuits(ledger, company_id: UUID) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    _, ctx = _ctx(ledger, company_id, state)
    cond = DomainEnabled() | DailyBudget(per_tenant=0)
    # First condition allows -> short-circuits to True.
    assert await cond.allows(_entry_with({"domain_id": "d-1"}), ctx) is True


async def test_not_inverts(ledger, company_id: UUID) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    registry, ctx = _ctx(ledger, company_id, state)
    cond = ~DomainEnabled()
    registry.disable_domain("d-1")
    # DomainEnabled would deny; ~ inverts to allow.
    assert await cond.allows(_entry_with({"domain_id": "d-1"}), ctx) is True


async def test_always_allow_returns_true(ledger, company_id: UUID) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    _, ctx = _ctx(ledger, company_id, state)
    cond = AlwaysAllow()
    assert await cond.allows(_entry_with({}), ctx) is True


async def test_empty_and_is_true(ledger, company_id: UUID) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    _, ctx = _ctx(ledger, company_id, state)
    assert await And().allows(_entry_with({}), ctx) is True


async def test_empty_or_is_false(ledger, company_id: UUID) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    _, ctx = _ctx(ledger, company_id, state)
    assert await Or().allows(_entry_with({}), ctx) is False
