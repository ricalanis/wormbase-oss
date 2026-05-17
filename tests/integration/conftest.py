"""L5 integration-test conftest.

Auto-tags every test in `tests/integration/` with the `integration`
marker so `pytest -m integration` and `make integration` select them.

Provides one extra fixture beyond the root conftest: `worm_core_integration`,
which gives each integration test a fully-wired ``WormCore`` instance
backed by either:

- the real `test_ledger` (testcontainers Postgres) — when WORMBASE_INTEGRATION_REAL_DB=1
- an `InMemoryLedger` otherwise (still exercises the full reactivity
  triad / source flows / governance / ramp wiring; just stores entries
  in memory rather than via SQLAlchemy)

Both modes count as L5 because they boot the full multi-service Python
graph; the docker-compose path tests transport-layer concerns
(networking, healthchecks, restart) which are largely out of scope for
a demo-Thursday gate.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger, Ledger


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    integration_marker = pytest.mark.integration
    for item in items:
        if "tests/integration/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(integration_marker)


TEST_COMPANY_ID = UUID("00000000-0000-0000-0000-000000005555")


@pytest.fixture
def integration_company_id() -> UUID:
    return TEST_COMPANY_ID


@pytest.fixture
async def integration_ledger(request) -> AsyncIterator[Ledger | InMemoryLedger]:  # type: ignore[no-untyped-def]
    """Real Ledger (testcontainers Postgres) when env flag set, else InMemoryLedger.

    We default to InMemoryLedger because OrbStack/Docker may be missing
    on a dev machine and the L5 tests still want to run there. CI sets
    WORMBASE_INTEGRATION_REAL_DB=1 to force the real path.
    """
    if os.environ.get("WORMBASE_INTEGRATION_REAL_DB") == "1":
        # Pull the real Ledger via the root `test_ledger` fixture.
        ledger = request.getfixturevalue("test_ledger")
        yield ledger
    else:
        yield InMemoryLedger()


@pytest.fixture
async def worm_core_integration(integration_ledger, integration_company_id):  # type: ignore[no-untyped-def]
    """Fully-wired WormCore for integration tests."""
    from wormbase_core.service import build_worm_core

    return await build_worm_core(
        integration_ledger,
        integration_company_id,
        domain_pack="saas",
        enable_lurker=False,  # tests inject events synthetically
        enable_cloud_classifier=False,  # no network in tests
    )
