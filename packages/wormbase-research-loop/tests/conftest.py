"""Shared pytest fixtures for wormbase-research-loop tests.

Provides ``ledger`` and ``company_id`` fixtures matching the worm-core
test conftest so lifted tests run unchanged.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger

# Stable UUID for tests so payload UUIDs don't change across runs.
TEST_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def company_id() -> UUID:
    return TEST_COMPANY_ID


@pytest.fixture
def ledger() -> InMemoryLedger:
    return InMemoryLedger()
