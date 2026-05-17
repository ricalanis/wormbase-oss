"""v024 — create ``projection_semantic_types``.

L5 lake-side compounding loop folded view of sample-data fingerprinting
proposals from inference strategies (column_name / value_pattern /
distribution) and confirmed/rejected by admin operators.

Folded from three ledger entry kinds (additive per schema-evolution
doctrine Rule 2; KIND_REGISTRY 117 → 120; 30 headroom under the
150-kind ceiling per Wave F Addendum 4):

* ``semantic_type_proposed`` → INSERT (or UPDATE evidence on
  re-proposal of the same ``type_id`` before resolution)
* ``semantic_type_confirmed`` → UPDATE state = "confirmed"
* ``semantic_type_rejected`` → UPDATE state = "rejected"

State transitions are forward-only — every state change is a new
ledger entry; no mutation of prior entries. Replay-stable: a re-fold
over the same ledger stream produces byte-identical projection rows
because the deterministic ``(company_id, type_id)`` primary key
collapses re-proposal onto the same row regardless of replay order.

Schema invariants:

* ``type_id`` is a deterministic hash of ``(table_id, column,
  semantic_type)`` minted upstream by the L5 inference service; the
  projection treats it as opaque.
* ``state`` ∈ {proposed, confirmed, rejected}. CHECK constraint pins
  the enum on both Postgres and SQLite.
* ``confidence`` is a Float in [0.0, 1.0]; the payload-side validator
  refuses out-of-range writes at ingest, so the column itself stays
  permissive (no CHECK) — the gate is at the ledger entry, not at the
  projection.
* ``semantic_type`` is one of 19 strict Literal values per spec §3.2;
  the column itself is plain String — drift prevention is enforced at
  the payload validator, not at the projection.
* ``state_changed_by`` is NULL when ``state == "proposed"`` (system-
  written by the Compounding axis), populated by the operator's
  Person UUID when state transitions to confirmed/rejected.

Backend portability: ``DateTime(timezone=True)`` compiles to
``TIMESTAMPTZ`` on Postgres and ``DATETIME`` on SQLite, matching the
pattern from v014/v015/v016/v021/v022/v023. ``evidence`` is JSON-typed
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


_TABLE_NAME: str = "projection_semantic_types"


def _build_table() -> Table:
    """Construct the projection_semantic_types Table on a fresh MetaData.

    Building a fresh MetaData on each call keeps the migration usable
    across multiple test engines without ``InvalidRequestError: Table
    is already defined`` (mirrors the v016/v021/v022/v023 pattern).
    Production runs apply once per boot per engine, so the fresh
    MetaData has no runtime cost.

    PK is composite ``(company_id, type_id)`` per spec §3.5; the
    pair is unique per tenant so re-proposal of the same logical
    semantic-type proposal folds onto the same row.
    """
    metadata = MetaData()
    return Table(
        _TABLE_NAME,
        metadata,
        Column("company_id", String, primary_key=True, nullable=False),
        Column("type_id", String, primary_key=True, nullable=False),
        Column("table_id", String, nullable=False),
        Column("column", String, nullable=False),
        Column("semantic_type", String, nullable=False),
        Column("confidence", Float, nullable=False),
        Column("strategy", String, nullable=False),
        Column("reasoning", Text, nullable=False),
        Column("evidence", JSON, nullable=False),
        Column("state", String, nullable=False),
        Column("state_changed_at", DateTime(timezone=True), nullable=False),
        Column("state_changed_by", String, nullable=True),
        CheckConstraint(
            "state IN ('proposed', 'confirmed', 'rejected')",
            name="ck_projection_semantic_types_state",
        ),
        Index(
            "ix_projection_semantic_types_state",
            "company_id",
            "state",
        ),
        Index(
            "ix_projection_semantic_types_table_id",
            "company_id",
            "table_id",
        ),
        Index(
            "ix_projection_semantic_types_semantic_type",
            "company_id",
            "semantic_type",
        ),
    )


def _create(sync_conn: Any) -> None:
    """Idempotent CREATE TABLE for projection_semantic_types.

    Builds a fresh MetaData + Table each call to stay compatible with
    multi-engine test suites. ``checkfirst=True`` short-circuits on
    re-apply so the migration is byte-stable across boots.
    """
    _build_table().create(sync_conn, checkfirst=True)


class Migration:
    version: int = 24
    description: str = (
        "create projection_semantic_types — L5 lake-side compounding-loop "
        "folded view of sample-data fingerprinting semantic-type proposals "
        "(proposed/confirmed/rejected); composite PK (company_id, type_id)"
    )

    async def up(self, conn: Any) -> None:
        await conn.run_sync(_create)
