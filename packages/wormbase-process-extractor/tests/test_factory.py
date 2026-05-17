"""G.1 — make_process_reactivities + wire_process_for_install.

The factory returns the four process-worm Reactivity instances in a
deterministic order; the lifecycle hook registers them with W5a's
``ReactivityRegistry``. Mirrors lake-maintainer's
``make_maintenance_reactivities`` / ``wire_maintenance_for_source``
shapes (see ``packages/lake-maintainer/src/wormbase_lake_maintainer/
factory.py:23-35`` and ``registry.py:54-79``) — the difference is
scope: lake-maintainer wires once per Source, process-worm wires once
per process boot (state is per-tenant inside each Reactivity, not at
the class level).
"""
from __future__ import annotations

from uuid import uuid4

from wormbase_process_extractor import (
    DecisionRecordReactivity,
    RecurringQuestionReactivity,
    SystemMapNodeReactivity,
    TopicSynthesisReactivity,
    make_process_reactivities,
    wire_process_for_install,
)


# Pulled from wormbase_reactivities.process_mapper to assert the
# RecurringQuestionReactivity preserves the P10 id slot.
from wormbase_reactivities.process_mapper import (
    _REACTIVITY_ID as _RECURRING_QUESTION_ID,
)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_returns_four_reactivities() -> None:
    rs = make_process_reactivities()
    assert len(rs) == 4


def test_factory_order_is_deterministic() -> None:
    """Order: TopicSynthesis, RecurringQuestion, DecisionRecord, SystemMapNode.

    The order is part of the contract — wire_process_for_install relies
    on it for stable registration ordering, and downstream telemetry
    reads it as positional metadata.
    """
    rs = make_process_reactivities()
    assert isinstance(rs[0], TopicSynthesisReactivity)
    assert isinstance(rs[1], RecurringQuestionReactivity)
    assert isinstance(rs[2], DecisionRecordReactivity)
    assert isinstance(rs[3], SystemMapNodeReactivity)


def test_factory_topic_synthesis_id() -> None:
    rs = make_process_reactivities()
    assert rs[0].id == "topic_synthesis"


def test_factory_recurring_question_id_aliases_p10() -> None:
    """RecurringQuestionReactivity is the P10 alias; same id slot."""
    rs = make_process_reactivities()
    assert rs[1].id == _RECURRING_QUESTION_ID


def test_factory_decision_record_id() -> None:
    rs = make_process_reactivities()
    assert rs[2].id == "decision_record"


def test_factory_system_map_node_id() -> None:
    rs = make_process_reactivities()
    assert rs[3].id == "system_map_node"


def test_factory_passes_through_decision_budget() -> None:
    rs = make_process_reactivities(decision_per_tenant_budget=99)
    assert rs[2].per_tenant_budget == 99


def test_factory_passes_through_decision_novelty_hours() -> None:
    rs = make_process_reactivities(decision_novelty_hours=5.5)
    assert rs[2].novelty_hours == 5.5


def test_factory_passes_through_system_map_budget() -> None:
    rs = make_process_reactivities(system_map_per_tenant_budget=7)
    assert rs[3].per_tenant_budget == 7


def test_factory_passes_through_recurring_threshold() -> None:
    rs = make_process_reactivities(recurring_threshold=11)
    # Inspect the RecurringQuestionProcessMapperReactivity's threshold
    # field (the dataclass exposes the constructor arg directly).
    assert getattr(rs[1], "threshold", None) == 11


def test_factory_passes_through_recurring_window_days() -> None:
    rs = make_process_reactivities(recurring_window_days=30)
    assert getattr(rs[1], "window_days", None) == 30


def test_factory_passes_through_recurring_per_tenant_budget() -> None:
    rs = make_process_reactivities(recurring_per_tenant_budget=2)
    assert getattr(rs[1], "per_tenant_budget", None) == 2


