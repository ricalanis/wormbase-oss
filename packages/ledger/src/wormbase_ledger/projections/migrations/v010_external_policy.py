"""v010 — create ``projection_external_policy``.

One row per upstream masking / row-access policy, folded from
``external_policy_imported`` ledger entries.

Phase 0 spike finding (S2): ``body`` is intentionally NULLABLE.
Snowflake catalog roles typically have SHOW privileges on policies
but not APPLY, so the policy body cannot be fetched on read-only
catalog credentials. Drift detection on policy existence still works
even when the body is inaccessible. The pydantic payload mirrors
this (``body: str | None``) — any NOT NULL constraint here would
break the catalog-mirror Reactivity on read-only roles.

``applied_to`` stores the list of column / table references the
policy is attached to upstream. Stored as ``JSON`` rather than a
native ``TEXT[]`` so the projection is byte-identical across Postgres
(production) and SQLite (tests) — the same pattern v001 uses for
``projection_memory.tags`` and ``projection_topics.member_message_ids``.
The pydantic payload's ``applied_to: tuple[str, ...]`` round-trips
through JSON list shape losslessly.

Ported from ``packages/ledger/migrations/v007_external_policy.sql``
(Wave 1 Task 4 raw-SQL form) to match the canonical Python migration
runner at ``wormbase_ledger.projections.migrate``. Renumbered from
v007 -> v010 to extend the existing monotonic v001-v007 sequence
without collision.

Idempotency: ``CREATE TABLE IF NOT EXISTS`` semantics via SQLAlchemy's
``checkfirst=True`` on ``Table.create``.
"""
from __future__ import annotations

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    MetaData,
    String,
    Table,
    Uuid,
    func,
)


_metadata = MetaData()

projection_external_policy = Table(
    "projection_external_policy",
    _metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("company_id", Uuid(as_uuid=True), nullable=False),
    Column("source_id", Uuid(as_uuid=True), nullable=False),
    Column("policy_fqn", String, nullable=False),
    Column("policy_kind", String, nullable=False),
    # ``body`` MUST stay nullable — S2 spike finding: read-only catalog
    # roles lack APPLY, so the policy SQL is unavailable. Drift on
    # policy existence still works without it.
    Column("body", String, nullable=True),
    Column(
        "applied_to",
        JSON,
        nullable=False,
        default=list,
    ),
    Column(
        "imported_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint(
        "policy_kind IN ('masking', 'row_access')",
        name="ck_external_policy_kind",
    ),
    Index(
        "uq_external_policy_source_fqn",
        "source_id",
        "policy_fqn",
        unique=True,
    ),
    Index(
        "idx_external_policy_company",
        "company_id",
        "imported_at",
    ),
)


def _create(conn) -> None:  # type: ignore[no-untyped-def]
    projection_external_policy.create(conn, checkfirst=True)


class Migration:
    version: int = 10
    description: str = (
        "create projection_external_policy for masking / row-access policies"
    )

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.run_sync(_create)
