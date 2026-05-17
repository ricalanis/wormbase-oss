"""v003 — add ``last_seen`` to ``projection_sources``.

Required by LakeMaintainer's StalenessSignalReactivity: the maintenance
loop reads ``last_seen`` to decide when to re-profile a source. NULL on
existing rows means "never observed" — the maintainer treats those as
candidates for an immediate freshness probe.

Idempotency: same ALTER-with-presence-check pattern as v002.
"""
from __future__ import annotations

from sqlalchemy import Column, DateTime, inspect, text


_NEW_COLUMNS: tuple[Column, ...] = (
    Column("last_seen", DateTime(timezone=True), nullable=True),
)


def _existing_column_names(conn, table_name: str) -> set[str]:  # type: ignore[no-untyped-def]
    insp = inspect(conn)
    return {col["name"] for col in insp.get_columns(table_name)}


def _add_missing_columns(conn) -> None:  # type: ignore[no-untyped-def]
    existing = _existing_column_names(conn, "projection_sources")
    dialect = conn.dialect
    for col in _NEW_COLUMNS:
        if col.name in existing:
            continue
        type_sql = col.type.compile(dialect=dialect)
        null_sql = "NULL" if col.nullable else "NOT NULL"
        ddl = (
            f"ALTER TABLE projection_sources "
            f"ADD COLUMN {col.name} {type_sql} {null_sql}"
        )
        conn.execute(text(ddl))


class Migration:
    version: int = 3
    description: str = "add last_seen to projection_sources"

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.run_sync(_add_missing_columns)
