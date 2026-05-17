"""Smoke test: every conftest fixture loads."""

from __future__ import annotations

from uuid import UUID

from wormbase_ledger import InMemoryLedger
from wormbase_ontology_seed import Loader


def test_clock_starts_at_known_iso(clock) -> None:
    assert clock.now().isoformat() == "2026-04-22T12:00:00+00:00"


def test_company_id_is_stable(company_id: UUID) -> None:
    assert str(company_id) == "00000000-0000-0000-0000-000000000001"


def test_ledger_initializes(ledger: InMemoryLedger) -> None:
    assert isinstance(ledger, InMemoryLedger)


def test_seed_loader_returns_at_least_50_saas_concepts(seed_loader: Loader) -> None:
    assert len(seed_loader.load_ontology("saas")) >= 50


def test_clock_tick_advances(clock) -> None:
    before = clock.now()
    clock.tick(seconds=30)
    assert (clock.now() - before).total_seconds() == 30
