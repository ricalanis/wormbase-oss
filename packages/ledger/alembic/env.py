"""Alembic environment.

Reads WORMBASE_DB_URL from the environment. Supports both sync URLs
(`sqlite:///...`, `postgresql://...`) and async URLs (`postgresql+asyncpg://...`,
`sqlite+aiosqlite:///...`); async URLs are translated to sync for migrations.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from wormbase_ledger.schema import metadata

target_metadata = metadata


def _sync_url() -> str:
    url = os.environ["WORMBASE_DB_URL"]
    # Translate async drivers to their sync equivalents for migrations.
    return (
        url.replace("postgresql+asyncpg://", "postgresql://")
        .replace("sqlite+aiosqlite://", "sqlite://")
    )


def run_migrations_online() -> None:
    config_section = context.config.get_section(context.config.config_ini_section) or {}
    config_section["sqlalchemy.url"] = _sync_url()
    connectable = engine_from_config(
        config_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
