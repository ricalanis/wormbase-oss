"""Initial ledger schema (ledger + 4 projection tables + replay_cursor).

Revision ID: 20260422_0001
Revises:
Create Date: 2026-04-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260422_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ledger",
        sa.Column("entry_id", sa.Uuid(), primary_key=True),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("quadrant", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("prev_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("hash", sa.LargeBinary(32), nullable=False),
        sa.UniqueConstraint("company_id", "seq", name="uq_ledger_company_seq"),
        sa.UniqueConstraint("company_id", "hash", name="uq_ledger_company_hash"),
    )
    op.create_index("ix_ledger_company_ts", "ledger", ["company_id", "ts"])
    op.create_index("ix_ledger_company_kind", "ledger", ["company_id", "kind"])
    op.create_index("ix_ledger_company_quadrant", "ledger", ["company_id", "quadrant"])

    op.create_table(
        "projection_sources",
        sa.Column("company_id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.Uuid(), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("uri", sa.String(1024), nullable=False),
        sa.Column("domain_id", sa.Uuid(), nullable=True),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("added_by_person", sa.Uuid(), nullable=True),
        sa.Column("added_via_flow", sa.String(64), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_entry_hash", sa.LargeBinary(32), nullable=False),
    )

    op.create_table(
        "projection_memory",
        sa.Column("company_id", sa.Uuid(), primary_key=True),
        sa.Column("memory_id", sa.Uuid(), primary_key=True),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("written_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "projection_kpi_nodes",
        sa.Column("company_id", sa.Uuid(), primary_key=True),
        sa.Column("node_id", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("domain_id", sa.Uuid(), nullable=True),
        sa.Column("owner_person_id", sa.Uuid(), nullable=True),
        sa.Column("parent_node_id", sa.String(128), nullable=True),
        sa.Column("source_resource_id", sa.Uuid(), nullable=True),
        sa.Column("metric_type", sa.String(64), nullable=False),
        sa.Column("confidence", sa.String(16), nullable=False),
    )

    op.create_table(
        "projection_ramp",
        sa.Column("company_id", sa.Uuid(), primary_key=True),
        sa.Column("axis", sa.String(32), primary_key=True),
        sa.Column("value", sa.String(8), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "replay_cursor",
        sa.Column("company_id", sa.Uuid(), primary_key=True),
        sa.Column("last_seq", sa.BigInteger(), nullable=False),
        sa.Column("last_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("replay_cursor")
    op.drop_table("projection_ramp")
    op.drop_table("projection_kpi_nodes")
    op.drop_table("projection_memory")
    op.drop_table("projection_sources")
    op.drop_index("ix_ledger_company_quadrant", table_name="ledger")
    op.drop_index("ix_ledger_company_kind", table_name="ledger")
    op.drop_index("ix_ledger_company_ts", table_name="ledger")
    op.drop_table("ledger")
