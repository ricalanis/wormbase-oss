"""Shared fixtures for governance tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_ontology_seed import Loader


TEST_COMPANY_ID = UUID("00000000-0000-0000-0000-00000000aaaa")


class FrozenClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def tick(self, **kw):
        self._now += timedelta(**kw)
        return self._now


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 4, 22, 12, tzinfo=UTC))


@pytest.fixture
def ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest.fixture
def company_id() -> UUID:
    return TEST_COMPANY_ID


@pytest.fixture
def seed_loader() -> Loader:
    return Loader()
