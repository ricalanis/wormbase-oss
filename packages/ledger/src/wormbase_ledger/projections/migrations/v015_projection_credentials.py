"""v015 — create ``projection_credentials``.

Lifecycle of every CredentialBroker-issued, scoped, time-bounded
token. Folded from ``credential`` ledger entries (single kind, status
field per Addendum 3). Covers both data tokens (Snowflake JWT, dbt
artifacts URL, etc.) and model tokens (Anthropic / Kimi / Gemma
scoped keys).

Schema invariants:

* ``credential_kind`` is enum-checked against {data, model} — the
  same Literal as ``CredentialPayload.credential_kind``.
* ``status`` is enum-checked against {active, revoked} per the
  status-field consolidation in Addendum 3. Revoked credentials are
  not deleted; the audit trail of an issued-then-revoked token must
  remain intact.
* ``target`` is opaque to the projection — resource_id for data,
  model_kind for model. The projection does not need to interpret it.

Backend portability: CHECK constraints emit uniformly on Postgres and
SQLite via ``CheckConstraint``. ``DateTime(timezone=True)`` compiles
to ``TIMESTAMPTZ`` on Postgres and ``DATETIME`` on SQLite.

Idempotency: ``checkfirst=True`` on ``Table.create``.
"""
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    MetaData,
    String,
    Table,
    func,
)


_metadata = MetaData()

projection_credentials = Table(
    "projection_credentials",
    _metadata,
    Column("id", String, primary_key=True),
    Column("company_id", String, nullable=False),
    Column("agent_id", String, nullable=False),
    Column("credential_kind", String, nullable=False),
    Column("target", String, nullable=False),
    Column("status", String, nullable=False),
    Column("ttl_expires_at", DateTime(timezone=True), nullable=False),
    Column("issued_by", String, nullable=False),
    Column(
        "issued_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint(
        "credential_kind IN ('data', 'model')",
        name="ck_projection_credentials_kind",
    ),
    CheckConstraint(
        "status IN ('active', 'revoked')",
        name="ck_projection_credentials_status",
    ),
    Index("idx_projection_credentials_company", "company_id"),
    Index("idx_projection_credentials_agent", "agent_id"),
)


def _create(conn) -> None:  # type: ignore[no-untyped-def]
    projection_credentials.create(conn, checkfirst=True)


class Migration:
    version: int = 15
    description: str = (
        "create projection_credentials — issued tokens for data + model "
        "(status-field consolidated)"
    )

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.run_sync(_create)
