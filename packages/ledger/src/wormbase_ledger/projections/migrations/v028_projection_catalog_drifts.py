"""v028 — create ``projection_catalog_drifts``.

L2 lake-side compounding-loop folded view of catalog-drift detection
proposals from inference strategies (``table_set`` / ``column_set`` /
``column_type``) and acknowledged/rejected by admin operators.

Folded from three ledger entry kinds (additive per schema-evolution
doctrine Rule 2; KIND_REGISTRY 129 → 132; 18 headroom under the 150-
kind ceiling per Wave F Addendum 4; L-axis family count 21 → 24 of
30 cap per Addendum 4 §E — L2 is the FINAL planned axis in this
generation per spec §11):

* ``catalog_drift_proposed`` → INSERT (or UPDATE evidence on
  re-proposal of the same ``drift_id`` before resolution)
* ``catalog_drift_acknowledged`` → UPDATE state = "acknowledged"
* ``catalog_drift_rejected`` → UPDATE state = "rejected"

State transitions are forward-only — every state change is a new
ledger entry; no mutation of prior entries. Replay-stable: a re-fold
over the same ledger stream produces byte-identical projection rows
because the deterministic ``(company_id, drift_id)`` primary key
collapses re-proposal onto the same row regardless of replay order.

Schema invariants:

* ``drift_id`` is a deterministic hash of the identifying tuple
  ``(source_id, table_id, column, drift_kind, before, after)`` minted
  upstream by ``wormbase_ledger.entries.make_drift_id``; the
  projection treats it as opaque.
* ``state`` ∈ {proposed, acknowledged, rejected}. CHECK constraint
  pins the enum on both Postgres and SQLite. (L2 uses
  ``acknowledged`` where L3/L7/L4/L5/L6/L8 use ``confirmed`` and L1
  uses ``promoted`` — semantic distinction per spec §1: L2's
  affirmative state is read-only acknowledgment with no downstream
  pipeline trigger.)
* ``drift_kind`` ∈ {table_added, table_removed, column_added,
  column_removed, column_type_changed}. CHECK constraint pins the
  enum on both backends (unlike L1's free-form ``proposed_kind``,
  the 5 drift cases enumerate observable catalog-metadata change
  classes; new cases require a doctrine review).
* ``column`` is NULL-able — NULL for ``table_added``/``table_removed``
  drifts; required (non-NULL) for ``column_*`` drifts. The payload
  validator enforces consistency at write time; this column itself
  allows NULL so the projection mirrors the payload's range exactly.
* ``before`` and ``after`` are NULL-able — NULL for ``*_added``
  drifts (no prior value) / ``*_removed`` drifts (no current value)
  respectively. For ``column_type_changed`` both must be non-NULL
  (the type values before / after the type change).
* ``confidence`` is a Float in [0.0, 1.0]; the payload-side validator
  refuses out-of-range writes at ingest, so the column itself stays
  permissive (no CHECK) — the gate is at the ledger entry, not at
  the projection.
* ``state_changed_by`` is NULL when ``state == "proposed"`` (system-
  written by the Compounding axis), populated by the operator's
  Person UUID when state transitions to acknowledged/rejected.

Backend portability: ``DateTime(timezone=True)`` compiles to
``TIMESTAMPTZ`` on Postgres and ``DATETIME`` on SQLite, matching the
pattern from v014/v015/v016/v021/v022/v023/v024/v025/v026/v027.
``evidence`` and ``before``/``after`` use JSON-typed columns for
byte-identical round-trip across both dialects.

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


_TABLE_NAME: str = "projection_catalog_drifts"


def _build_table() -> Table:
    """Construct the projection_catalog_drifts Table on a fresh
    MetaData.

    Building a fresh MetaData on each call keeps the migration usable
    across multiple test engines without ``InvalidRequestError: Table
    is already defined`` (mirrors the
    v016/v021/v022/v023/v024/v025/v026/v027 pattern). Production
    runs apply once per boot per engine, so the fresh MetaData has
    no runtime cost.

    PK is composite ``(company_id, drift_id)`` per spec §3.6; the
    pair is unique per tenant so re-proposal of the same logical
    catalog-drift (same strategy proposing the same drift twice)
    folds onto the same row.
    """
    metadata = MetaData()
    return Table(
        _TABLE_NAME,
        metadata,
        Column("company_id", String, primary_key=True, nullable=False),
        Column("drift_id", String, primary_key=True, nullable=False),
        Column("source_id", String, nullable=False),
        Column("table_id", String, nullable=False),
        Column("column", String, nullable=True),
        Column("drift_kind", String, nullable=False),
        Column("before", JSON, nullable=True),
        Column("after", JSON, nullable=True),
        Column("strategy", String, nullable=False),
        Column("reasoning", Text, nullable=False),
        Column("confidence", Float, nullable=False),
        Column("evidence", JSON, nullable=False),
        Column("state", String, nullable=False),
        Column("state_changed_at", DateTime(timezone=True), nullable=False),
        Column("state_changed_by", String, nullable=True),
        CheckConstraint(
            "state IN ('proposed', 'acknowledged', 'rejected')",
            name="ck_projection_catalog_drifts_state",
        ),
        CheckConstraint(
            "drift_kind IN ('table_added', 'table_removed', "
            "'column_added', 'column_removed', 'column_type_changed')",
            name="ck_projection_catalog_drifts_drift_kind",
        ),
        Index(
            "ix_projection_catalog_drifts_state",
            "company_id",
            "state",
        ),
        Index(
            "ix_projection_catalog_drifts_source_id",
            "company_id",
            "source_id",
        ),
        Index(
            "ix_projection_catalog_drifts_drift_kind",
            "company_id",
            "drift_kind",
        ),
        Index(
            "ix_projection_catalog_drifts_table_id",
            "company_id",
            "table_id",
        ),
    )


def _create(sync_conn: Any) -> None:
    """Idempotent CREATE TABLE for projection_catalog_drifts.

    Builds a fresh MetaData + Table each call to stay compatible with
    multi-engine test suites. ``checkfirst=True`` short-circuits on
    re-apply so the migration is byte-stable across boots.
    """
    _build_table().create(sync_conn, checkfirst=True)


class Migration:
    version: int = 28
    description: str = (
        "create projection_catalog_drifts — L2 lake-side "
        "compounding-loop folded view of catalog-drift detection "
        "proposals (proposed/acknowledged/rejected); composite PK "
        "(company_id, drift_id)"
    )

    async def up(self, conn: Any) -> None:
        await conn.run_sync(_create)
