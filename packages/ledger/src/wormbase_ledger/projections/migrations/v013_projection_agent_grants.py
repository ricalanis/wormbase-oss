"""v013 — create ``projection_agent_grants``.

Per-agent grants for both data and model access. Folded from
``agent_grant`` ledger entries (single kind, status field per Addendum 3).

Schema invariants:

* UNIQUE on ``(agent_id, grant_kind, grant_target)`` — one active grant
  per triple at a time; the ``status`` field flips to ``revoked`` rather
  than deleting the row, so the audit trail stays whole.
* ``grant_kind`` is enum-checked against
  {domain.read, resource.read, resource.maintainer, model.access} —
  the same Literal as ``AgentGrantPayload``.
* ``status`` is enum-checked against {active, revoked} per the
  status-field consolidation in Addendum 3.
* ``budget_remaining_usd`` is NUMERIC(18,4) and is NULLABLE — only
  ``model.access`` grants populate it; data grants leave it ``NULL``.

Backend portability: CHECK constraints emit uniformly on Postgres and
SQLite via ``CheckConstraint``. ``Numeric`` compiles to native NUMERIC
on Postgres and accepts the same precision on SQLite (stored as text
internally but round-trips losslessly).

Idempotency: ``checkfirst=True`` on ``Table.create``.
"""
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    func,
)


_metadata = MetaData()

projection_agent_grants = Table(
    "projection_agent_grants",
    _metadata,
    Column("id", String, primary_key=True),
    Column("company_id", String, nullable=False),
    Column("agent_id", String, nullable=False),
    Column("grant_kind", String, nullable=False),
    Column("grant_target", String, nullable=False),
    Column("status", String, nullable=False),
    Column("granted_by", String, nullable=False),
    Column(
        "granted_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("budget_remaining_usd", Numeric(18, 4), nullable=True),
    UniqueConstraint(
        "agent_id",
        "grant_kind",
        "grant_target",
        name="uq_projection_agent_grants_triple",
    ),
    CheckConstraint(
        "grant_kind IN ('domain.read', 'resource.read', 'resource.maintainer', 'model.access')",
        name="ck_projection_agent_grants_kind",
    ),
    CheckConstraint(
        "status IN ('active', 'revoked')",
        name="ck_projection_agent_grants_status",
    ),
    Index("idx_projection_agent_grants_company", "company_id"),
    Index("idx_projection_agent_grants_agent", "agent_id"),
)


def _create(conn) -> None:  # type: ignore[no-untyped-def]
    projection_agent_grants.create(conn, checkfirst=True)


class Migration:
    version: int = 13
    description: str = (
        "create projection_agent_grants — agent grants for data + model "
        "(status-field consolidated)"
    )

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.run_sync(_create)
