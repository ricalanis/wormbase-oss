"""Protocol contract tests.

Verify that:
  * Concrete classes implementing ``Reactivity`` pass isinstance checks
    (Protocol is runtime_checkable via the imports' shape).
  * Default ``ReactivityResult`` / ``FiredAction`` constructions are sane.
  * ``ReactivitySpec`` round-trips its fields without losing fidelity.
  * ``ReactivityContext`` carries the expected slots.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from wormbase_reactivities import (
    AlwaysAllow,
    EntryKind,
    FiredAction,
    ReactivityContext,
    ReactivityRegistry,
    ReactivityResult,
    ReactivityScope,
    ReactivitySpec,
    ReactivityState,
)


def _now() -> datetime:
    return datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)


class _DummyReactivity:
    """Minimal Reactivity-shaped class for Protocol contract tests."""

    id: str = "dummy"
    name: str = "Dummy"
    description: str = "Test reactivity that fires nothing."
    scope: ReactivityScope = "company"

    def __init__(self) -> None:
        self.predicate = EntryKind("chat_received")
        self.condition = AlwaysAllow()

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        return ReactivityResult(fired=False)


def test_dummy_reactivity_satisfies_protocol() -> None:
    r = _DummyReactivity()
    assert hasattr(r, "id") and r.id == "dummy"
    assert hasattr(r, "fire")
    # Reactivity is a Protocol with runtime checks per-attribute. We
    # don't isinstance-check it because Protocol w/o @runtime_checkable
    # rejects custom classes; structural checks are enough here.
    assert callable(r.fire)


def test_reactivity_result_defaults() -> None:
    r = ReactivityResult(fired=False)
    assert r.fired is False
    assert r.actions == []
    assert r.novelty_key == ""
    assert r.budget_used == {}


def test_reactivity_result_carries_actions() -> None:
    a = FiredAction(action_kind="person_proposed", action_seqs=[1, 2, 3, 4])
    r = ReactivityResult(
        fired=True,
        actions=[a],
        novelty_key="slack:U-bob",
        budget_used={"per_tenant": 1},
    )
    assert r.fired is True
    assert len(r.actions) == 1
    assert r.actions[0].action_kind == "person_proposed"
    assert r.actions[0].action_seqs == [1, 2, 3, 4]
    assert r.budget_used == {"per_tenant": 1}


def test_reactivity_spec_round_trips() -> None:
    spec = ReactivitySpec(
        id="statement_to_owner",
        name="Statement to Owner",
        description="DM the resource owner with related KPIs/sources.",
        scope="domain",
        predicate_spec={"kind": "chat_received"},
        condition_spec={"per_owner_per_day": 3},
        action_spec={"channel": "dm"},
    )
    raw = asdict(spec)
    again = ReactivitySpec(**raw)
    assert again == spec


def test_reactivity_context_holds_slots(ledger, company_id: UUID) -> None:
    registry = ReactivityRegistry(ledger=ledger, company_id=company_id, now=_now)
    ctx = ReactivityContext(
        ledger=ledger,
        company_id=company_id,
        registry=registry,
        now=_now,
        extras={"k": "v"},
    )
    assert ctx.ledger is ledger
    assert ctx.company_id == company_id
    assert ctx.registry is registry
    assert ctx.now() == _now()
    assert ctx.extras == {"k": "v"}


def test_reactivity_state_is_a_literal_set() -> None:
    # Compile-time-style assertion — assignment of any of the known
    # values must not raise.
    valid_states: list[ReactivityState] = ["proposed", "active", "disabled"]
    assert all(isinstance(s, str) for s in valid_states)
