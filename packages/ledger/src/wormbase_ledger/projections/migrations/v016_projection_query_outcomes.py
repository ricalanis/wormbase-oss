"""v016 — create ``projection_query_outcomes``.

§4.5 compounding-layer outcome ledger. Folded from
``query_outcome_recorded`` entries (one row per recorded outcome).

Embedding is dialect-aware: ``Vector(1536)`` on Postgres (via pgvector
≥0.6) and ``JSON`` on SQLite (tests). The Postgres path issues
``CREATE EXTENSION IF NOT EXISTS vector`` before creating the table;
the SQLite path stores the embedding as a JSON array so unit tests
don't depend on a binary extension. Vector ops are a no-op on the
SQLite shape — projections that need similarity search are
Postgres-only at runtime.

NOTE (v2.B Phase 3b, 2026-05-12): the 1536-dim pin in this migration is
SUPERSEDED by v018, which resizes the column to 768 dim to match the
nomic-embed-text model wired in v2.B Phase 3b. The 1536-dim shape here
is preserved for replay determinism — fresh installs apply v016 (1536)
then immediately v018 (768) in order. The column has been ALWAYS NULL
since v016 landed; the resize is data-loss-free by construction.

Schema invariants:

* ``id`` is the entry_id of the originating ``query_outcome_recorded``
  ledger row.
* ``agent_query_id`` is a back-reference to the ``audit_trail_id`` of
  the closed PEVR cycle that produced the outcome. Indexed so the
  agent-detail surface can fetch the cycle's outcome timeline cheaply.
* ``quality_score`` is ``NUMERIC(6, 4)`` — the on-the-wire payload
  carries the score as a string Decimal in [0.0, 1.0]; the projection
  upcasts to a fixed-precision numeric for index-friendly comparisons.
* ``used`` and ``useful`` are booleans the agent supplies after user
  feedback; both are required (no NULL "unknown" states — agents must
  resolve the outcome before recording).

Backend portability: ``DateTime(timezone=True)`` compiles to
``TIMESTAMPTZ`` on Postgres and ``DATETIME`` on SQLite, matching the
pattern from v014/v015.

Idempotency: ``checkfirst=True`` on ``Table.create``.
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa


def _embedding_column(dialect_name: str | None) -> sa.Column:
    """Return the dialect-appropriate embedding column.

    Postgres production deployments require pgvector ≥0.6 — the
    ``Vector(1536)`` shape matches OpenAI ``text-embedding-3-small``
    output. SQLite test runs fall back to a JSON list so the column
    is structurally present (and round-trippable) without requiring
    a binary extension.
    """
    if dialect_name == "postgresql":
        from pgvector.sqlalchemy import Vector  # type: ignore[import-not-found]

        return sa.Column("embedding", Vector(1536), nullable=True)
    return sa.Column("embedding", sa.JSON, nullable=True)


class Migration:
    version: int = 16
    description: str = (
        "create projection_query_outcomes — §4.5 outcome ledger "
        "(pgvector embedding on Postgres, JSON on SQLite)"
    )

    async def up(self, conn: Any) -> None:
        await conn.run_sync(self._create)

    def _create(self, sync_conn: Any) -> None:
        dialect = sync_conn.dialect.name if sync_conn.dialect else None
        embedding_col = _embedding_column(dialect)
        if dialect == "postgresql":
            sync_conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

        # Build a fresh MetaData on each call: the same Migration
        # instance is reused across multiple test engines, and binding
        # the same Table to a long-lived MetaData would raise
        # ``InvalidRequestError: Table is already defined``. Migrations
        # using a static module-level MetaData (v001-v015) only land
        # once per process, so they don't hit this case.
        metadata = sa.MetaData()
        table = sa.Table(
            "projection_query_outcomes",
            metadata,
            sa.Column("id", sa.String, primary_key=True),
            sa.Column("company_id", sa.String, nullable=False),
            sa.Column("agent_query_id", sa.String, nullable=False),
            sa.Column("nl_question", sa.Text, nullable=False),
            sa.Column("final_query_spec", sa.JSON, nullable=False),
            sa.Column("result_summary", sa.JSON, nullable=False),
            sa.Column("used", sa.Boolean, nullable=False),
            sa.Column("useful", sa.Boolean, nullable=False),
            sa.Column("user_correction", sa.Text, nullable=True),
            sa.Column("quality_score", sa.Numeric(6, 4), nullable=False),
            embedding_col,
            sa.Column(
                "recorded_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Index(
                "idx_projection_query_outcomes_company",
                "company_id",
            ),
            sa.Index(
                "idx_projection_query_outcomes_agent_query",
                "agent_query_id",
            ),
        )
        table.create(sync_conn, checkfirst=True)
