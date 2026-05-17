"""v012 — create ``projection_agents``.

A Person sub-type for external (Claude / OpenAI / Kimi / other) and
internal (worm-issued) agents. Folded from ``agent_registered`` ledger
entries; the /agents dashboard surface and the agent-gateway
``register_agent`` flow both read this projection.

Schema invariants:

* ``person_id`` is UNIQUE — one ``Person`` row backs each agent.
* ``external_provider`` is enum-checked against the
  ``AgentRegisteredPayload`` literal so the projection cannot drift
  silently from the payload schema.
* ``status`` is enum-checked against {active, inactive}; agents are
  never hard-deleted (audit lineage stays whole).

Backend portability: CHECK constraints are expressed as SQLAlchemy
``CheckConstraint`` objects so they emit uniformly on Postgres
(production) and SQLite (tests). ``DateTime(timezone=True)`` compiles
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

projection_agents = Table(
    "projection_agents",
    _metadata,
    Column("id", String, primary_key=True),
    Column("company_id", String, nullable=False),
    Column("person_id", String, nullable=False, unique=True),
    Column("external_provider", String, nullable=False),
    Column("display_name", String, nullable=False),
    Column(
        "registered_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("status", String, nullable=False, server_default="active"),
    CheckConstraint(
        "external_provider IN ('claude', 'openai', 'kimi', 'internal_worm', 'other')",
        name="ck_projection_agents_external_provider",
    ),
    CheckConstraint(
        "status IN ('active', 'inactive')",
        name="ck_projection_agents_status",
    ),
    Index("idx_projection_agents_company", "company_id"),
)


def _create(conn) -> None:  # type: ignore[no-untyped-def]
    projection_agents.create(conn, checkfirst=True)


class Migration:
    version: int = 12
    description: str = (
        "create projection_agents — agent identity (Person sub-type)"
    )

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.run_sync(_create)
