"""v021 — create ``projection_lineage_edges``.

L3 lake-side compounding loop folded view of lineage edges proposed
by inference strategies and confirmed/rejected by admin operators.

Folded from three ledger entry kinds (additive per schema-evolution
doctrine Rule 2; KIND_REGISTRY 106 → 109):

* ``lineage_edge_proposed`` → INSERT (or UPDATE evidence/confidence
  on re-proposal of the same ``edge_id`` before resolution)
* ``lineage_edge_confirmed`` → UPDATE state = "confirmed"
* ``lineage_edge_rejected`` → UPDATE state = "rejected"

State transitions are forward-only — every state change is a new
ledger entry; no mutation of prior entries. Replay-stable: a re-fold
over the same ledger stream produces byte-identical projection rows
because the deterministic ``(company_id, edge_id)`` primary key
collapses re-proposal onto the same row regardless of replay order.

Schema invariants:

* ``edge_id`` is a deterministic hash of
  ``(src_table_id, src_column, tgt_table_id, tgt_column)`` minted
  upstream by the L3 inference service; the projection treats it as
  opaque.
* ``state`` ∈ {proposed, confirmed, rejected}. CHECK constraint pins
  the enum on both Postgres and SQLite.
* ``confidence`` is a Float in [0.0, 1.0]; the payload-side validator
  refuses out-of-range writes at ingest, so the column itself stays
  permissive (no CHECK) — the gate is at the ledger entry, not at the
  projection.
* ``src_column`` / ``tgt_column`` may be NULL to express a whole-
  table edge (common for dbt-manifest-derived lineage).
* ``state_changed_by`` is NULL when ``state == "proposed"`` (system-
  written by the Compounding axis), populated by the operator's
  Person UUID when state transitions to confirmed/rejected.

Backend portability: ``DateTime(timezone=True)`` compiles to
``TIMESTAMPTZ`` on Postgres and ``DATETIME`` on SQLite, matching the
pattern from v014/v015/v016. ``evidence`` is JSON-typed for byte-
identical round-trip across both dialects.

Idempotency: ``checkfirst=True`` on ``Table.create``. Forward-only
per the projections/migrations doctrine — no ``down`` method.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    Index,
    MetaData,
    String,
    Table,
    Text,
)


_TABLE_NAME: str = "projection_lineage_edges"


def _build_table() -> Table:
    """Construct the projection_lineage_edges Table on a fresh MetaData.

    Building a fresh MetaData on each call keeps the migration usable
    across multiple test engines without ``InvalidRequestError: Table
    is already defined`` (mirrors the v016 pattern). Production runs
    apply once per boot per engine, so the fresh MetaData has no
    runtime cost.

    PK is composite ``(company_id, edge_id)`` per spec §3.5; the
    pair is unique per tenant so re-proposal of the same logical
    edge folds onto the same row.
    """
    metadata = MetaData()
    return Table(
        _TABLE_NAME,
        metadata,
        Column("company_id", String, primary_key=True, nullable=False),
        Column("edge_id", String, primary_key=True, nullable=False),
        Column("src_table_id", String, nullable=False),
        Column("src_column", String, nullable=True),
        Column("tgt_table_id", String, nullable=False),
        Column("tgt_column", String, nullable=True),
        Column("confidence", Float, nullable=False),
        Column("strategy", String, nullable=False),
        Column("reasoning", Text, nullable=False),
        Column("evidence", JSON, nullable=False),
        Column("state", String, nullable=False),
        Column("state_changed_at", DateTime(timezone=True), nullable=False),
        Column("state_changed_by", String, nullable=True),
        CheckConstraint(
            "state IN ('proposed', 'confirmed', 'rejected')",
            name="ck_projection_lineage_edges_state",
        ),
        Index(
            "ix_projection_lineage_edges_state",
            "company_id",
            "state",
        ),
        Index(
            "ix_projection_lineage_edges_src",
            "company_id",
            "src_table_id",
        ),
        Index(
            "ix_projection_lineage_edges_tgt",
            "company_id",
            "tgt_table_id",
        ),
    )


def _create(sync_conn: Any) -> None:
    """Idempotent CREATE TABLE for projection_lineage_edges.

    Builds a fresh MetaData + Table each call to stay compatible with
    multi-engine test suites. ``checkfirst=True`` short-circuits on
    re-apply so the migration is byte-stable across boots.
    """
    _build_table().create(sync_conn, checkfirst=True)


class Migration:
    version: int = 21
    description: str = (
        "create projection_lineage_edges — L3 lake-side compounding-loop "
        "folded view of lineage edges (proposed/confirmed/rejected); "
        "composite PK (company_id, edge_id)"
    )

    async def up(self, conn: Any) -> None:
        await conn.run_sync(_create)
