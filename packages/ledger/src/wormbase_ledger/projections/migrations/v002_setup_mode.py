"""v002 — add ``setup_mode`` and ``setup_completed_at`` to ``projection_installs``.

Closes the schema-drift gap from the live tutorial run (2026-04-28
~03:00 local): Block G of the connector-first onboarding PRD added
these two columns to ``projection_installs`` after the table was
already created on running databases. Without a migration step the
columns simply never landed; the projection_runner then crashed on
inserts that referenced them, and the only known workaround was
``docker volume rm wormbase-postgres-data`` (loses ledger entries).

Idempotency strategy
--------------------
Postgres supports ``ALTER TABLE ADD COLUMN IF NOT EXISTS`` natively;
SQLite (used in tests) does NOT. So we inspect the current columns
and only emit ``ADD COLUMN`` for those that are missing. The check +
the alter run inside the same transaction the migrator opens for
this version, so any concurrent boot will block on the first
migrator's lock and see the columns already present on its turn.

Backend portability
-------------------
The ALTER TABLE statement is dialect-compiled at apply time via
``Type.compile(dialect=conn.dialect)`` so the column type is
rendered correctly for whichever backend is in use (e.g.
``DATETIME`` on SQLite, ``TIMESTAMP WITH TIME ZONE`` on Postgres).
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, String, inspect, text

_NEW_COLUMNS: tuple[Column, ...] = (
    # ``setup_mode`` ∈ {wizard, bot, NULL}. NULL means the user has
    # not yet picked a fork in the connector-first onboarding flow;
    # the redirect guard treats null as "still in T2".
    Column("setup_mode", String(8), nullable=True),
    # ``setup_completed_at`` stamps the moment the bot-path or
    # wizard-path setup conversation reached its terminal step. NULL
    # while setup is in progress.
    Column("setup_completed_at", DateTime(timezone=True), nullable=True),
)


def _existing_column_names(conn, table_name: str) -> set[str]:  # type: ignore[no-untyped-def]
    """Return the set of column names currently on ``table_name``.

    Uses SQLAlchemy's ``inspect`` so the same code works on Postgres
    (information_schema-backed) and SQLite (PRAGMA-backed).
    """
    insp = inspect(conn)
    return {col["name"] for col in insp.get_columns(table_name)}


def _add_missing_columns(conn) -> None:  # type: ignore[no-untyped-def]
    """Add any of ``_NEW_COLUMNS`` that aren't yet on the table.

    Runs against a *sync* connection (the migrator invokes us via
    ``conn.run_sync``). Uses the connection's dialect to compile
    each column's type for the correct backend.
    """
    existing = _existing_column_names(conn, "projection_installs")
    dialect = conn.dialect
    for col in _NEW_COLUMNS:
        if col.name in existing:
            continue
        type_sql = col.type.compile(dialect=dialect)
        null_sql = "NULL" if col.nullable else "NOT NULL"
        # The column name is a hard-coded literal from _NEW_COLUMNS,
        # not user input — no SQL-injection risk. Same for the table
        # name. Type SQL is dialect-compiled so it's safe.
        ddl = (
            f"ALTER TABLE projection_installs "
            f"ADD COLUMN {col.name} {type_sql} {null_sql}"
        )
        conn.execute(text(ddl))


class Migration:
    """v002 — additive: ``setup_mode`` + ``setup_completed_at``.

    Idempotent: each ADD COLUMN is guarded by a presence check so a
    re-run against a database that already has the columns is a
    no-op.
    """

    version: int = 2
    description: str = (
        "add setup_mode + setup_completed_at to projection_installs"
    )

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.run_sync(_add_missing_columns)
