"""v026 — create ``projection_entity_stitches``.

L8 lake-side compounding-loop folded view of cross-source
entity-stitch proposals from inference strategies (name_match /
sample_overlap / schema_shape) and confirmed/rejected by admin
operators.

Folded from three ledger entry kinds (additive per schema-evolution
doctrine Rule 2; KIND_REGISTRY 123 → 126; 24 headroom under the 150-
kind ceiling per Wave F Addendum 4; L-axis family count 15 → 18 of
30 cap per Addendum 4 §E):

* ``entity_stitch_proposed`` → INSERT (or UPDATE evidence on
  re-proposal of the same ``stitch_id`` before resolution)
* ``entity_stitch_confirmed`` → UPDATE state = "confirmed"
* ``entity_stitch_rejected`` → UPDATE state = "rejected"

State transitions are forward-only — every state change is a new
ledger entry; no mutation of prior entries. Replay-stable: a re-fold
over the same ledger stream produces byte-identical projection rows
because the deterministic ``(company_id, stitch_id)`` primary key
collapses re-proposal onto the same row regardless of replay order.

Schema invariants:

* ``stitch_id`` is a deterministic hash of ``(src_source_id_a,
  src_table_a, src_column_a, src_source_id_b, src_table_b,
  src_column_b)`` minted upstream by the L8 inference service with
  the pair ordering canonicalised (lex order); the projection
  treats it as opaque.
* ``state`` ∈ {proposed, confirmed, rejected}. CHECK constraint pins
  the enum on both Postgres and SQLite.
* ``confidence`` is a Float in [0.0, 1.0]; the payload-side validator
  refuses out-of-range writes at ingest, so the column itself stays
  permissive (no CHECK) — the gate is at the ledger entry, not at the
  projection.
* ``entity_kind`` is one of 8 strict ``EntityKind`` Literal values
  {person, organization, transaction, product, event, location,
  session, other}; the column itself is plain String — drift
  prevention is enforced at the payload validator, not at the
  projection.
* ``upstream_semantic_type_id`` is NULL-able — populated when the
  proposing strategy consulted a confirmed semantic type (the L8→L5
  cross-axis chain shared with L6), NULL when the strategy was
  ``name_match`` or ``schema_shape`` without an L5 hit. The
  /lake/entity-stitch surface uses this to render the "view L5
  semantic type →" link only when set.
* ``state_changed_by`` is NULL when ``state == "proposed"`` (system-
  written by the Compounding axis), populated by the operator's
  Person UUID when state transitions to confirmed/rejected.

Backend portability: ``DateTime(timezone=True)`` compiles to
``TIMESTAMPTZ`` on Postgres and ``DATETIME`` on SQLite, matching the
pattern from v014/v015/v016/v021/v022/v023/v024/v025. ``evidence``
is JSON-typed for byte-identical round-trip across both dialects.

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


_TABLE_NAME: str = "projection_entity_stitches"


def _build_table() -> Table:
    """Construct the projection_entity_stitches Table on a fresh
    MetaData.

    Building a fresh MetaData on each call keeps the migration usable
    across multiple test engines without ``InvalidRequestError: Table
    is already defined`` (mirrors the v016/v021/v022/v023/v024/v025
    pattern). Production runs apply once per boot per engine, so the
    fresh MetaData has no runtime cost.

    PK is composite ``(company_id, stitch_id)`` per spec §4.5; the
    pair is unique per tenant so re-proposal of the same logical
    entity-stitch proposal folds onto the same row.
    """
    metadata = MetaData()
    return Table(
        _TABLE_NAME,
        metadata,
        Column("company_id", String, primary_key=True, nullable=False),
        Column("stitch_id", String, primary_key=True, nullable=False),
        Column("src_source_id_a", String, nullable=False),
        Column("src_table_a", String, nullable=False),
        Column("src_column_a", String, nullable=False),
        Column("src_source_id_b", String, nullable=False),
        Column("src_table_b", String, nullable=False),
        Column("src_column_b", String, nullable=False),
        Column("upstream_semantic_type_id", String, nullable=True),
        Column("entity_kind", String, nullable=False),
        Column("confidence", Float, nullable=False),
        Column("strategy", String, nullable=False),
        Column("reasoning", Text, nullable=False),
        Column("evidence", JSON, nullable=False),
        Column("state", String, nullable=False),
        Column("state_changed_at", DateTime(timezone=True), nullable=False),
        Column("state_changed_by", String, nullable=True),
        CheckConstraint(
            "state IN ('proposed', 'confirmed', 'rejected')",
            name="ck_projection_entity_stitches_state",
        ),
        Index(
            "ix_projection_entity_stitches_state",
            "company_id",
            "state",
        ),
        Index(
            "ix_projection_entity_stitches_src_source_id_a",
            "company_id",
            "src_source_id_a",
        ),
        Index(
            "ix_projection_entity_stitches_src_source_id_b",
            "company_id",
            "src_source_id_b",
        ),
        Index(
            "ix_projection_entity_stitches_entity_kind",
            "company_id",
            "entity_kind",
        ),
    )


def _create(sync_conn: Any) -> None:
    """Idempotent CREATE TABLE for projection_entity_stitches.

    Builds a fresh MetaData + Table each call to stay compatible with
    multi-engine test suites. ``checkfirst=True`` short-circuits on
    re-apply so the migration is byte-stable across boots.
    """
    _build_table().create(sync_conn, checkfirst=True)


class Migration:
    version: int = 26
    description: str = (
        "create projection_entity_stitches — L8 lake-side "
        "compounding-loop folded view of cross-source entity-stitch "
        "proposals (proposed/confirmed/rejected); composite PK "
        "(company_id, stitch_id)"
    )

    async def up(self, conn: Any) -> None:
        await conn.run_sync(_create)
