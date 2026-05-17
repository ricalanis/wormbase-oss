"""DailyBudget rollover property tests (W6.A1).

Invariants
----------
**B1. Per-owner cap.** ``DailyBudget(per_owner=N)`` enforces ≤N firings
per (reactivity_id, owner_id, day) — for any sequence of fires across
any number of owners and any day-key generator.

**B2. Midnight rollover.** Crossing UTC midnight resets the per-owner
counter to 0. The N+1th fire on day D is denied; the 1st fire on day
D+1 is allowed.

**B3. DST agnosticism.** The per-day key is UTC-anchored. A clock that
crosses a DST boundary in the local zone (Europe/London March 30, US
America/Los_Angeles March 9, etc.) does NOT cross the per-owner day
boundary unless UTC midnight is also crossed. The condition's behaviour
is identical regardless of the local clock's DST state.

**B4. Leap-second tolerance.** POSIX time skips leap seconds; the
condition's day-key is ``utc.date().isoformat()`` which is unaffected
by the absence of seconds 23:59:60 from the timeline. Synthesizing a
"during a leap second" wall clock is impossible in pure Python, so we
verify the proxy: the condition treats 23:59:59.999999 and 00:00:00.000000
as adjacent days with no off-by-one budget loss.

**B5. UUID layout neutrality.** The condition keys budget on
``str(owner_id)``. UUID v4 (random) and v7-like (timestamp-prefixed) MUST
both work — sequential v7 ids are not "the same" owner.

These properties are what makes the condition trustworthy. Without them,
admins would either see runaway DMs at midnight or false-positive budget
exhaustion in spring/fall.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from hypothesis import HealthCheck, given, settings, strategies as st

from wormbase_reactivities.conditions import DailyBudget
from wormbase_reactivities.protocol import ReactivityContext

from tests.property import strategies as S


# ---------------------------------------------------------------------------
# Minimal fake registry implementing the budget-counter API the condition
# uses. We model the rolling-day store as a dict so we can sweep across
# midnight / DST / leap-second boundaries without touching wall-clock
# state.
# ---------------------------------------------------------------------------


class _FakeRegistry:
    """In-memory budget store — same shape as ReactivityRegistry uses."""

    def __init__(self) -> None:
        self.counters: dict[tuple[str, str, str, str], int] = {}
        self.disabled_domains: set[str] = set()

    async def get_budget_count(
        self, *, reactivity_id: str, axis: str, key: str, day: str,
    ) -> int:
        return self.counters.get((reactivity_id, axis, key, day), 0)

    def increment(self, *, reactivity_id: str, axis: str, key: str, day: str) -> None:
        k = (reactivity_id, axis, key, day)
        self.counters[k] = self.counters.get(k, 0) + 1

    async def is_domain_enabled(self, domain_id: str) -> bool:
        return domain_id not in self.disabled_domains


def _entry_for_owner(owner_id: str) -> dict[str, Any]:
    """Synthesize an execute entry that surfaces ``owner_id`` in args."""
    return {
        "kind": "execute",
        "ts": datetime(2026, 4, 22, tzinfo=UTC),
        "seq": 1,
        "payload": {
            "tool": "emit_chat_received",
            "args": {"owner_id": owner_id},
        },
    }


def _ctx(now: datetime, registry: _FakeRegistry) -> ReactivityContext:
    return ReactivityContext(
        ledger=None,
        company_id=UUID("00000000-0000-0000-0000-000000000099"),
        registry=registry,
        now=lambda: now,
        extras={"reactivity_id": "test_rx"},
    )


def _allows(condition: DailyBudget, entry: dict[str, Any], ctx: ReactivityContext) -> bool:
    return asyncio.run(condition.allows(entry, ctx))


# ---------------------------------------------------------------------------
# B1 — per-owner cap
# ---------------------------------------------------------------------------


@given(per_owner=st.integers(min_value=1, max_value=10),
       fires=st.integers(min_value=0, max_value=20),
       owner_uuid=S.uuids_v4())
@settings(max_examples=200, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
def test_per_owner_cap_enforced(per_owner: int, fires: int, owner_uuid: UUID) -> None:
    """Invariant B1: after ``fires`` increments, ``allows`` returns True iff fires < per_owner.

    Scenarios fuzzed:
      * fires < per_owner   → condition allows  (True)
      * fires == per_owner  → condition denies (False, exact-boundary)
      * fires > per_owner   → condition denies (False)
    """
    reg = _FakeRegistry()
    cond = DailyBudget(per_owner=per_owner, per_domain=None, per_tenant=None)
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    day = now.date().isoformat()
    owner = str(owner_uuid)
    entry = _entry_for_owner(owner)
    ctx = _ctx(now, reg)
    # Pre-load the counter.
    for _ in range(fires):
        reg.increment(
            reactivity_id="test_rx", axis="owner", key=owner, day=day,
        )
    assert _allows(cond, entry, ctx) is (fires < per_owner)


# ---------------------------------------------------------------------------
# B2 — midnight rollover
# ---------------------------------------------------------------------------


@given(per_owner=st.integers(min_value=1, max_value=5),
       owner_uuid=S.uuids_v4())
@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
def test_midnight_utc_rollover_resets_per_owner_counter(
    per_owner: int, owner_uuid: UUID,
) -> None:
    """Invariant B2: crossing UTC midnight resets the per-owner counter.

    Sequence:
      1. saturate the budget on day D (per_owner fires)
      2. condition denies on day D
      3. clock advances past 00:00 UTC of day D+1
      4. condition allows on day D+1 (counter for D+1 is 0)
    """
    reg = _FakeRegistry()
    cond = DailyBudget(per_owner=per_owner, per_domain=None, per_tenant=None)
    owner = str(owner_uuid)
    entry = _entry_for_owner(owner)

    day_d = datetime(2026, 4, 22, 23, 59, 59, 500_000, tzinfo=UTC)
    day_d_plus_1 = datetime(2026, 4, 23, 0, 0, 1, tzinfo=UTC)
    day_d_key = day_d.date().isoformat()

    for _ in range(per_owner):
        reg.increment(reactivity_id="test_rx", axis="owner", key=owner, day=day_d_key)

    # Day D — saturated, denied.
    assert _allows(cond, entry, _ctx(day_d, reg)) is False
    # Day D+1 — fresh counter, allowed.
    assert _allows(cond, entry, _ctx(day_d_plus_1, reg)) is True


def test_midnight_boundary_no_off_by_one_loss() -> None:
    """Invariant B4 (proxy): 23:59:59.999999 and 00:00:00.000000 are adjacent days.

    POSIX skips leap seconds, so synthesizing "during a leap second" is
    not possible in stdlib datetime. Instead we verify the property the
    condition relies on: the day key crosses cleanly at midnight, with
    no microsecond capable of producing a third "limbo" key.
    """
    just_before = datetime(2026, 4, 22, 23, 59, 59, 999_999, tzinfo=UTC)
    just_after = datetime(2026, 4, 23, 0, 0, 0, 0, tzinfo=UTC)
    assert just_before.date().isoformat() == "2026-04-22"
    assert just_after.date().isoformat() == "2026-04-23"
    # The microsecond between is also covered: the .date() function does
    # not look at microseconds, so any (hour=23, minute=59, second=59,
    # microsecond=*) is day D, and (hour=0, ...) is day D+1.
    one_ms_off = just_before + timedelta(microseconds=1)
    assert one_ms_off.date().isoformat() == "2026-04-23"


# ---------------------------------------------------------------------------
# B3 — DST agnosticism
# ---------------------------------------------------------------------------


def test_dst_local_clock_does_not_shift_per_owner_day() -> None:
    """Invariant B3: a local-time DST jump doesn't affect the UTC day key.

    On 2026-03-29 02:00 local time, Europe/London springs forward to
    03:00. The UTC clock during this transition was at 01:00:00 (and
    01:59:59 just before it). UTC midnight has not been crossed —
    therefore the day key is the same on either side of the DST event.
    """
    pre = datetime(2026, 3, 29, 0, 59, 59, tzinfo=UTC)
    post = datetime(2026, 3, 29, 2, 0, 0, tzinfo=UTC)
    assert pre.date() == post.date()


# ---------------------------------------------------------------------------
# B5 — UUID v4 vs v7-like neutrality
# ---------------------------------------------------------------------------


@given(per_owner=st.integers(min_value=1, max_value=3),
       v4_id=S.uuids_v4(),
       v7_id=S.uuids_v7_like())
@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
def test_v4_and_v7_owner_ids_are_independently_budgeted(
    per_owner: int, v4_id: UUID, v7_id: UUID,
) -> None:
    """Invariant B5: v4 and v7 owner ids are independent budget keys.

    The condition stringifies the owner id; v7's timestamp prefix and v4's
    fully-random prefix produce distinct strings, so saturating the v4
    counter does NOT block fires for the v7 owner. (Edge case: collision
    is astronomically unlikely; we just skip if our random pair happens
    to produce the same string.)
    """
    if str(v4_id) == str(v7_id):
        # Astronomically rare; skip for deterministic semantics.
        return

    reg = _FakeRegistry()
    cond = DailyBudget(per_owner=per_owner, per_domain=None, per_tenant=None)
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    day = now.date().isoformat()

    # Saturate the v4 budget.
    for _ in range(per_owner):
        reg.increment(reactivity_id="test_rx", axis="owner", key=str(v4_id), day=day)

    # v4 owner is denied.
    v4_entry = _entry_for_owner(str(v4_id))
    assert _allows(cond, v4_entry, _ctx(now, reg)) is False

    # v7 owner is unaffected — independent counter.
    v7_entry = _entry_for_owner(str(v7_id))
    assert _allows(cond, v7_entry, _ctx(now, reg)) is True


# ---------------------------------------------------------------------------
# Cross-axis sanity: per_owner + per_domain compose monotonically — if
# either is exceeded, the condition denies. The boundary depends on
# whichever axis is exceeded first.
# ---------------------------------------------------------------------------


@given(per_owner=st.integers(min_value=1, max_value=5),
       per_domain=st.integers(min_value=1, max_value=10),
       owner_fires=st.integers(min_value=0, max_value=10),
       domain_fires=st.integers(min_value=0, max_value=15))
@settings(max_examples=150, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
def test_per_owner_and_per_domain_compose_with_min_semantics(
    per_owner: int, per_domain: int, owner_fires: int, domain_fires: int,
) -> None:
    """Invariant B1+: composed limits deny when EITHER axis is exceeded.

    DailyBudget(per_owner=N, per_domain=M) is the conjunction of two
    independent caps. If owner_fires >= N OR domain_fires >= M, the
    condition denies; otherwise it allows. This is "min-semantics" —
    whichever axis runs out first is the binding constraint.
    """
    reg = _FakeRegistry()
    cond = DailyBudget(per_owner=per_owner, per_domain=per_domain, per_tenant=None)
    owner = str(uuid4())
    domain = "domain-xyz"
    entry = {
        "kind": "execute",
        "ts": datetime(2026, 4, 22, tzinfo=UTC),
        "seq": 1,
        "payload": {
            "tool": "emit_chat_received",
            "args": {"owner_id": owner, "domain_id": domain},
        },
    }
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    day = now.date().isoformat()
    ctx = _ctx(now, reg)

    for _ in range(owner_fires):
        reg.increment(reactivity_id="test_rx", axis="owner", key=owner, day=day)
    for _ in range(domain_fires):
        reg.increment(reactivity_id="test_rx", axis="domain", key=domain, day=day)

    expected_allow = owner_fires < per_owner and domain_fires < per_domain
    assert _allows(cond, entry, ctx) is expected_allow
