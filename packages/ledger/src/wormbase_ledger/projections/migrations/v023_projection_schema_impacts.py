"""v023 — create ``projection_schema_impacts``.

L4 lake-side compounding loop folded view of schema-evolution
impacts proposed by inference strategies (lineage_edge / dbt_test /
type_coercion) and confirmed/rejected by admin operators.

Folded from three ledger entry kinds (additive per schema-evolution
doctrine Rule 2; KIND_REGISTRY 114 → 117; 3 headroom under the
120-kind ceiling per Wave F Addendum 1):

* ``schema_impact_proposed`` → INSERT (or UPDATE evidence on
  re-proposal of the same ``impact_id`` before resolution)
* ``schema_impact_confirmed`` → UPDATE state = "confirmed"
* ``schema_impact_rejected`` → UPDATE state = "rejected"

State transitions are forward-only — every state change is a new
ledger entry; no mutation of prior entries. Replay-stable: a re-fold
over the same ledger stream produces byte-identical projection rows
because the deterministic ``(company_id, impact_id)`` primary key
collapses re-proposal onto the same row regardless of replay order.

Schema invariants:

* ``impact_id`` is a deterministic hash of
  ``(source_id, src_table, src_column, change_kind, tgt_table_id,
  tgt_column)`` minted upstream by the L4 inference service; the
  projection treats it as opaque.
* ``state`` ∈ {proposed, confirmed, rejected}. CHECK constraint pins
  the enum on both Postgres and SQLite.
* ``confidence`` is a Float in [0.0, 1.0]; the payload-side validator
  refuses out-of-range writes at ingest, so the column itself stays
  permissive (no CHECK) — the gate is at the ledger entry, not at the
  projection.
* ``upstream_lineage_edge_id`` is NULLABLE — ``type_coercion``-strategy
  proposals derive from sample-stats rather than a confirmed L3 edge
  and carry NULL; ``lineage_edge`` / ``dbt_test`` strategy proposals
  populate the field.
* ``state_changed_by`` is NULL when ``state == "proposed"`` (system-
  written by the Compounding axis), populated by the operator's
  Person UUID when state transitions to confirmed/rejected.

Backend portability: ``DateTime(timezone=True)`` compiles to
``TIMESTAMPTZ`` on Postgres and ``DATETIME`` on SQLite, matching the
pattern from v014/v015/v016/v021/v022. ``evidence`` is JSON-typed
for byte-identical round-trip across both dialects.

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


_TABLE_NAME: str = "projection_schema_impacts"


def _build_table() -> Table:
    """Construct the projection_schema_impacts Table on a fresh MetaData.

    Building a fresh MetaData on each call keeps the migration usable
    across multiple test engines without ``InvalidRequestError: Table
    is already defined`` (mirrors the v016/v021/v022 pattern). Production
    runs apply once per boot per engine, so the fresh MetaData has no
    runtime cost.

    PK is composite ``(company_id, impact_id)`` per spec §3.5; the
    pair is unique per tenant so re-proposal of the same logical
    impact folds onto the same row.
    """
    metadata = MetaData()
    return Table(
        _TABLE_NAME,
        metadata,
        Column("company_id", String, primary_key=True, nullable=False),
        Column("impact_id", String, primary_key=True, nullable=False),
        Column("source_id", String, nullable=False),
        Column("src_table", String, nullable=False),
        Column("src_column", String, nullable=False),
        Column("change_kind", String, nullable=False),
        Column("impact_kind", String, nullable=False),
        Column("tgt_table_id", String, nullable=False),
        Column("tgt_column", String, nullable=False),
        Column("upstream_lineage_edge_id", String, nullable=True),
        Column("confidence", Float, nullable=False),
        Column("strategy", String, nullable=False),
        Column("reasoning", Text, nullable=False),
        Column("evidence", JSON, nullable=False),
        Column("state", String, nullable=False),
        Column("state_changed_at", DateTime(timezone=True), nullable=False),
        Column("state_changed_by", String, nullable=True),
        CheckConstraint(
            "state IN ('proposed', 'confirmed', 'rejected')",
            name="ck_projection_schema_impacts_state",
        ),
        Index(
            "ix_projection_schema_impacts_state",
            "company_id",
            "state",
        ),
        Index(
            "ix_projection_schema_impacts_source",
            "company_id",
            "source_id",
        ),
        Index(
            "ix_projection_schema_impacts_tgt_table",
            "company_id",
            "tgt_table_id",
        ),
        Index(
            "ix_projection_schema_impacts_change_kind",
            "company_id",
            "change_kind",
        ),
    )


def _create(sync_conn: Any) -> None:
    """Idempotent CREATE TABLE for projection_schema_impacts.

    Builds a fresh MetaData + Table each call to stay compatible with
    multi-engine test suites. ``checkfirst=True`` short-circuits on
    re-apply so the migration is byte-stable across boots.
    """
    _build_table().create(sync_conn, checkfirst=True)


class Migration:
    version: int = 23
    description: str = (
        "create projection_schema_impacts — L4 lake-side compounding-loop "
        "folded view of schema-evolution impacts (proposed/confirmed/rejected); "
        "composite PK (company_id, impact_id)"
    )

    async def up(self, conn: Any) -> None:
        await conn.run_sync(_create)
