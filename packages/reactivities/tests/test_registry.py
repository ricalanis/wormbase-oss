"""Registry: register / propose / confirm / disable / dispatch + budget enforcement."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_reactivities import (
    AlwaysAllow,
    DailyBudget,
    EntryKind,
    FiredAction,
    ReactivityContext,
    ReactivityRegistry,
    ReactivityResult,
    ReactivityScope,
    ReactivitySpec,
)


def _now_factory(state: dict):
    def _now() -> datetime:
        return state["now"]

    return _now


# ---------------------------------------------------------------------------
# Test reactivities
# ---------------------------------------------------------------------------


class _RecordingReactivity:
    """Records every (entry, context) it fires against. AlwaysAllow."""

    id = "recorder"
    name = "Recorder"
    description = "Records every dispatch for assertion."
    scope: ReactivityScope = "company"

    def __init__(self) -> None:
        self.predicate = EntryKind("chat_received")
        self.condition = AlwaysAllow()
        self.fired_with: list[dict[str, Any]] = []

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        self.fired_with.append(entry)
        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="recorded")],
            novelty_key=f"seq-{entry.get('seq')}",
            budget_used={"per_tenant": 1},
        )


class _NoFireReactivity:
    """Predicate matches but Reactivity returns fired=False."""

    id = "skipper"
    name = "Skipper"
    description = "Always returns fired=False."
    scope: ReactivityScope = "company"

    def __init__(self) -> None:
        self.predicate = EntryKind("chat_received")
        self.condition = AlwaysAllow()

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        return ReactivityResult(fired=False)


class _BudgetedReactivity:
    """Owner-budgeted Reactivity for the budget-enforcement tests."""

    id = "budgeted"
    name = "Budgeted"
    description = "DailyBudget(per_owner=2)."
    scope: ReactivityScope = "domain"

    def __init__(self) -> None:
        self.predicate = EntryKind("chat_received")
        self.condition = DailyBudget(
            per_owner=2, per_domain=10, per_tenant=10,
        )

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="dm_sent")],
            novelty_key="",
            budget_used={"per_owner": 1, "per_domain": 1, "per_tenant": 1},
        )


def _chat_entry(seq: int, owner: str | None = None, domain: str | None = None) -> dict[str, Any]:
    args: dict[str, Any] = {"text": "hi"}
    if owner is not None:
        args["owner_person_id"] = owner
    if domain is not None:
        args["domain_id"] = domain
    return {
        "kind": "execute",
        "seq": seq,
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": args,
        },
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def test_register_lists_reactivity(ledger, company_id: UUID) -> None:
    reg = ReactivityRegistry(ledger=ledger, company_id=company_id)
    reg.register(_RecordingReactivity())
    state = reg.list()
    assert len(state) == 1
    assert state[0].id == "recorder"
    assert state[0].state == "active"


async def test_register_default_state_is_active(
    ledger, company_id: UUID,
) -> None:
    reg = ReactivityRegistry(ledger=ledger, company_id=company_id)
    reg.register(_RecordingReactivity())
    assert reg.list()[0].state == "active"


async def test_register_proposed_state_skips_dispatch(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=_now_factory(state),
    )
    r = _RecordingReactivity()
    reg.register(r, initial_state="proposed")
    fired = await reg.dispatch(_chat_entry(seq=1))
    assert fired == []
    assert r.fired_with == []


async def test_register_duplicate_raises(ledger, company_id: UUID) -> None:
    reg = ReactivityRegistry(ledger=ledger, company_id=company_id)
    reg.register(_RecordingReactivity())
    with pytest.raises(ValueError):
        reg.register(_RecordingReactivity())


# ---------------------------------------------------------------------------
# propose / confirm / disable lifecycle
# ---------------------------------------------------------------------------


async def test_propose_writes_emit_reactivity_proposed(
    ledger, company_id: UUID,
) -> None:
    reg = ReactivityRegistry(ledger=ledger, company_id=company_id)
    spec = ReactivitySpec(
        id="dm_owner",
        name="DM Owner",
        description="Test propose",
        scope="company",
    )
    await reg.propose(spec, proposed_by="worm")
    rows = await ledger.fetch(company_id)
    proposes = [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_reactivity_proposed"
    ]
    assert len(proposes) == 1
    args = proposes[0]["payload"]["args"]
    assert args["reactivity_id"] == "dm_owner"
    assert args["proposed_by"] == "worm"


async def test_confirm_flips_state_to_active(ledger, company_id: UUID) -> None:
    reg = ReactivityRegistry(ledger=ledger, company_id=company_id)
    reg.register(_RecordingReactivity(), initial_state="proposed")
    confirmed_by = uuid4()
    await reg.confirm("recorder", confirmed_by=confirmed_by)
    state = reg.list()
    assert state[0].state == "active"
    rows = await ledger.fetch(company_id)
    confirms = [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_reactivity_confirmed"
    ]
    assert len(confirms) == 1
    assert confirms[0]["payload"]["args"]["reactivity_id"] == "recorder"


async def test_disable_flips_state_and_skips_dispatch(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=_now_factory(state),
    )
    r = _RecordingReactivity()
    reg.register(r)
    await reg.disable("recorder", disabled_by=uuid4(), reason="too noisy")
    assert reg.list()[0].state == "disabled"
    fired = await reg.dispatch(_chat_entry(seq=1))
    assert fired == []
    assert r.fired_with == []


async def test_confirm_unregistered_raises(ledger, company_id: UUID) -> None:
    reg = ReactivityRegistry(ledger=ledger, company_id=company_id)
    with pytest.raises(ValueError):
        await reg.confirm("nonexistent", confirmed_by=uuid4())


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


async def test_dispatch_fires_matching_reactivity(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=_now_factory(state),
    )
    r = _RecordingReactivity()
    reg.register(r)
    fired = await reg.dispatch(_chat_entry(seq=42))
    assert fired == ["recorder"]
    assert len(r.fired_with) == 1
    assert r.fired_with[0]["seq"] == 42


async def test_dispatch_writes_emit_reactivity_fired(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=_now_factory(state),
    )
    reg.register(_RecordingReactivity())
    await reg.dispatch(_chat_entry(seq=99))
    rows = await ledger.fetch(company_id)
    fires = [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_reactivity_fired"
    ]
    assert len(fires) == 1
    args = fires[0]["payload"]["args"]
    assert args["reactivity_id"] == "recorder"
    assert args["source_seq"] == 99
    assert args["novelty_key"] == "seq-99"


async def test_dispatch_no_fire_when_predicate_misses(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=_now_factory(state),
    )
    r = _RecordingReactivity()
    reg.register(r)
    not_chat = {
        "kind": "execute", "seq": 1,
        "payload": {"tool": "emit_person_proposed", "args": {}},
    }
    fired = await reg.dispatch(not_chat)
    assert fired == []


async def test_dispatch_no_emit_fired_when_result_fired_false(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=_now_factory(state),
    )
    reg.register(_NoFireReactivity())
    fired = await reg.dispatch(_chat_entry(seq=1))
    assert fired == []
    rows = await ledger.fetch(company_id)
    fires = [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_reactivity_fired"
    ]
    assert fires == []


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------


async def test_budget_enforces_per_owner_cap(ledger, company_id: UUID) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=_now_factory(state),
    )
    reg.register(_BudgetedReactivity())
    # Fire twice for owner=p-1 (cap=2 → both succeed).
    assert await reg.dispatch(_chat_entry(seq=1, owner="p-1")) == ["budgeted"]
    assert await reg.dispatch(_chat_entry(seq=2, owner="p-1")) == ["budgeted"]
    # Third call should be denied by the budget.
    assert await reg.dispatch(_chat_entry(seq=3, owner="p-1")) == []
    rows = await ledger.fetch(company_id)
    fires = [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_reactivity_fired"
    ]
    # Exactly two fires landed; the third was blocked.
    assert len(fires) == 2


async def test_budget_increments_after_successful_fire_only(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=_now_factory(state),
    )
    reg.register(_BudgetedReactivity())
    await reg.dispatch(_chat_entry(seq=1, owner="p-1", domain="d-1"))
    day = state["now"].date().isoformat()
    cnt_owner = await reg.get_budget_count(
        reactivity_id="budgeted", axis="owner", key="p-1", day=day,
    )
    cnt_domain = await reg.get_budget_count(
        reactivity_id="budgeted", axis="domain", key="d-1", day=day,
    )
    cnt_tenant = await reg.get_budget_count(
        reactivity_id="budgeted", axis="tenant", key=str(company_id), day=day,
    )
    assert cnt_owner == 1
    assert cnt_domain == 1
    assert cnt_tenant == 1


async def test_dispatch_continues_after_one_reactivity_fails(
    ledger, company_id: UUID,
) -> None:
    """A buggy Reactivity must not wedge dispatch for siblings."""

    class _Buggy:
        id = "buggy"
        name = "Buggy"
        description = ""
        scope: ReactivityScope = "company"

        def __init__(self) -> None:
            self.predicate = EntryKind("chat_received")
            self.condition = AlwaysAllow()

        async def fire(self, entry, context):
            raise RuntimeError("synthetic")

    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=_now_factory(state),
    )
    reg.register(_Buggy())
    reg.register(_RecordingReactivity())
    fired = await reg.dispatch(_chat_entry(seq=1))
    assert fired == ["recorder"]


async def test_get_last_fired_at_round_trip(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    reg = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=_now_factory(state),
    )
    reg.register(_RecordingReactivity())
    await reg.dispatch(_chat_entry(seq=1))
    last = await reg.get_last_fired_at(
        reactivity_id="recorder", novelty_key="seq-1",
    )
    assert last == state["now"]
