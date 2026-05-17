"""Postgres connector — async via asyncpg, no SQLAlchemy.

Reads `information_schema` for discovery and column profiling, and
`pg_stat_user_tables` for row-count estimates. asyncpg is used directly
because the connector is part of the agent's hot path (low-latency
discovery and sampling on demand) and we want to avoid SQLAlchemy
session overhead on a per-call basis.

Auth bundle:
    {"dsn": "postgresql://user:pass@host:5432/db"}
or  {"host": ..., "port": ..., "user": ..., "password": ..., "database": ...}

asyncpg DSNs use the bare ``postgresql://`` scheme — this connector
will normalize ``postgresql+asyncpg://`` (SQLAlchemy form) by stripping
the driver suffix before connecting.

Note on connection lifecycle: each async method opens its own
short-lived connection and closes it on return. We do not maintain a
pool here because the source-builder calls discover/profile/sample at
human cadence (once per minute at most). A future enhancement can
introduce an `asyncpg.Pool` keyed by `handle_id`.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from typing import Any

from .base import Connector
from .registry import register_connector
from .types import (
    AuthHandle,
    Capability,
    Change,
    ClassificationHint,
    Profile,
    ResourceProposal,
    SecretBundle,
)


def _normalize_dsn(dsn: str) -> str:
    """Strip SQLAlchemy driver suffix so asyncpg can parse the DSN."""
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


def _dsn_from_secrets(payload: dict[str, Any]) -> str:
    if "dsn" in payload and isinstance(payload["dsn"], str):
        return _normalize_dsn(payload["dsn"])
    required = ("host", "user", "database")
    if not all(k in payload for k in required):
        raise ValueError(
            "postgres connector requires {dsn} or "
            "{host, user, database, password?, port?}"
        )
    user = payload["user"]
    password = payload.get("password")
    host = payload["host"]
    port = payload.get("port", 5432)
    database = payload["database"]
    auth = f"{user}:{password}@" if password else f"{user}@"
    return f"postgresql://{auth}{host}:{port}/{database}"


@register_connector
class PostgresConnector(Connector):
    """Postgres connector via asyncpg."""

    kind = "postgres"
    capability: set[Capability] = {"discover", "profile", "sample"}
    classification_hints: list[ClassificationHint] = ["dsn_in_message"]
    status: str = "production"
    status_note: str = (
        "Production-grade. Discover walks information_schema; "
        "profile reads pg_stat; sample via SELECT … LIMIT n."
    )

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        dsn = _dsn_from_secrets(secrets.payload)
        # Validate DSN is reachable. We open and immediately close a
        # connection — failures surface as ValueError so the caller can
        # propose a credential_in_dm gate failure cleanly.
        import asyncpg

        try:
            conn = await asyncpg.connect(dsn=dsn)
        except Exception as exc:
            raise ValueError(f"postgres authenticate failed: {exc}") from exc
        try:
            version = await conn.fetchval("SELECT version()")
        finally:
            await conn.close()
        return AuthHandle(
            connector_kind="postgres",
            handle_id=hashlib.sha256(dsn.encode()).hexdigest()[:16],
            extra={"dsn": dsn, "version": version},
        )

    async def discover(self, handle: AuthHandle) -> list[ResourceProposal]:
        import asyncpg

        conn = await asyncpg.connect(dsn=handle.extra["dsn"])
        try:
            rows = await conn.fetch(
                """
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN
                    ('pg_catalog', 'information_schema', 'pg_toast')
                ORDER BY table_schema, table_name
                """
            )
        finally:
            await conn.close()
        proposals: list[ResourceProposal] = []
        for row in rows:
            schema = row["table_schema"]
            name = row["table_name"]
            qualified = f"{schema}.{name}"
            proposals.append(
                ResourceProposal(
                    resource_id=qualified,
                    name=qualified,
                    kind="table",
                    classification_hint=None,
                    metadata={
                        "schema": schema,
                        "table": name,
                        "table_type": row["table_type"],
                    },
                )
            )
        return proposals

    async def profile(self, handle: AuthHandle, resource_id: str) -> Profile:
        if "." not in resource_id:
            raise ValueError(
                f"postgres resource_id must be schema.table: {resource_id!r}"
            )
        schema, table = resource_id.split(".", 1)
        import asyncpg

        conn = await asyncpg.connect(dsn=handle.extra["dsn"])
        try:
            cols = await conn.fetch(
                """
                SELECT column_name, data_type, is_nullable, ordinal_position
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = $2
                ORDER BY ordinal_position
                """,
                schema,
                table,
            )
            row_count = await conn.fetchval(
                """
                SELECT n_live_tup
                FROM pg_stat_user_tables
                WHERE schemaname = $1 AND relname = $2
                """,
                schema,
                table,
            )
            # Fall back to COUNT(*) when pg_stat hasn't analyzed.
            if row_count is None:
                row_count = await conn.fetchval(
                    f'SELECT COUNT(*) FROM "{schema}"."{table}"'
                )
        finally:
            await conn.close()
        columns = [
            {
                "name": c["column_name"],
                "dtype": c["data_type"],
                "nullable": c["is_nullable"] == "YES",
                "ordinal": c["ordinal_position"],
            }
            for c in cols
        ]
        schema_hash = hashlib.sha256(
            ",".join(f"{c['name']}:{c['dtype']}" for c in columns).encode()
        ).hexdigest()[:16]
        return Profile(
            row_count=int(row_count) if row_count is not None else None,
            column_count=len(columns),
            columns=columns,
            schema_hash=schema_hash,
            extra={"schema": schema, "table": table},
        )

    async def sample(
        self, handle: AuthHandle, resource_id: str, n: int
    ) -> bytes:
        if "." not in resource_id:
            raise ValueError(
                f"postgres resource_id must be schema.table: {resource_id!r}"
            )
        schema, table = resource_id.split(".", 1)
        import asyncpg

        conn = await asyncpg.connect(dsn=handle.extra["dsn"])
        try:
            # asyncpg returns Record objects; we serialize as
            # tab-separated text — the source-builder's downstream
            # bronze writer accepts bytes and splits on TAB.
            rows = await conn.fetch(
                f'SELECT * FROM "{schema}"."{table}" LIMIT $1', n
            )
        finally:
            await conn.close()
        if not rows:
            return b""
        header = "\t".join(rows[0].keys())
        body_lines = [
            "\t".join("" if v is None else str(v) for v in r.values())
            for r in rows
        ]
        return ("\n".join([header, *body_lines]) + "\n").encode()

    async def watch(
        self, handle: AuthHandle, resource_id: str
    ) -> AsyncIterator[Change]:
        # CDC via logical replication is post-day-one work.
        if False:
            yield  # type: ignore[unreachable]


__all__ = ["PostgresConnector"]
