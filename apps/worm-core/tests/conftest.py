"""Shared pytest fixtures for worm-core tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_ontology_seed import Loader

# Stable UUID for tests so payload UUIDs don't change across runs.
TEST_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000001")


class FrozenClock:
    """Tiny clock fixture: tick / advance / now."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def tick(self, *, seconds: float = 0, minutes: float = 0, hours: float = 0,
             days: float = 0) -> datetime:
        self._now += timedelta(seconds=seconds, minutes=minutes,
                               hours=hours, days=days)
        return self._now

    def advance_to(self, dt: datetime) -> datetime:
        if dt < self._now:
            raise ValueError("clocks only run forward")
        self._now = dt
        return self._now


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC))


@pytest.fixture
def company_id() -> UUID:
    return TEST_COMPANY_ID


@pytest.fixture
def ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest.fixture
def seed_loader() -> Loader:
    return Loader()
