"""v001 — initial baseline schema.

Snapshots the projection-table surface as it stood before the
migration runner existed. Idempotent: every CREATE TABLE uses IF
NOT EXISTS semantics via SQLAlchemy's ``metadata.create_all``, so
running this migration against a database that already has the
tables is a no-op.

Why this is a snapshot rather than a delta
------------------------------------------
v001 captures the v1 surface explicitly so future readers can
trace schema evolution by reading migration files in order.
``schema.py`` is the *current* truth; the migrations are the
*history* of how we got here.

This migration deliberately omits the columns added by v002
(``projection_installs.setup_mode``, ``projection_installs.setup_completed_at``).
That keeps the migration sequence honest:

- on a brand-new DB: v001 creates the v1 shape, v002 adds the new columns
- on a DB that ``metadata.create_all`` already populated with the v002
  columns: v001's CREATE TABLE IF NOT EXISTS is a no-op, v002's
  presence-checked ADD COLUMN is a no-op — same final state, no drift

Backend portability
-------------------
Uses SQLAlchemy generic types so the same code path runs on
Postgres (production) and SQLite (tests). On Postgres these
compile to native UUID + JSONB; on SQLite they fall back to
CHAR(32) / JSON-as-TEXT / BLOB.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Index,
    LargeBinary,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    Uuid,
)

# Local MetaData so v001's CREATE TABLE IF NOT EXISTS is bounded to
# the v1 surface. We do NOT import from ``schema.py`` — schema.py
# is the live mirror of the latest version, and importing it here
# would couple v001 to whatever shape ``schema.py`` happens to have
# at any given moment. The migration must capture v1 explicitly.
_v1_metadata = MetaData()


# --- Ledger + replay-cursor (unchanged through v001/v002) ----------

Table(
    "ledger",
    _v1_metadata,
    Column("entry_id", Uuid(as_uuid=True), primary_key=True),
    Column("company_id", Uuid(as_uuid=True), nullable=False),
    Column("seq", BigInteger, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("kind", String(64), nullable=False),
    Column("quadrant", String(32), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("prev_hash", LargeBinary(32), nullable=False),
    Column("hash", LargeBinary(32), nullable=False),
    UniqueConstraint("company_id", "seq", name="uq_ledger_company_seq"),
    UniqueConstraint("company_id", "hash", name="uq_ledger_company_hash"),
    Index("ix_ledger_company_ts", "company_id", "ts"),
    Index("ix_ledger_company_kind", "company_id", "kind"),
    Index("ix_ledger_company_quadrant", "company_id", "quadrant"),
)

Table(
    "replay_cursor",
    _v1_metadata,
    Column("company_id", Uuid(as_uuid=True), primary_key=True),
    Column("last_seq", BigInteger, nullable=False),
    Column("last_hash", LargeBinary(32), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


# --- Projections that ship in v001 -------------------------------

Table(
    "projection_sources",
    _v1_metadata,
    Column("company_id", Uuid(as_uuid=True), primary_key=True),
    Column("source_id", Uuid(as_uuid=True), primary_key=True),
    Column("status", String(32), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("uri", String(1024), nullable=False),
    Column("domain_id", Uuid(as_uuid=True), nullable=True),
    Column("classification", String(32), nullable=False),
    Column("added_by_person", Uuid(as_uuid=True), nullable=True),
    Column("added_via_flow", String(64), nullable=False),
    Column("added_at", DateTime(timezone=True), nullable=False),
    Column("last_entry_hash", LargeBinary(32), nullable=False),
)

Table(
    "projection_memory",
    _v1_metadata,
    Column("company_id", Uuid(as_uuid=True), primary_key=True),
    Column("memory_id", Uuid(as_uuid=True), primary_key=True),
    Column("content", String, nullable=False),
    Column("tags", JSON, nullable=False),
    Column("written_at", DateTime(timezone=True), nullable=False),
)

Table(
    "projection_kpi_nodes",
    _v1_metadata,
    Column("company_id", Uuid(as_uuid=True), primary_key=True),
    Column("node_id", String(128), primary_key=True),
    Column("name", String(256), nullable=False),
    Column("domain_id", Uuid(as_uuid=True), nullable=True),
    Column("owner_person_id", Uuid(as_uuid=True), nullable=True),
    Column("parent_node_id", String(128), nullable=True),
    Column("source_resource_id", Uuid(as_uuid=True), nullable=True),
    Column("metric_type", String(64), nullable=False),
    Column("confidence", String(16), nullable=False),
)

Table(
    "projection_ramp",
    _v1_metadata,
    Column("company_id", Uuid(as_uuid=True), primary_key=True),
    Column("axis", String(32), primary_key=True),
    Column("value", String(8), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
)

Table(
    "projection_persons",
    _v1_metadata,
    Column("person_id", Uuid(as_uuid=True), primary_key=True),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("name", String(255), nullable=False),
    Column("email", String(255), nullable=True),
    Column("position", String(64), nullable=True),
    Column("status", String(16), nullable=False),
    Column("proposed_by", String(64), nullable=True),
    Column("confirmed_by", Uuid(as_uuid=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_updated_seq", BigInteger, nullable=False),
    Index("ix_projection_persons_tenant", "tenant_id"),
    Index("ix_projection_persons_email", "email"),
)

Table(
    "projection_person_identities",
    _v1_metadata,
    Column("identity_id", Uuid(as_uuid=True), primary_key=True),
    Column("person_id", Uuid(as_uuid=True), nullable=False),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("platform", String(32), nullable=False),
    Column("platform_user_id", String(255), nullable=False),
    Column("display_name", String(255), nullable=True),
    Column("email_at_platform", String(255), nullable=True),
    Column("avatar_url", String(512), nullable=True),
    Column("added_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "platform",
        "platform_user_id",
        name="uq_identity_tenant_platform_user",
    ),
    Index("ix_projection_person_identities_person", "person_id"),
    Index("ix_projection_person_identities_tenant", "tenant_id"),
)

# v001 baseline: projection_installs WITHOUT the setup_mode /
# setup_completed_at columns. v002 adds those.
Table(
    "projection_installs",
    _v1_metadata,
    Column("install_id", Uuid(as_uuid=True), primary_key=True),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("platform", String(32), nullable=False),
    Column("installer_person_id", Uuid(as_uuid=True), nullable=False),
    Column("oauth_grant_ref", String(512), nullable=False),
    Column("scopes", JSON, nullable=False),
    Column("bot_user_id", String(255), nullable=False),
    Column("status", String(16), nullable=False),
    Column("installed_at", DateTime(timezone=True), nullable=False),
    Column("last_updated_seq", BigInteger, nullable=False),
    UniqueConstraint("tenant_id", "platform", name="uq_install_tenant_platform"),
    Index("ix_projection_installs_tenant", "tenant_id"),
)

Table(
    "projection_setup_progress",
    _v1_metadata,
    Column("tenant_id", Uuid(as_uuid=True), primary_key=True),
    Column("current_step", String(64), nullable=True),
    Column("steps_completed", JSON, nullable=False),
    Column("last_advance_seq", BigInteger, nullable=True),
    Column("last_advance_ts", DateTime(timezone=True), nullable=True),
)

Table(
    "projection_roles",
    _v1_metadata,
    Column("grant_id", Uuid(as_uuid=True), primary_key=True),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("person_id", Uuid(as_uuid=True), nullable=False),
    Column("facet", String(16), nullable=False),
    Column("role", String(32), nullable=False),
    Column("scope_id", Uuid(as_uuid=True), nullable=True),
    Column("scope_type", String(32), nullable=True),
    Column("granted_by", Uuid(as_uuid=True), nullable=False),
    Column("granted_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("last_updated_seq", BigInteger, nullable=False),
    Index("ix_roles_tenant_person", "tenant_id", "person_id"),
    Index("ix_roles_facet", "facet"),
)

Table(
    "projection_data_products",
    _v1_metadata,
    Column("data_product_id", Uuid(as_uuid=True), primary_key=True),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("name", String(255), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("status", String(16), nullable=False),
    Column("requested_by_person_id", Uuid(as_uuid=True), nullable=False),
    Column("domain_id", Uuid(as_uuid=True), nullable=True),
    Column("latest_run_seq", BigInteger, nullable=True),
    Column("generated_at", DateTime(timezone=True), nullable=True),
    Column("content_hash", String(64), nullable=True),
    Column("contents_uri", String(1024), nullable=True),
    Column("last_updated_seq", BigInteger, nullable=False),
    Index("ix_data_products_tenant", "tenant_id"),
    Index("ix_data_products_requested_by", "tenant_id", "requested_by_person_id"),
    Index("ix_data_products_domain", "tenant_id", "domain_id"),
)

Table(
    "projection_data_product_runs",
    _v1_metadata,
    Column("run_id", Uuid(as_uuid=True), primary_key=True),
    Column("data_product_id", Uuid(as_uuid=True), nullable=False),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("generated_by", String(64), nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("source_hashes", JSON, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("duration_ms", BigInteger, nullable=False),
    Index("ix_data_product_runs_dp", "data_product_id", "ts"),
    Index("ix_data_product_runs_tenant", "tenant_id"),
)

Table(
    "projection_data_product_consumption",
    _v1_metadata,
    Column("consumption_id", Uuid(as_uuid=True), primary_key=True),
    Column("data_product_id", Uuid(as_uuid=True), nullable=False),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("person_id", Uuid(as_uuid=True), nullable=False),
    Column("surface", String(16), nullable=False),
    Column("channel", String(255), nullable=True),
    Column("ts", DateTime(timezone=True), nullable=False),
    Index("ix_consumption_dp", "data_product_id", "ts"),
    Index("ix_consumption_tenant_person", "tenant_id", "person_id"),
)

Table(
    "projection_notebooks",
    _v1_metadata,
    Column("notebook_id", Uuid(as_uuid=True), primary_key=True),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("name", String(255), nullable=False),
    Column("kernel", String(32), nullable=False),
    Column("status", String(16), nullable=False),
    Column("owner_person_id", Uuid(as_uuid=True), nullable=True),
    Column("domain_id", Uuid(as_uuid=True), nullable=True),
    Column("latest_run_id", Uuid(as_uuid=True), nullable=True),
    Column("latest_published_run_id", Uuid(as_uuid=True), nullable=True),
    Column("version", String(32), nullable=True),
    Column("last_updated_seq", BigInteger, nullable=False),
    Index("ix_notebooks_tenant", "tenant_id"),
    Index("ix_notebooks_owner", "tenant_id", "owner_person_id"),
    Index("ix_notebooks_domain", "tenant_id", "domain_id"),
)

Table(
    "projection_notebook_runs",
    _v1_metadata,
    Column("run_id", Uuid(as_uuid=True), primary_key=True),
    Column("notebook_id", Uuid(as_uuid=True), nullable=False),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("status", String(16), nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("run_by", String(64), nullable=False),
    Column("kernel_state_hash", String(64), nullable=False),
    Column("duration_ms", BigInteger, nullable=False),
    Index("ix_notebook_runs_nb", "notebook_id", "ts"),
    Index("ix_notebook_runs_tenant", "tenant_id"),
)

Table(
    "projection_mcp_calls",
    _v1_metadata,
    Column("mcp_call_id", Uuid(as_uuid=True), primary_key=True),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("caller_person_id", Uuid(as_uuid=True), nullable=True),
    Column("tool_name", String(64), nullable=False),
    Column("args_hash", String(64), nullable=False),
    Column("client_ua", String(255), nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("outcome", String(16), nullable=False),
    Column("latency_ms", BigInteger, nullable=False),
    Index("ix_mcp_calls_tenant", "tenant_id"),
    Index("ix_mcp_calls_tenant_tool", "tenant_id", "tool_name"),
    Index("ix_mcp_calls_started_at", "tenant_id", "started_at"),
)


class Migration:
    """v001 — create the v1 baseline projection schema.

    Idempotent: ``metadata.create_all`` only creates tables that
    don't exist; existing tables (and their existing columns) are
    left untouched.
    """

    version: int = 1
    description: str = "initial baseline projection schema"

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.run_sync(_v1_metadata.create_all)
