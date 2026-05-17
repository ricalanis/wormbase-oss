"""Shared fixtures for reactivities tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger

TEST_COMPANY_ID = UUID("00000000-0000-0000-0000-00000000a001")


@pytest.fixture
def company_id() -> UUID:
    return TEST_COMPANY_ID


@pytest.fixture
def ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest.fixture
def frozen_now():
    """A monotonically-controllable now() for budget rollover tests."""
    state = {"now": datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)}

    def get() -> datetime:
        return state["now"]

    def set_(dt: datetime) -> None:
        state["now"] = dt

    get.set = set_  # type: ignore[attr-defined]
    return get
