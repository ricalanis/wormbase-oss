"""Schema-migration tests.

Covers two separate migration mechanisms:

1. **Alembic** (legacy). Used by the ledger package's CI-time
   schema check. The ``test_alembic_upgrade_head_succeeds`` smoke
   test ensures ``alembic upgrade head`` still works against a
   fresh SQLite database.

2. **Boot-time migrate runner** (``wormbase_ledger.projections.migrate``).
   The new path that applies pending migrations on every worm-core
   boot, fixing the schema-drift gap that previously required a
   ``docker volume rm wormbase-postgres-data`` to recover.

The boot-time runner is the source of truth going forward. The
alembic smoke test stays green so the legacy CI hook keeps working
until it's retired in a follow-up.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import inspect, select
from wormbase_ledger.ledger_api import Ledger
from wormbase_ledger.projections.migrate import (
    current_version,
    migrate,
    schema_migrations,
)
from wormbase_ledger.projections.migrations import MIGRATIONS

# ---------------------------------------------------------------------------
# Alembic legacy smoke test (kept until alembic is retired)
# ---------------------------------------------------------------------------


def test_alembic_upgrade_head_succeeds() -> None:
    pkg_root = Path(__file__).resolve().parents[1]
    db_file = Path(tempfile.mkdtemp(prefix="wb-alembic-")) / "ledger.sqlite"
    url = f"sqlite:///{db_file}"

    env = {**os.environ, "WORMBASE_DB_URL": url}
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=pkg_root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"stdout: {r.stdout}\nstderr: {r.stderr}"
    assert db_file.exists()


# ---------------------------------------------------------------------------
# Boot-time migrate runner — fixtures
# ---------------------------------------------------------------------------
#
# We override the package's ``_reset_schema`` autouse fixture (from
# conftest.py) by making the ledger fixtures here use a *raw* engine
# that has no schema applied. The migration tests need to start from
# an empty database to exercise the runner end-to-end.
#
# The autouse fixture in conftest.py calls metadata.create_all, which
# would short-circuit our migration run. Instead we open a fresh URL
# per test that the autouse fixture has not touched.


@pytest_asyncio.fixture
async def fresh_ledger(tmp_path) -> Any:  # type: ignore[no-untyped-def]
    """A Ledger pointed at a brand-new (empty) sqlite file.

    The package-level autouse ``_reset_schema`` fixture creates the
    full schema on a *different* database URL (per-test from
    ``test_database_url``). We sidestep it by opening our own URL
    here so the migrate() runner sees an empty database.
    """
    db_file = tmp_path / "fresh.sqlite"
    url = f"sqlite+aiosqlite:///{db_file}"
    ledger = Ledger(url)
    yield ledger
    await ledger.dispose()


# ---------------------------------------------------------------------------
# Boot-time migrate runner — tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clean_boot_applies_all_migrations(fresh_ledger: Ledger) -> None:
    """A brand-new DB applies every migration in order."""
    expected_versions = [m.version for m in MIGRATIONS]

    applied = await migrate(fresh_ledger)

    assert applied == expected_versions
    assert await current_version(fresh_ledger) == max(expected_versions)


@pytest.mark.asyncio
async def test_clean_boot_creates_expected_columns(fresh_ledger: Ledger) -> None:
    """After migrate(), projection_installs has setup_mode + setup_completed_at."""
    await migrate(fresh_ledger)

    async with fresh_ledger.engine.connect() as conn:
        cols = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("projection_installs")}
        )

    assert "setup_mode" in cols, "v002 should have added setup_mode"
    assert "setup_completed_at" in cols, "v002 should have added setup_completed_at"


@pytest.mark.asyncio
async def test_already_current_is_noop(fresh_ledger: Ledger) -> None:
    """Re-running migrate() on a current schema is a no-op."""
    first = await migrate(fresh_ledger)
    assert first == [m.version for m in MIGRATIONS]

    second = await migrate(fresh_ledger)
    assert second == [], "second apply must report no work"

    third = await migrate(fresh_ledger)
    assert third == []


@pytest.mark.asyncio
async def test_partial_applied_resumes_from_cursor(fresh_ledger: Ledger) -> None:
    """If only v1 is applied, a re-run with both v1 and v2 applies only v2."""
    # Apply only v001 first.
    only_v001 = [MIGRATIONS[0]]
    applied_first = await migrate(fresh_ledger, migrations=only_v001)
    assert applied_first == [1]
    assert await current_version(fresh_ledger) == 1

    # Now run with the full canonical list — should pick up every version above v001.
    applied_second = await migrate(fresh_ledger)
    expected_tail = [m.version for m in MIGRATIONS if m.version > 1]
    assert applied_second == expected_tail, (
        f"expected {expected_tail} to apply when v001 is already at the cursor"
    )
    assert await current_version(fresh_ledger) == max(m.version for m in MIGRATIONS)


@pytest.mark.asyncio
async def test_runner_records_migrations_in_table(fresh_ledger: Ledger) -> None:
    """Applied migrations land in ``_schema_migrations`` with applied_at set."""
    await migrate(fresh_ledger)

    async with fresh_ledger.engine.connect() as conn:
        result = await conn.execute(
            select(schema_migrations.c.version, schema_migrations.c.applied_at)
            .order_by(schema_migrations.c.version)
        )
        rows = result.fetchall()

    assert [r.version for r in rows] == [m.version for m in MIGRATIONS]
    for r in rows:
        assert r.applied_at is not None, "applied_at must be stamped on insert"


@pytest.mark.asyncio
async def test_v002_idempotent_on_existing_columns(fresh_ledger: Ledger) -> None:
    """v002's ADD COLUMN check skips columns that already exist.

    Simulates a database where ``metadata.create_all`` has already
    created ``projection_installs`` with the v002 columns (this is
    the state of every existing demo DB before the migration system
    landed). v002 must be a no-op rather than crashing on duplicate
    column.
    """
    # Pre-populate using the LIVE schema (which already includes
    # setup_mode + setup_completed_at) — mirrors the pre-migrations
    # production state.
    from wormbase_ledger.schema import metadata as live_metadata

    async with fresh_ledger.engine.begin() as conn:
        await conn.run_sync(live_metadata.create_all)

    # v001 is no-op (CREATE TABLE IF NOT EXISTS); v002 must skip the
    # already-present columns.
    applied = await migrate(fresh_ledger)
    assert applied == [m.version for m in MIGRATIONS]

    # Schema is still valid: columns exist exactly once.
    async with fresh_ledger.engine.connect() as conn:
        cols = await conn.run_sync(
            lambda c: [col["name"] for col in inspect(c).get_columns("projection_installs")]
        )
    assert cols.count("setup_mode") == 1
    assert cols.count("setup_completed_at") == 1


@pytest.mark.asyncio
async def test_future_migration_applies_on_next_boot(fresh_ledger: Ledger) -> None:
    """A hypothetical future migration applies on the next migrate() call.

    Exercises the runner with a mock migration inserted after the canonical
    list to prove the cursor-based catch-up works for any future
    additive migration. Uses ``version=99`` to stay clear of any future
    canonical migrations added after this one.
    """
    # First boot: apply canonical list.
    await migrate(fresh_ledger)
    canonical_max = max(m.version for m in MIGRATIONS)
    assert await current_version(fresh_ledger) == canonical_max

    # Hypothetical future migration — adds an `audit_count` column to
    # projection_installs. Replicates the shape of v002.
    class _MockFutureMigration:
        version = 99
        description = "mock: add audit_count column"

        async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
            def _add(c) -> None:
                from sqlalchemy import inspect, text
                cols = {col["name"] for col in inspect(c).get_columns("projection_installs")}
                if "audit_count" in cols:
                    return
                c.execute(text("ALTER TABLE projection_installs ADD COLUMN audit_count INTEGER NULL"))

            await conn.run_sync(_add)

    extended = [*list(MIGRATIONS), _MockFutureMigration()]

    # Second boot with the extended list — the new migration catches up.
    applied = await migrate(fresh_ledger, migrations=extended)
    assert applied == [99]
    assert await current_version(fresh_ledger) == 99

    # Column landed.
    async with fresh_ledger.engine.connect() as conn:
        cols = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("projection_installs")}
        )
    assert "audit_count" in cols


@pytest.mark.asyncio
async def test_runner_rejects_unsorted_migrations(fresh_ledger: Ledger) -> None:
    """Out-of-order migration lists raise — no implicit sort."""

    class _M1:
        version = 1
        description = "m1"

        async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
            return

    class _M2:
        version = 2
        description = "m2"

        async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
            return

    with pytest.raises(RuntimeError, match="ordered by version"):
        await migrate(fresh_ledger, migrations=[_M2(), _M1()])


@pytest.mark.asyncio
async def test_runner_rejects_duplicate_versions(fresh_ledger: Ledger) -> None:
    """Duplicate versions raise — every version is unique."""

    class _M1:
        version = 1
        description = "m1"

        async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
            return

    class _M1Dup:
        version = 1
        description = "m1-dup"

        async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
            return

    with pytest.raises(RuntimeError, match="duplicate"):
        await migrate(fresh_ledger, migrations=[_M1(), _M1Dup()])


@pytest.mark.asyncio
async def test_failed_migration_does_not_advance_cursor(
    fresh_ledger: Ledger,
) -> None:
    """A migration that raises mid-up does not advance the cursor.

    Documents the "downgrade-not-supported" stance: forward-only
    migrations rely on the runner ROLLBACKing failed applies so the
    cursor never advances past a half-applied step. The operator
    fixes the bug, retries — no manual recovery.

    Note on backend portability: Postgres rolls back DDL + DML
    atomically, so a failed migration leaves the schema bit-identical
    to its pre-apply state. SQLite (used here) does not roll back
    DDL — but the bookkeeping ``INSERT INTO _schema_migrations``
    *is* DML and DOES roll back, so the cursor stays put on every
    backend. That property is what this test pins down: the
    invariant "failed migration → cursor unchanged" holds everywhere,
    so retry-after-fix always replays the failed step.
    """
    # First, apply the canonical list cleanly.
    await migrate(fresh_ledger)
    canonical_max = max(m.version for m in MIGRATIONS)
    assert await current_version(fresh_ledger) == canonical_max

    class _BrokenFutureMigration:
        version = 99
        description = "intentionally broken"

        async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
            from sqlalchemy import text
            # Valid DML, then a deliberate failure. We don't run DDL
            # here because SQLite's non-transactional DDL would leak
            # state in a way that doesn't reflect Postgres semantics;
            # this isolates the cursor-rollback property.
            await conn.run_sync(
                lambda c: c.execute(text("SELECT 1"))
            )
            raise RuntimeError("simulated migration failure")

    extended = [*list(MIGRATIONS), _BrokenFutureMigration()]

    with pytest.raises(RuntimeError, match="simulated migration failure"):
        await migrate(fresh_ledger, migrations=extended)

    # Cursor must NOT have advanced past the canonical max — the broken
    # migration rolled back.
    assert await current_version(fresh_ledger) == canonical_max

    # No row exists in _schema_migrations for the broken migration — the
    # bookkeeping INSERT was rolled back atomically with the migration body.
    async with fresh_ledger.engine.connect() as conn:
        result = await conn.execute(
            select(schema_migrations.c.version).where(
                schema_migrations.c.version == 99
            )
        )
        assert result.fetchone() is None, (
            "broken migration must not have left a v99 row behind"
        )
