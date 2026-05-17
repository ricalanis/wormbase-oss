"""v017 — create ``projection_query_templates``.

§4.5 compounding-layer template registry. Folded from
``query_template_promoted`` entries — one row per promoted template,
keyed by entry_id.

Embedding is dialect-aware (same pattern as v016): ``Vector(1536)`` on
Postgres (via pgvector ≥0.6) and ``JSON`` on SQLite (tests). The
embedding semantically clusters templates by NL intent so future
queries can hit a cached template via similarity search.

NOTE (v2.B Phase 3b, 2026-05-12): the 1536-dim pin is SUPERSEDED by
v018 — see v016's matching note. The column was always-NULL until
v2.B Phase 3b, so the 1536→768 resize is data-loss-free.

Schema invariants:

* ``id`` is the entry_id of the originating ``query_template_promoted``
  ledger row.
* ``domain_id`` scopes the template to a single domain; the canonical
  query layer doesn't share templates across domains because
  privilege boundaries and ontology differ.
* ``promoted_from_outcome_ids`` is a JSON array of the outcome
  audit-trail IDs that drove the promotion — full provenance back to
  the observed-outcome cluster.
* ``quality_score`` is ``NUMERIC(6, 4)`` — same shape as v016's outcome
  quality score; both originate as Decimal-as-string payloads.
* ``hit_count`` is an integer reuse counter with ``DEFAULT 0`` — the
  query path increments it on each cache hit so the admin surface can
  surface high-value templates.

Backend portability: ``DateTime(timezone=True)`` compiles to
``TIMESTAMPTZ`` on Postgres and ``DATETIME`` on SQLite.

Idempotency: ``checkfirst=True`` on ``Table.create``.
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa


def _embedding_column(dialect_name: str | None) -> sa.Column:
    """Return the dialect-appropriate embedding column.

    Mirrors v016's helper — pgvector ``Vector(1536)`` on Postgres,
    ``JSON`` list fallback on SQLite. Kept as a per-module helper
    rather than a shared util because each migration owns its
    schema independently (no cross-migration imports).
    """
    if dialect_name == "postgresql":
        from pgvector.sqlalchemy import Vector  # type: ignore[import-not-found]

        return sa.Column("embedding", Vector(1536), nullable=True)
    return sa.Column("embedding", sa.JSON, nullable=True)


class Migration:
    version: int = 17
    description: str = (
        "create projection_query_templates — §4.5 template registry "
        "(pgvector embedding on Postgres, JSON on SQLite)"
    )

    async def up(self, conn: Any) -> None:
        await conn.run_sync(self._create)

    def _create(self, sync_conn: Any) -> None:
        dialect = sync_conn.dialect.name if sync_conn.dialect else None
        embedding_col = _embedding_column(dialect)
        if dialect == "postgresql":
            sync_conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

        # Fresh MetaData per call so the same Migration instance is
        # reusable across multiple engines (the test suite shares one
        # Migration instance between many in-memory SQLite engines).
        # See v016's matching comment for the full rationale.
        metadata = sa.MetaData()
        table = sa.Table(
            "projection_query_templates",
            metadata,
            sa.Column("id", sa.String, primary_key=True),
            sa.Column("company_id", sa.String, nullable=False),
            sa.Column("domain_id", sa.String, nullable=False),
            sa.Column("nl_intent", sa.Text, nullable=False),
            sa.Column("query_spec", sa.JSON, nullable=False),
            sa.Column("promoted_from_outcome_ids", sa.JSON, nullable=False),
            sa.Column("quality_score", sa.Numeric(6, 4), nullable=False),
            sa.Column(
                "hit_count",
                sa.Integer,
                nullable=False,
                server_default=sa.text("0"),
            ),
            embedding_col,
            sa.Column(
                "promoted_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Index(
                "idx_projection_query_templates_company",
                "company_id",
            ),
            sa.Index(
                "idx_projection_query_templates_domain",
                "domain_id",
            ),
        )
        table.create(sync_conn, checkfirst=True)
