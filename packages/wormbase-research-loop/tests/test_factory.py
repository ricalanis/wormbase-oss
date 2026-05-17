"""make_research_reactivities + wire_research_for_install — Block G.1.

Mirrors chat-presence's ``test_factory.py`` / identity-tracker's
``test_lifecycle.py`` shape: assert that the factory returns the four
research-loop Reactivities with the expected ids, and that the wire
helper registers all four with a W5a ``ReactivityRegistry``.

Per the G.1 spec (see ``docs/superpowers/plans/2026-05-03-research-worm-extraction.md``
lines 844-933), the factory is the **single point of construction** so
the four-instance cardinality is enforced structurally — no caller can
register, say, just ExperimentTriggerReactivity and forget the others.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from wormbase_chat_presence import Install
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.protocol import Reactivity
from wormbase_reactivities.registry import ReactivityRegistry

from wormbase_research_loop import (
    make_research_reactivities,
    wire_research_for_install,
)
from wormbase_research_loop.keep_rate import KeepRatePublisher


_EXPECTED_IDS = {
    "experiment_trigger",
    "experiment_resolve",
    "lesson_extraction",
    "keep_rate_publish",
}


def test_make_research_reactivities_returns_four() -> None:
    """Factory returns exactly four Reactivities with the expected ids."""
    reactivities = make_research_reactivities()

    assert len(reactivities) == 4
    ids = {r.id for r in reactivities}
    assert ids == _EXPECTED_IDS
    for r in reactivities:
        assert isinstance(r, Reactivity)


def test_make_research_reactivities_unique_names() -> None:
    """Each Reactivity has a unique human-readable name (per G.1 spec)."""
    reactivities = make_research_reactivities()
    names = [r.name for r in reactivities]
    assert len(set(names)) == len(names), (
        f"non-unique names: {names}"
    )


def test_make_research_reactivities_accepts_publisher_override() -> None:
    """Caller may inject a pre-built KeepRatePublisher (DI hook)."""
    ledger = InMemoryLedger()
    company = uuid4()
    publisher = KeepRatePublisher(ledger, company)
    reactivities = make_research_reactivities(publisher=publisher)

    keep_rate_rxs = [r for r in reactivities if r.id == "keep_rate_publish"]
    assert len(keep_rate_rxs) == 1
    # The injected publisher is the one threaded into KeepRatePublishReactivity.
    assert keep_rate_rxs[0].publisher is publisher


def test_make_research_reactivities_per_scope_daily_budget_threaded() -> None:
    """The per_scope_daily_budget kwarg reaches ExperimentTriggerReactivity."""
    reactivities = make_research_reactivities(per_scope_daily_budget=7)
    trigger = next(r for r in reactivities if r.id == "experiment_trigger")
    assert trigger.per_scope_daily_budget == 7


@pytest.mark.asyncio
async def test_wire_research_for_install_registers_four() -> None:
    """wire_research_for_install registers all four Reactivities."""
    company = uuid4()
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=company)
    install = Install(id=company, platform="slack")

    await wire_research_for_install(
        install=install,
        ledger=ledger,
        reactivity_registry=registry,
    )

    ids = {r.id for r in registry.list()}
    assert _EXPECTED_IDS.issubset(ids)


@pytest.mark.asyncio
async def test_wire_research_for_install_enumeration_matches_factory() -> None:
    """Registry list() enumerates the four expected names from the factory."""
    company = uuid4()
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=company)
    install = Install(id=company, platform="slack")

    await wire_research_for_install(
        install=install,
        ledger=ledger,
        reactivity_registry=registry,
    )

    factory_ids = {r.id for r in make_research_reactivities()}
    registry_ids = {r.id for r in registry.list()}
    assert factory_ids == registry_ids == _EXPECTED_IDS


@pytest.mark.asyncio
async def test_wire_research_for_install_threads_publisher() -> None:
    """Caller-supplied publisher reaches the registered KeepRatePublishReactivity."""
    company = uuid4()
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=company)
    install = Install(id=company, platform="slack")
    publisher = KeepRatePublisher(ledger, company)

    await wire_research_for_install(
        install=install,
        ledger=ledger,
        reactivity_registry=registry,
        publisher=publisher,
    )

    # Find the KeepRatePublishReactivity binding by walking registry internals
    # via the public ``list()``-by-id index.
    registered = {r.id: r for r in registry.list()}
    assert "keep_rate_publish" in registered
    # Reach the underlying Reactivity through the registry's binding map; the
    # public surface is intentionally narrow, so we use the documented test
    # accessor ``_bindings`` (see registry.py).
    binding = registry._bindings["keep_rate_publish"]
    assert binding.reactivity.publisher is publisher


def test_make_research_reactivities_publisher_default_is_none_at_construction() -> None:
    """Factory does not eagerly construct a publisher when none supplied.

    The KeepRatePublisher requires a ledger + company_id at construction;
    the factory shouldn't fabricate dummy values when caller didn't supply
    one. The KeepRatePublishReactivity lazily builds a publisher inside
    ``fire`` from ``context.ledger`` / ``context.company_id`` instead.
    """
    reactivities = make_research_reactivities()
    keep_rate = next(r for r in reactivities if r.id == "keep_rate_publish")
    assert keep_rate.publisher is None
