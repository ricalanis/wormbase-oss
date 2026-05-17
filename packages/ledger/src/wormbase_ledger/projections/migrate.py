"""Boot-time schema-migration runner.

Tracks applied migrations in ``_schema_migrations`` and applies any
pending migrations in version order. Backend-portable: works on
Postgres (production) and SQLite (tests). Tenant-agnostic — the
projection schema is shared across tenants, so this runs once per
worm-core boot, not per tenant.

Why this exists
---------------
``metadata.create_all`` is idempotent for *creating* tables but does
nothing for *altering* them. When a column is added to ``schema.py``
(e.g. ``projection_installs.setup_mode``) on an already-running DB,
``metadata.create_all`` is silently a no-op for the new column, and
reads/writes that touch it crash with "column does not exist". The
operator workaround was ``docker volume rm wormbase-postgres-data``,
which trashes ledger entries — unacceptable.

This runner closes the gap by applying versioned migrations on every
boot. ``_schema_migrations`` records ``(version, applied_at)`` per
applied step; pending steps are detected by ``MAX(version)`` and
applied in order inside their own transactions. Failure rolls back
the failing migration only — successful prior migrations stay
applied.

No downgrades
-------------
Forward-only. Migrations capture additive deltas; rolling back a
schema requires either a manual ``DROP COLUMN`` (operator action) or
a fresh rebuild from the ledger. The append-only ledger is the
durable substrate; projections are derived state.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    MetaData,
    Table,
    func,
    select,
)

if TYPE_CHECKING:
    from wormbase_ledger.ledger_api import Ledger
    from wormbase_ledger.projections.migrations import Migration


logger = logging.getLogger("wormbase_ledger.projections.migrate")


# ``_schema_migrations`` is OWNED by the migration runner, not by
# ``schema.py``. Keeping it separate makes it clear that this is
# bookkeeping for the migrator itself; ``schema.py`` describes the
# projection surface, not its versioning.
_migrations_metadata = MetaData()

schema_migrations = Table(
    "_schema_migrations",
    _migrations_metadata,
    Column("version", BigInteger, primary_key=True),
    Column("applied_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


async def _ensure_bookkeeping_table(conn) -> None:  # type: ignore[no-untyped-def]
    """Create ``_schema_migrations`` if missing. Idempotent."""
    await conn.run_sync(_migrations_metadata.create_all)


async def _applied_versions(conn) -> set[int]:  # type: ignore[no-untyped-def]
    """Return the set of versions already applied."""
    result = await conn.execute(select(schema_migrations.c.version))
    return {row[0] for row in result.fetchall()}


async def migrate(
    ledger: Ledger,
    *,
    migrations: list[Migration] | None = None,
) -> list[int]:
    """Apply pending migrations against the ledger's database.

    Returns the list of versions newly applied (in order). When the
    DB is already current this returns ``[]``.

    Each migration runs inside its own transaction:
    - ``conn = await engine.begin()``  (transaction starts)
    - ``await migration.up(conn)``
    - ``INSERT INTO _schema_migrations``
    - on success: COMMIT (transaction context exit)
    - on failure: ROLLBACK + re-raise (transaction context exit on error)

    Successful prior migrations remain applied; the operator sees
    exactly which version failed and can fix it before retrying.

    Pass ``migrations`` to inject a custom list (used by tests). Default
    is the project's canonical list from
    ``wormbase_ledger.projections.migrations``.
    """
    # Lazy import to avoid an import cycle: ``migrations/__init__.py``
    # imports the concrete migration modules; the migrate() entrypoint
    # is referenced by tests that may want to swap in a fake list.
    if migrations is None:
        from wormbase_ledger.projections.migrations import MIGRATIONS

        migrations = list(MIGRATIONS)

    # Guard against accidental gaps / duplicates in the migration list.
    versions = [m.version for m in migrations]
    if versions != sorted(versions):
        raise RuntimeError(
            f"migrations must be ordered by version; got {versions}"
        )
    if len(versions) != len(set(versions)):
        raise RuntimeError(
            f"duplicate migration versions: {versions}"
        )

    engine = ledger.engine

    # Bookkeeping table is created in its own short transaction so the
    # subsequent SELECT runs against a committed table on every backend.
    async with engine.begin() as conn:
        await _ensure_bookkeeping_table(conn)

    async with engine.connect() as conn:
        applied = await _applied_versions(conn)

    cursor = max(applied) if applied else 0
    pending = [m for m in migrations if m.version > cursor]

    if not pending:
        logger.info(
            "schema migrations: up-to-date (cursor=%d, %d known migrations)",
            cursor, len(migrations),
        )
        return []

    newly_applied: list[int] = []
    for m in pending:
        logger.info(
            "applying schema migration v%03d: %s",
            m.version, m.description,
        )
        # Each migration in its own transaction. On failure the
        # transaction rolls back; the migrator stops at the failed
        # version. ``newly_applied`` reflects only fully-committed
        # migrations.
        async with engine.begin() as conn:
            await m.up(conn)
            await conn.execute(
                schema_migrations.insert().values(version=m.version)
            )
        newly_applied.append(m.version)
        logger.info("schema migration v%03d applied", m.version)

    logger.info(
        "schema migrations complete: applied=%s",
        newly_applied,
    )
    return newly_applied


async def current_version(ledger: Ledger) -> int:
    """Return the highest applied migration version (0 if none applied).

    Useful for runtime preconditions — e.g. the projection_runner can
    refuse to start if the schema is older than its expected baseline.
    """
    engine = ledger.engine
    async with engine.begin() as conn:
        await _ensure_bookkeeping_table(conn)
    async with engine.connect() as conn:
        applied = await _applied_versions(conn)
    return max(applied) if applied else 0
