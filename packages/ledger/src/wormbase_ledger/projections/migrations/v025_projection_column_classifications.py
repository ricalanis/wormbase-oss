"""v025 — create ``projection_column_classifications``.

L6 lake-side compounding-loop folded view of column-level governance
classification proposals from inference strategies (semantic_type /
naming_pattern / domain_default) and confirmed/rejected by admin
operators.

Folded from three ledger entry kinds (additive per schema-evolution
doctrine Rule 2; KIND_REGISTRY 120 → 123; 27 headroom under the 150-
kind ceiling per Wave F Addendum 4; L-axis family count 12 → 15 of
30 cap per Addendum 4 §E):

* ``column_classification_proposed`` → INSERT (or UPDATE evidence on
  re-proposal of the same ``classification_id`` before resolution)
* ``column_classification_confirmed`` → UPDATE state = "confirmed"
* ``column_classification_rejected`` → UPDATE state = "rejected"

State transitions are forward-only — every state change is a new
ledger entry; no mutation of prior entries. Replay-stable: a re-fold
over the same ledger stream produces byte-identical projection rows
because the deterministic ``(company_id, classification_id)``
primary key collapses re-proposal onto the same row regardless of
replay order.

Schema invariants:

* ``classification_id`` is a deterministic hash of ``(table_id,
  column, classification_level, strategy)`` minted upstream by the
  L6 inference service; the projection treats it as opaque.
* ``state`` ∈ {proposed, confirmed, rejected}. CHECK constraint pins
  the enum on both Postgres and SQLite.
* ``confidence`` is a Float in [0.0, 1.0]; the payload-side validator
  refuses out-of-range writes at ingest, so the column itself stays
  permissive (no CHECK) — the gate is at the ledger entry, not at the
  projection.
* ``classification_level`` is one of 5 strict ``ClassificationLevel``
  Literal values {public, internal, confidential, pii, regulated};
  the column itself is plain String — drift prevention is enforced
  at the payload validator, not at the projection.
* ``upstream_semantic_type_id`` is NULL-able — populated when the
  proposing strategy was ``semantic_type`` (the L6→L5 cross-axis
  chain), NULL when the strategy was ``naming_pattern`` or
  ``domain_default``. The /lake/column-classification surface uses
  this to render the "view L5 semantic type →" link only when set.
* ``state_changed_by`` is NULL when ``state == "proposed"`` (system-
  written by the Compounding axis), populated by the operator's
  Person UUID when state transitions to confirmed/rejected.

Backend portability: ``DateTime(timezone=True)`` compiles to
``TIMESTAMPTZ`` on Postgres and ``DATETIME`` on SQLite, matching the
pattern from v014/v015/v016/v021/v022/v023/v024. ``evidence`` is
JSON-typed for byte-identical round-trip across both dialects.

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


_TABLE_NAME: str = "projection_column_classifications"


def _build_table() -> Table:
    """Construct the projection_column_classifications Table on a fresh
    MetaData.

    Building a fresh MetaData on each call keeps the migration usable
    across multiple test engines without ``InvalidRequestError: Table
    is already defined`` (mirrors the v016/v021/v022/v023/v024
    pattern). Production runs apply once per boot per engine, so the
    fresh MetaData has no runtime cost.

    PK is composite ``(company_id, classification_id)`` per spec §4.5;
    the pair is unique per tenant so re-proposal of the same logical
    column-classification proposal folds onto the same row.
    """
    metadata = MetaData()
    return Table(
        _TABLE_NAME,
        metadata,
        Column("company_id", String, primary_key=True, nullable=False),
        Column("classification_id", String, primary_key=True, nullable=False),
        Column("table_id", String, nullable=False),
        Column("column", String, nullable=False),
        Column("classification_level", String, nullable=False),
        Column("upstream_semantic_type_id", String, nullable=True),
        Column("confidence", Float, nullable=False),
        Column("strategy", String, nullable=False),
        Column("reasoning", Text, nullable=False),
        Column("evidence", JSON, nullable=False),
        Column("state", String, nullable=False),
        Column("state_changed_at", DateTime(timezone=True), nullable=False),
        Column("state_changed_by", String, nullable=True),
        CheckConstraint(
            "state IN ('proposed', 'confirmed', 'rejected')",
            name="ck_projection_column_classifications_state",
        ),
        Index(
            "ix_projection_column_classifications_state",
            "company_id",
            "state",
        ),
        Index(
            "ix_projection_column_classifications_table_id",
            "company_id",
            "table_id",
        ),
        Index(
            "ix_projection_column_classifications_level",
            "company_id",
            "classification_level",
        ),
    )


def _create(sync_conn: Any) -> None:
    """Idempotent CREATE TABLE for projection_column_classifications.

    Builds a fresh MetaData + Table each call to stay compatible with
    multi-engine test suites. ``checkfirst=True`` short-circuits on
    re-apply so the migration is byte-stable across boots.
    """
    _build_table().create(sync_conn, checkfirst=True)


class Migration:
    version: int = 25
    description: str = (
        "create projection_column_classifications — L6 lake-side "
        "compounding-loop folded view of column-level governance "
        "classification proposals (proposed/confirmed/rejected); "
        "composite PK (company_id, classification_id)"
    )

    async def up(self, conn: Any) -> None:
        await conn.run_sync(_create)