def test_factory_default_values_match_spec() -> None:
    """Defaults documented in the plan G.1 spec."""
    rs = make_process_reactivities()
    assert rs[2].per_tenant_budget == 20
    assert rs[2].novelty_hours == 1.0
    assert rs[3].per_tenant_budget == 50


def test_factory_imports_are_cheap() -> None:
    """Module import must not pull in wormbase-llm (heavy dep).

    Mirrors the import-discipline check from
    ``packages/wormbase-process-extractor/src/.../reactivities.py``
    (lazy LLM resolution) — the factory is a static-import surface,
    so it must not transitively load llm clients at import time.
    """
    import sys

    # Re-import freshly to check the static surface stayed clean. We
    # don't pop the module because pytest's collection already loaded
    # it; instead we assert wormbase_llm is not pulled by simply
    # importing the factory module (which has run already).
    import wormbase_process_extractor.factory  # noqa: F401

    assert "wormbase_llm" not in sys.modules


# ---------------------------------------------------------------------------
# Lifecycle (wire_process_for_install)
# ---------------------------------------------------------------------------


class _StubReactivityRegistry:
    """Minimal stand-in for W5a's ReactivityRegistry.register contract.

    Mirrors the real registry's duplicate-detection behavior (raises
    ValueError on a re-register) so the lifecycle's idempotency
    guard is exercised under the same shape as production.
    """

    def __init__(self) -> None:
        self.registered: list[str] = []

    def register(self, reactivity, **_kwargs) -> None:  # noqa: ANN001
        if reactivity.id in self.registered:
            raise ValueError(
                f"reactivity {reactivity.id!r} is already registered",
            )
        self.registered.append(reactivity.id)


def test_wire_registers_all_four_reactivities() -> None:
    reg = _StubReactivityRegistry()
    ids = wire_process_for_install(registry=reg)
    assert len(ids) == 4
    assert reg.registered == ids


def test_wire_returns_ids_in_factory_order() -> None:
    reg = _StubReactivityRegistry()
    ids = wire_process_for_install(registry=reg)
    assert ids[0] == "topic_synthesis"
    assert ids[1] == _RECURRING_QUESTION_ID
    assert ids[2] == "decision_record"
    assert ids[3] == "system_map_node"


def test_wire_is_idempotent_on_second_call() -> None:
    """W5a's ``register`` raises on duplicate; the lifecycle must skip
    duplicates explicitly so that calling ``wire_process_for_install``
    twice on the same registry is a no-op rather than a crash.
    """
    reg = _StubReactivityRegistry()
    first = wire_process_for_install(registry=reg)
    second = wire_process_for_install(registry=reg)
    assert first == second
    assert reg.registered == first  # still only 4 registered ids


def test_wire_against_real_registry() -> None:
    """End-to-end smoke: wire against a real W5a ``ReactivityRegistry``.

    This guards against drift between the stub above and the real
    registry contract — if the real ``register`` ever stops raising
    ValueError on duplicates, the idempotency guard still holds.
    """
    from wormbase_reactivities.registry import ReactivityRegistry

    class _NullLedger:
        engine = None

    reg = ReactivityRegistry(ledger=_NullLedger(), company_id=uuid4())
    ids = wire_process_for_install(registry=reg)
    assert {b.id for b in reg.list()} == set(ids)

    # Second call is a no-op (same ids returned, no exception).
    ids_again = wire_process_for_install(registry=reg)
    assert ids_again == ids
    assert {b.id for b in reg.list()} == set(ids)


def test_wire_with_llm_client_threads_through() -> None:
    """The lifecycle accepts an optional llm_client kw and constructs
    Reactivities with it via the factory. The current factory does not
    mutate Reactivity instances based on llm_client (LLM resolution is
    lazy, via context.extras); this test asserts the kw is accepted
    and registration still succeeds.
    """
    reg = _StubReactivityRegistry()
    sentinel_client = object()
    ids = wire_process_for_install(registry=reg, llm_client=sentinel_client)
    assert len(ids) == 4
