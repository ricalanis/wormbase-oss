"""v014 — create ``projection_agent_queries``.

PEVR-collapsed view of every ``agent_query`` lifecycle: one row per
``audit_trail_id``, status tracks the latest phase the cycle has
reached. Folded from ``agent_query`` ledger entries (single kind,
phase field per Addendum 3).

Schema invariants:

* ``id`` is the ``audit_trail_id`` minted at the propose phase; all four
  PEVR entries for a single query share the same audit_trail_id.
* ``route_mode`` is enum-checked against {broker, federate} — the
  route taken by the gateway when satisfying the query.
* ``status`` is enum-checked against {propose, execute, verify, resolve,
  denied}. ``denied`` is the terminal state when a governance gate
  blocks the call before execute.
* ``args`` stores the opaque tool-specific JSON. We use SQLAlchemy
  ``JSON`` rather than a native JSONB column so the projection is
  byte-identical across Postgres (production) and SQLite (tests) —
  the same pattern v001/v011 use for ``tags`` / ``dimensions``.
* ``row_count`` / ``cost_usd`` / ``latency_ms`` are NULLABLE — the
  propose phase doesn't know them yet; they populate on verify/resolve.

Indexed on ``(agent_id, started_at)`` so the /agents detail surface
can fetch a Person's recent-query timeline without scanning the
projection.

Idempotency: ``checkfirst=True`` on ``Table.create``.
"""
from __future__ import annotations

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    func,
)


_metadata = MetaData()

projection_agent_queries = Table(
    "projection_agent_queries",
    _metadata,
    Column("id", String, primary_key=True),
    Column("company_id", String, nullable=False),
    Column("agent_id", String, nullable=False),
    Column("mcp_tool", String, nullable=False),
    Column("args", JSON, nullable=False),
    Column("route_mode", String, nullable=False),
    Column("status", String, nullable=False),
    Column("row_count", Integer, nullable=True),
    Column("cost_usd", Numeric(18, 4), nullable=True),
    Column("latency_ms", Integer, nullable=True),
    Column("caused_by", String, nullable=True),
    Column(
        "started_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint(
        "route_mode IN ('broker', 'federate')",
        name="ck_projection_agent_queries_route",
    ),
    CheckConstraint(
        "status IN ('propose', 'execute', 'verify', 'resolve', 'denied')",
        name="ck_projection_agent_queries_status",
    ),
    Index("idx_projection_agent_queries_company", "company_id"),
    Index(
        "idx_projection_agent_queries_agent_time",
        "agent_id",
        "started_at",
    ),
)


def _create(conn) -> None:  # type: ignore[no-untyped-def]
    projection_agent_queries.create(conn, checkfirst=True)


class Migration:
    version: int = 14
    description: str = (
        "create projection_agent_queries — single row per agent_query "
        "PEVR cycle (latest phase)"
    )

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.run_sync(_create)
