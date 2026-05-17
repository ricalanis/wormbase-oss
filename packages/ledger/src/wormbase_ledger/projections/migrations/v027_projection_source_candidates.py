"""v027 — create ``projection_source_candidates``.

L1 lake-side compounding-loop folded view of source-candidate triage
proposals from inference strategies (``kpi_gap`` / ``channel_mention``
/ ``complementarity``) and promoted/rejected by admin operators.

Folded from three ledger entry kinds (additive per schema-evolution
doctrine Rule 2; KIND_REGISTRY 126 → 129; 21 headroom under the 150-
kind ceiling per Wave F Addendum 4; L-axis family count 18 → 21 of
30 cap per Addendum 4 §E):

* ``source_candidate_proposed`` → INSERT (or UPDATE evidence on
  re-proposal of the same ``candidate_id`` before resolution)
* ``source_candidate_promoted`` → UPDATE state = "promoted"
* ``source_candidate_rejected`` → UPDATE state = "rejected"

State transitions are forward-only — every state change is a new
ledger entry; no mutation of prior entries. Replay-stable: a re-fold
over the same ledger stream produces byte-identical projection rows
because the deterministic ``(company_id, candidate_id)`` primary key
collapses re-proposal onto the same row regardless of replay order.

Schema invariants:

* ``candidate_id`` is a deterministic hash of ``(proposed_kind,
  proposed_identifier, strategy)`` minted upstream by
  ``wormbase_ledger.entries.make_candidate_id``; the projection
  treats it as opaque.
* ``state`` ∈ {proposed, promoted, rejected}. CHECK constraint pins
  the enum on both Postgres and SQLite. (L1 uses "promoted" where
  L3/L7/L4/L5/L6/L8 use "confirmed" — see spec §1 for rationale on
  the prequel-triage naming.)
* ``confidence`` is a Float in [0.0, 1.0]; the payload-side validator
  refuses out-of-range writes at ingest, so the column itself stays
  permissive (no CHECK) — the gate is at the ledger entry, not at the
  projection.
* ``proposed_kind`` is a free-form connector-registry string (e.g.
  ``"csv_local"``, ``"postgres"``, ``"stripe"``, ``"mcp:notion"``);
  the column itself is plain String. Drift prevention is enforced
  at the payload validator via a runtime check against
  ``wormbase_lake_surfaces.registry.default_registry()`` per spec §4.2
  (NOT a Literal — connector kinds are configuration, not
  KIND_REGISTRY entries; Addendum 4 §B).
* ``domain_id_hint`` is NULL-able — populated when the proposing
  strategy has domain signal (e.g. kpi_gap threads the gap's owning
  domain through), NULL otherwise.
* ``downstream_source_proposed_id`` is NULL-able — populated when a
  promote action threads back the entry-id of the downstream
  ``source_proposed`` it triggered. The /lake/source-candidates
  surface renders a "view connected source →" link when this is set.
  Note: this is NOT a peer-L-axis cross-axis link in the L4→L3 /
  L6→L5 / L8→L5 sense; it points downstream into the existing
  source-pipeline lifecycle (cross-axis chain count stays at 3 per
  spec §4.6).
* ``state_changed_by`` is NULL when ``state == "proposed"`` (system-
  written by the Compounding axis), populated by the operator's
  Person UUID when state transitions to promoted/rejected.

Backend portability: ``DateTime(timezone=True)`` compiles to
``TIMESTAMPTZ`` on Postgres and ``DATETIME`` on SQLite, matching the
pattern from v014/v015/v016/v021/v022/v023/v024/v025/v026.
``evidence`` is JSON-typed for byte-identical round-trip across both
dialects.

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


_TABLE_NAME: str = "projection_source_candidates"


def _build_table() -> Table:
    """Construct the projection_source_candidates Table on a fresh
    MetaData.

    Building a fresh MetaData on each call keeps the migration usable
    across multiple test engines without ``InvalidRequestError: Table
    is already defined`` (mirrors the v016/v021/v022/v023/v024/v025/v026
    pattern). Production runs apply once per boot per engine, so the
    fresh MetaData has no runtime cost.

    PK is composite ``(company_id, candidate_id)`` per spec §4.5; the
    pair is unique per tenant so re-proposal of the same logical
    source-candidate (same strategy proposing the same source twice)
    folds onto the same row.
    """
    metadata = MetaData()
    return Table(
        _TABLE_NAME,
        metadata,
        Column("company_id", String, primary_key=True, nullable=False),
        Column("candidate_id", String, primary_key=True, nullable=False),
        Column("proposed_kind", String, nullable=False),
        Column("proposed_identifier", String, nullable=False),
        Column("domain_id_hint", String, nullable=True),
        Column("strategy", String, nullable=False),
        Column("reasoning", Text, nullable=False),
        Column("confidence", Float, nullable=False),
        Column("evidence", JSON, nullable=False),
        Column("downstream_source_proposed_id", String, nullable=True),
        Column("state", String, nullable=False),
        Column("state_changed_at", DateTime(timezone=True), nullable=False),
        Column("state_changed_by", String, nullable=True),
        CheckConstraint(
            "state IN ('proposed', 'promoted', 'rejected')",
            name="ck_projection_source_candidates_state",
        ),
        Index(
            "ix_projection_source_candidates_state",
            "company_id",
            "state",
        ),
        Index(
            "ix_projection_source_candidates_strategy",
            "company_id",
            "strategy",
        ),
        Index(
            "ix_projection_source_candidates_proposed_kind",
            "company_id",
            "proposed_kind",
        ),
        Index(
            "ix_projection_source_candidates_domain_id_hint",
            "company_id",
            "domain_id_hint",
        ),
    )


def _create(sync_conn: Any) -> None:
    """Idempotent CREATE TABLE for projection_source_candidates.

    Builds a fresh MetaData + Table each call to stay compatible with
    multi-engine test suites. ``checkfirst=True`` short-circuits on
    re-apply so the migration is byte-stable across boots.
    """
    _build_table().create(sync_conn, checkfirst=True)


class Migration:
    version: int = 27
    description: str = (
        "create projection_source_candidates — L1 lake-side "
        "compounding-loop folded view of source-candidate triage "
        "proposals (proposed/promoted/rejected); composite PK "
        "(company_id, candidate_id)"
    )

    async def up(self, conn: Any) -> None:
        await conn.run_sync(_create)
