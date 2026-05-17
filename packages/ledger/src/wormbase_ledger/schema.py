"""SQLAlchemy table definitions for the ledger and its projections.

Backend-portable: uses SQLAlchemy's generic types (`Uuid`, `JSON`,
`LargeBinary`) so the same schema works on Postgres (production) and SQLite
(tests/CI). On Postgres these compile to native UUID + JSONB; on SQLite they
fall back to CHAR(32)/JSON-as-TEXT/BLOB respectively.

Logical partitioning by `company_id` (per Wave-2 review resolution): every
table is keyed on `company_id` first, with per-company unique constraints.
Native Postgres declarative partitioning is deferred to v1.1.

Per the review resolution, every ledger entry carries a `quadrant` enum:
    passive_deterministic | passive_probabilistic |
    active_deterministic  | active_probabilistic
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)

metadata = MetaData()

QUADRANT_VALUES = (
    "passive_deterministic",
    "passive_probabilistic",
    "active_deterministic",
    "active_probabilistic",
)

# The append-only ledger. One row per entry. Hash chain is per company_id.
ledger = Table(
    "ledger",
    metadata,
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

projection_sources = Table(
    "projection_sources",
    metadata,
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
    Column("last_seen", DateTime(timezone=True), nullable=True),
)

projection_conversations = Table(
    "projection_conversations",
    metadata,
    Column("company_id", Uuid(as_uuid=True), primary_key=True),
    Column("channel_id", String(128), primary_key=True),
    Column("message_id", String(128), primary_key=True),
    Column("sender_person", Uuid(as_uuid=True), nullable=True),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("text", String, nullable=False),
    Column("classification", String(32), nullable=False),
    Column("domain_id", Uuid(as_uuid=True), nullable=True),
    Column("thread_root_message_id", String(128), nullable=True),
    Column("platform", String(32), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
)

# ---------------------------------------------------------------------------
# Channel-talkativeness projection (chat-worm Wave B, D13).
#
# Per-channel posture is policy-applied state, not constructor config.
# Folded from ``policy_applied`` entries with template
# ``policy:channel_talkativeness``; the daily-interjection columns are
# refreshed by InterjectionBudgetReactivity's observation cycle.
# ---------------------------------------------------------------------------

projection_channels = Table(
    "projection_channels",
    metadata,
    Column("tenant_id", Uuid(as_uuid=True), primary_key=True),
    Column("channel_id", String(128), primary_key=True),
    Column("talkativeness", String(16), nullable=False, default="responsive"),
    Column("daily_interjection_budget", BigInteger, nullable=False, default=3),
    Column("last_set_by", Uuid(as_uuid=True), nullable=True),
    Column("last_set_at", DateTime(timezone=True), nullable=True),
    Column("last_interjection_count", BigInteger, nullable=False, default=0),
    Column("last_interjection_day", String(10), nullable=True),
    Column("last_updated_seq", BigInteger, nullable=False, default=0),
    Index("ix_projection_channels_tenant", "tenant_id"),
)

projection_memory = Table(
    "projection_memory",
    metadata,
    Column("company_id", Uuid(as_uuid=True), primary_key=True),
    Column("memory_id", Uuid(as_uuid=True), primary_key=True),
    Column("content", String, nullable=False),
    Column("tags", JSON, nullable=False),
    Column("written_at", DateTime(timezone=True), nullable=False),
)

projection_kpi_nodes = Table(
    "projection_kpi_nodes",
    metadata,
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

projection_ramp = Table(
    "projection_ramp",
    metadata,
    Column("company_id", Uuid(as_uuid=True), primary_key=True),
    Column("axis", String(32), primary_key=True),
    Column("value", String(8), nullable=False),  # "0".."100" as string for byte stability
    Column("as_of", DateTime(timezone=True), nullable=False),
)

replay_cursor = Table(
    "replay_cursor",
    metadata,
    Column("company_id", Uuid(as_uuid=True), primary_key=True),
    Column("last_seq", BigInteger, nullable=False),
    Column("last_hash", LargeBinary(32), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

# ---------------------------------------------------------------------------
# Identity projections (Block A1 of the production-dashboard PRD).
#
# Three tables back the identity surfaces (/people, /channels, install picker):
#
#   projection_persons               — one row per Person per tenant.
#   projection_person_identities     — multi-platform fan-out for one Person.
#   projection_installs              — one OAuth grant per (tenant, platform).
#
# `tenant_id` is the same value as `ledger.company_id`; we use the dashboard
# vocabulary here because every read path is tenant-scoped.
# ---------------------------------------------------------------------------

projection_persons = Table(
    "projection_persons",
    metadata,
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

projection_person_identities = Table(
    "projection_person_identities",
    metadata,
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

projection_installs = Table(
    "projection_installs",
    metadata,
    Column("install_id", Uuid(as_uuid=True), primary_key=True),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("platform", String(32), nullable=False),
    Column("installer_person_id", Uuid(as_uuid=True), nullable=False),
    Column("oauth_grant_ref", String(512), nullable=False),
    Column("scopes", JSON, nullable=False),
    Column("bot_user_id", String(255), nullable=False),
    Column("status", String(16), nullable=False),
    Column("installed_at", DateTime(timezone=True), nullable=False),
    # Block G of the production-dashboard PRD (§17): connector-first onboarding
    # introduces a wizard-vs-bot fork. Both columns are nullable; the redirect
    # guard treats null as "not chosen yet" and routes to T2 fork.
    Column("setup_mode", String(8), nullable=True),  # "wizard" | "bot" | NULL
    Column("setup_completed_at", DateTime(timezone=True), nullable=True),
    Column("last_updated_seq", BigInteger, nullable=False),
    UniqueConstraint("tenant_id", "platform", name="uq_install_tenant_platform"),
    Index("ix_projection_installs_tenant", "tenant_id"),
)

# ---------------------------------------------------------------------------
# Tenant projection (Phase 1B.A — multi-tenancy v2).
#
# One row per tenant. Folded from ``tenant_signup_initiated`` and
# ``tenant_signup_completed`` entries (kinds registered in 1B.B). Status
# starts at ``pending`` on signup_initiated and transitions to ``active``
# on signup_completed. Suspend / delete tooling lives in Phase 4 polish.
#
# ``demo_visitors`` carries the magic-link round-robin state — list of
# ``{"email", "visited_at"}`` dicts, empty for non-demo tenants. The
# magic-link confirm endpoint reads this column to pick a least-recently-
# visited demo tenant for the requesting evaluator.
# ---------------------------------------------------------------------------

projection_tenants = Table(
    "projection_tenants",
    metadata,
    Column("tenant_id", Uuid(as_uuid=True), primary_key=True),
    Column("slug", String(128), nullable=False),
    Column("display_name", String(256), nullable=False),
    Column("signup_source", String(32), nullable=False),
    Column("signup_email", String(255), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("signup_completed_at", DateTime(timezone=True), nullable=True),
    Column("status", String(16), nullable=False),
    Column("demo_visitors", JSON, nullable=False),
    Column("last_updated_seq", BigInteger, nullable=False),
    UniqueConstraint("slug", name="uq_projection_tenants_slug"),
    Index("ix_projection_tenants_status", "status"),
    Index("ix_projection_tenants_signup_source", "signup_source"),
)

# ---------------------------------------------------------------------------
# Setup-progress (Block G — bot-path conversation cursor).
#
# One row per tenant. ``current_step`` is the YAML step the loop is
# currently waiting on; ``steps_completed`` is the ordered list of steps
# already answered. ``last_advance_seq`` lets the loop resume from where it
# left off after a restart without re-reading the full ledger.
# ---------------------------------------------------------------------------

projection_setup_progress = Table(
    "projection_setup_progress",
    metadata,
    Column("tenant_id", Uuid(as_uuid=True), primary_key=True),
    Column("current_step", String(64), nullable=True),
    Column("steps_completed", JSON, nullable=False),  # list[str]
    Column("last_advance_seq", BigInteger, nullable=True),
    Column("last_advance_ts", DateTime(timezone=True), nullable=True),
)

# ---------------------------------------------------------------------------
# Role projections (Block A2 of the production-dashboard PRD).
#
# A single table covers all three independent role facets. ``facet``
# discriminates {tenancy, domain, resource}; ``scope_id`` + ``scope_type``
# are nullable for the tenancy facet and populated for domain/resource.
# A non-null ``revoked_at`` marks a tombstoned grant; ``grants_for(person_id)``
# (see projections.builder._RoleView helper) returns only the unrevoked rows.
# ---------------------------------------------------------------------------

projection_roles = Table(
    "projection_roles",
    metadata,
    Column("grant_id", Uuid(as_uuid=True), primary_key=True),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("person_id", Uuid(as_uuid=True), nullable=False),
    Column("facet", String(16), nullable=False),  # "tenancy" | "domain" | "resource"
    Column("role", String(32), nullable=False),
    Column("scope_id", Uuid(as_uuid=True), nullable=True),  # domain_id or resource_id
    Column("scope_type", String(32), nullable=True),  # "domain" | "source" | "kpi" | ...
    Column("granted_by", Uuid(as_uuid=True), nullable=False),
    Column("granted_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("last_updated_seq", BigInteger, nullable=False),
    Index("ix_roles_tenant_person", "tenant_id", "person_id"),
    Index("ix_roles_facet", "facet"),
)

# ---------------------------------------------------------------------------
# Data products + notebooks (Block F of the production-dashboard PRD).
#
# Five tables back the data-product / notebook surfaces (PRD §16.3):
#
#   projection_data_products             — one row per artifact (latest version).
#   projection_data_product_runs         — append-only generation history.
#   projection_data_product_consumption  — every read/share/export.
#   projection_notebooks                 — one row per notebook (latest version).
#   projection_notebook_runs             — append-only run history.
# ---------------------------------------------------------------------------

projection_data_products = Table(
    "projection_data_products",
    metadata,
    Column("data_product_id", Uuid(as_uuid=True), primary_key=True),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("name", String(255), nullable=False),
    Column("kind", String(32), nullable=False),  # chart | table | report
    Column("status", String(16), nullable=False),  # proposed | generated | archived
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

projection_data_product_runs = Table(
    "projection_data_product_runs",
    metadata,
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

projection_data_product_consumption = Table(
    "projection_data_product_consumption",
    metadata,
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

projection_notebooks = Table(
    "projection_notebooks",
    metadata,
    Column("notebook_id", Uuid(as_uuid=True), primary_key=True),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("name", String(255), nullable=False),
    Column("kernel", String(32), nullable=False),
    Column("status", String(16), nullable=False),  # proposed | run | published | archived
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

projection_notebook_runs = Table(
    "projection_notebook_runs",
    metadata,
    Column("run_id", Uuid(as_uuid=True), primary_key=True),
    Column("notebook_id", Uuid(as_uuid=True), nullable=False),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("status", String(16), nullable=False),  # ok | error
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("run_by", String(64), nullable=False),
    Column("kernel_state_hash", String(64), nullable=False),
    Column("duration_ms", BigInteger, nullable=False),
    Index("ix_notebook_runs_nb", "notebook_id", "ts"),
    Index("ix_notebook_runs_tenant", "tenant_id"),
)

# ---------------------------------------------------------------------------
# MCP integration (Phase 0 spike).
#
# One row per external MCP tool invocation. Fold of ``emit_mcp_call_received``
# entries on the ledger; mirrors the `query_audit_trail`-shaped surface the
# Phase 1 audit dashboard will read. ``args_hash`` is sha256 hex (privacy:
# raw args never persist). ``outcome`` ∈ {ok, error, denied, timeout}.
# ---------------------------------------------------------------------------

projection_mcp_calls = Table(
    "projection_mcp_calls",
    metadata,
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

# ---------------------------------------------------------------------------
# Topic clusters projection (Phase 2 Task 2B — silver-conversations layer).
#
# One row per topic cluster per tenant. Folded from ``topic_proposed`` ledger
# entries written by ``TopicSynthesisReactivity``. ``cluster_signature`` is
# the canonical normalized text from the recurring.py-style similarity
# clustering; ``label`` is the human-readable label produced by the
# inference router (``call_type="summarize"``) on cluster promotion.
#
# Backs the future /topics dashboard tab (Phase 3 — validation gap P2.3).
# Stable PK (tenant_id, topic_id) lets the projection-fold replay
# idempotently: re-emitting a growing cluster keeps the same topic_id (uuid5
# over cluster_signature) and updates the row in place.
# ---------------------------------------------------------------------------

projection_topics = Table(
    "projection_topics",
    metadata,
    Column("tenant_id", Uuid(as_uuid=True), primary_key=True),
    Column("topic_id", Uuid(as_uuid=True), primary_key=True),
    Column("label", String(256), nullable=False),
    Column("cluster_signature", String(512), nullable=False),
    Column("cluster_size", BigInteger, nullable=False),
    Column("member_message_ids", JSON, nullable=False),  # list[str]
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("confidence", String(8), nullable=False),  # "0.50" stored as str for byte stability
    Column("served_by", String(16), nullable=False),
    Column("last_updated_seq", BigInteger, nullable=False),
    Index("ix_projection_topics_tenant", "tenant_id"),
    Index("ix_projection_topics_last_seen", "tenant_id", "last_seen_at"),
)


# ---------------------------------------------------------------------------
# Catalog-mirror projections (Semantic Layer Wave 1).
#
# Two projection tables folded from ``external_catalog_imported`` and
# ``external_lineage_imported`` PEVR cycles written by the
# ``wormbase-catalog-mirror`` package's CatalogSource implementations
# (``dbt_manifest``, ``snowflake_native``).
#
# These mirror the migration-side declarations in
# ``projections/migrations/v008_external_catalog.py`` (table create) and
# ``projections/migrations/v009_external_lineage.py``; the same shape is
# duplicated here so the canonical ``metadata`` (used by ``metadata.create_all``
# in tests and by the projection builder's INSERT/DELETE paths) sees them
# alongside the rest of the projection tables.
#
# Wave 1 v1 fold semantics:
#   * external_catalog_imported → one row per (source_id, snapshot_hash)
#     snapshot. Latest-wins on re-import for the same (source_id) by virtue
#     of the projection builder generating a deterministic ``id`` from
#     ``(company_id, source_id, snapshot_hash)``.
#   * external_lineage_imported → one row per edge tuple per snapshot
#     import. Edges are keyed on (company_id, source_id, upstream, downstream)
#     for replay idempotency; re-imports with identical edge sets land on
#     the same primary keys and INSERT replays as updates via the builder's
#     tenant-scoped delete+insert pattern.
# ---------------------------------------------------------------------------

projection_external_catalog = Table(
    "projection_external_catalog",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("company_id", Uuid(as_uuid=True), nullable=False),
    Column("source_id", Uuid(as_uuid=True), nullable=False),
    Column("domain_id", Uuid(as_uuid=True), nullable=False),
    Column("source_kind", String, nullable=False),
    Column("snapshot_hash", String, nullable=False),
    Column("table_count", Integer, nullable=False),
    Column("edge_count", Integer, nullable=False),
    Column("metric_count", Integer, nullable=False),
    Column("import_mode", String, nullable=False),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "import_mode IN ('initial', 'refresh')",
        name="ck_external_catalog_import_mode",
    ),
    Index(
        "idx_external_catalog_source",
        "source_id",
        "imported_at",
    ),
    Index(
        "idx_external_catalog_company",
        "company_id",
        "imported_at",
    ),
)


projection_external_lineage = Table(
    "projection_external_lineage",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("company_id", Uuid(as_uuid=True), nullable=False),
    Column("source_id", Uuid(as_uuid=True), nullable=False),
    Column("upstream", String, nullable=False),
    Column("downstream", String, nullable=False),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Index(
        "idx_external_lineage_upstream",
        "company_id",
        "upstream",
    ),
    Index(
        "idx_external_lineage_downstream",
        "company_id",
        "downstream",
    ),
    Index(
        "idx_external_lineage_source",
        "source_id",
        "imported_at",
    ),
)


# ---------------------------------------------------------------------------
# Catalog-mirror policy + metric projections (Semantic Layer Wave 1 → Wave 3
# Task 6 dashboard surface).
#
# Mirrors the migration-defined tables in
# ``projections/migrations/v010_external_policy.py`` and
# ``projections/migrations/v011_external_metric.py`` so a fresh
# ``metadata.create_all`` (tests, in-memory replay) materialises them
# alongside the rest of the projection surface. The catalog-mirror
# CatalogImportReactivity writes one ``external_policy_imported`` PEVR per
# upstream masking / row-access policy and one ``external_metric_imported``
# PEVR per semantic-layer metric definition.
#
# Phase 0 S2 spike: ``projection_external_policy.body`` is intentionally
# NULLABLE. Read-only Snowflake catalog roles typically have SHOW
# privileges on policies but not APPLY, so the policy SQL cannot be
# fetched on read-only credentials. Drift detection on policy existence
# still works without the body. The dashboard MUST surface this as a
# "Body unavailable (insufficient APPLY privilege)" placeholder rather
# than hiding the policy.
#
# Idempotency contract:
#   * ``external_policy_imported`` is keyed at the projection-builder
#     level on ``(company_id, source_id, policy_fqn)`` so a re-import
#     of the same policy fqn upserts in place. The SQL ``UNIQUE`` index
#     on ``(source_id, policy_fqn)`` pins this on disk.
#   * ``external_metric_imported`` is keyed on
#     ``(company_id, source_id, name)`` for the same reason — re-imports
#     upsert; a different ``name`` for the same source is a new row.
# ---------------------------------------------------------------------------

projection_external_policy = Table(
    "projection_external_policy",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("company_id", Uuid(as_uuid=True), nullable=False),
    Column("source_id", Uuid(as_uuid=True), nullable=False),
    Column("policy_fqn", String, nullable=False),
    Column("policy_kind", String, nullable=False),
    # ``body`` MUST stay nullable — S2 spike finding: read-only catalog
    # roles lack APPLY, so the policy SQL is unavailable. Drift on
    # policy existence still works without it.
    Column("body", String, nullable=True),
    Column("applied_to", JSON, nullable=False, default=list),
    Column("imported_at", DateTime(timezone=True), nullable=False),
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


projection_external_metric = Table(
    "projection_external_metric",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("company_id", Uuid(as_uuid=True), nullable=False),
    Column("source_id", Uuid(as_uuid=True), nullable=False),
    Column("name", String, nullable=False),
    Column("expression", String, nullable=True),
    Column("time_grain", String, nullable=True),
    Column("dimensions", JSON, nullable=False, default=list),
    Column("description", String, nullable=True),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Index(
        "uq_external_metric_source_name",
        "source_id",
        "name",
        unique=True,
    ),
    Index(
        "idx_external_metric_company",
        "company_id",
        "imported_at",
    ),
)


# ---------------------------------------------------------------------------
# Agent-query + credential projections (Wave 3 Task 3 — SOC-2-credibility).
#
# Mirrors the migration-defined tables in
# ``projections/migrations/v014_projection_agent_queries.py`` and
# ``projections/migrations/v015_projection_credentials.py`` so a fresh
# ``metadata.create_all`` (tests, in-memory replay) materialises them
# alongside the rest of the projection surface.
#
# Per doctrine Addendum 3:
#   * ``agent_query`` is a SINGLE entry kind with FOUR phases — the four
#     PEVR ledger entries share an ``audit_trail_id`` and the projection
#     folds them into ONE row keyed on that id. ``status`` reflects the
#     latest phase observed (``propose`` → ``execute`` → ``verify`` →
#     ``resolve``); ``denied`` is the terminal state for a gate block.
#   * ``credential`` is a SINGLE entry kind with a ``status`` field
#     {active, revoked}. Covers both data tokens (Snowflake JWT etc.)
#     and model tokens (Anthropic / Kimi / Gemma scoped keys).
# ---------------------------------------------------------------------------

projection_agent_queries = Table(
    "projection_agent_queries",
    metadata,
    Column("id", String, primary_key=True),
    Column("company_id", String, nullable=False),
    Column("agent_id", String, nullable=False),
    Column("mcp_tool", String, nullable=False),
    Column("args", JSON, nullable=False),
    Column("route_mode", String, nullable=False),
    Column("status", String, nullable=False),
    Column("row_count", Integer, nullable=True),
    Column("cost_usd", Numeric(18, 4), nullable=True),
    Column("latency_ms", Integer, nullable=True),
    Column("caused_by", String, nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "route_mode IN ('broker', 'federate')",
        name="ck_projection_agent_queries_route",
    ),
    CheckConstraint(
        "status IN ('propose', 'execute', 'verify', 'resolve', 'denied')",
        name="ck_projection_agent_queries_status",
    ),
    Index("idx_projection_agent_queries_company", "company_id"),
    Index(
        "idx_projection_agent_queries_agent_time",
        "agent_id",
        "started_at",
    ),
)


projection_credentials = Table(
    "projection_credentials",
    metadata,
    Column("id", String, primary_key=True),
    Column("company_id", String, nullable=False),
    Column("agent_id", String, nullable=False),
    Column("credential_kind", String, nullable=False),
    Column("target", String, nullable=False),
    Column("status", String, nullable=False),
    Column("ttl_expires_at", DateTime(timezone=True), nullable=False),
    Column("issued_by", String, nullable=False),
    Column("issued_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "credential_kind IN ('data', 'model')",
        name="ck_projection_credentials_kind",
    ),
    CheckConstraint(
        "status IN ('active', 'revoked')",
        name="ck_projection_credentials_status",
    ),
    Index("idx_projection_credentials_company", "company_id"),
    Index("idx_projection_credentials_agent", "agent_id"),
)


# ---------------------------------------------------------------------------
# Agent identity + grant projections (Semantic Layer Wave 2 Task 1 +
# Wave 3 Task 2).
#
# Mirrors v012_projection_agents.py and v013_projection_agent_grants.py
# so they land on metadata.create_all (tests / in-memory replay) — the
# migration runner stays the source of truth for production schema.
#
# Per doctrine Addendum 3:
#   * One Person row backs each agent (UNIQUE on person_id); status
#     toggles {active, inactive} rather than hard-deleting.
#   * agent_grant is a SINGLE kind with status {active, revoked}; the
#     (agent_id, grant_kind, grant_target) triple keys an upsert so
#     assign + revoke fold into the same row.
#   * budget_remaining_usd is NUMERIC(18,4) and only model.access grants
#     populate it; data grants leave it NULL.
# ---------------------------------------------------------------------------

projection_agents = Table(
    "projection_agents",
    metadata,
    Column("id", String, primary_key=True),
    Column("company_id", String, nullable=False),
    Column("person_id", String, nullable=False, unique=True),
    Column("external_provider", String, nullable=False),
    Column("display_name", String, nullable=False),
    Column("registered_at", DateTime(timezone=True), nullable=False),
    Column("status", String, nullable=False),
    CheckConstraint(
        "external_provider IN ('claude', 'openai', 'kimi', 'internal_worm', 'other')",
        name="ck_projection_agents_external_provider",
    ),
    CheckConstraint(
        "status IN ('active', 'inactive')",
        name="ck_projection_agents_status",
    ),
    Index("idx_projection_agents_company", "company_id"),
)


projection_agent_grants = Table(
    "projection_agent_grants",
    metadata,
    Column("id", String, primary_key=True),
    Column("company_id", String, nullable=False),
    Column("agent_id", String, nullable=False),
    Column("grant_kind", String, nullable=False),
    Column("grant_target", String, nullable=False),
    Column("status", String, nullable=False),
    Column("granted_by", String, nullable=False),
    Column("granted_at", DateTime(timezone=True), nullable=False),
    Column("budget_remaining_usd", Numeric(18, 4), nullable=True),
    UniqueConstraint(
        "agent_id",
        "grant_kind",
        "grant_target",
        name="uq_projection_agent_grants_triple",
    ),
    CheckConstraint(
        "grant_kind IN ('domain.read', 'resource.read', 'resource.maintainer', 'model.access')",
        name="ck_projection_agent_grants_kind",
    ),
    CheckConstraint(
        "status IN ('active', 'revoked')",
        name="ck_projection_agent_grants_status",
    ),
    Index("idx_projection_agent_grants_company", "company_id"),
    Index("idx_projection_agent_grants_agent", "agent_id"),
)


# ---------------------------------------------------------------------------
# §4.5 compounding-loop projections (Semantic Layer Wave 3 Task 4).
#
# Mirrors the migration-defined tables in
# ``projections/migrations/v016_projection_query_outcomes.py`` and
# ``projections/migrations/v017_projection_query_templates.py`` so a fresh
# ``metadata.create_all`` (tests, in-memory replay) materialises them
# alongside the rest of the projection surface. Migrations stay the
# canonical source of truth for production schema; this mirror exists so
# the projection builder can write to both Postgres and SQLite paths
# through SQLAlchemy Core ``insert()``.
#
# v2.B Phase 3b (2026-05-12): the ``embedding`` column IS in the
# mirror now — as JSON for dialect portability. The dialect-divergent
# real shape (``Vector(768)`` on Postgres via pgvector ≥0.6 — resized
# from 1536 by v018, ``JSON`` on SQLite) is owned by the migration
# (v016+v018 for outcomes, v017+v018 for templates).
#
# Embeddings are produced by the §4.5 ``lake.query.record_outcome``
# MCP tool path at write time via :class:`EmbeddingService`. The fold
# preserves them verbatim — no recomputation, no inference call. Replay
# of a recorded ``query_outcome_recorded`` execute entry produces the
# same projection row by construction (embeddings are write-once).
#
# Fold semantics:
#   * ``query_outcome_recorded`` lands as canonical PEVR with
#     ``tool="emit_query_outcome_recorded"`` — one row per recorded
#     outcome, keyed on the execute entry's UUID.
#   * ``query_template_promoted`` is written by the
#     OutcomeToTemplatePromotion Reactivity via a typed-payload PEVR
#     (no ``tool`` wrapping); fold detects by payload shape. One row
#     per promotion, keyed on the propose entry's UUID.
# ---------------------------------------------------------------------------

projection_query_outcomes = Table(
    "projection_query_outcomes",
    metadata,
    Column("id", String, primary_key=True),
    Column("company_id", String, nullable=False),
    Column("agent_query_id", String, nullable=False),
    Column("nl_question", Text, nullable=False),
    Column("final_query_spec", JSON, nullable=False),
    Column("result_summary", JSON, nullable=False),
    Column("used", Boolean, nullable=False),
    Column("useful", Boolean, nullable=False),
    Column("user_correction", Text, nullable=True),
    Column("quality_score", Numeric(6, 4), nullable=False),
    # v2.B Phase 3b: 768-dim embedding. JSON in the mirror for SQLite
    # portability; Postgres production sees Vector(768) via the
    # migration (v016 + v018). Nullable — additive field per Rule 2.
    Column("embedding", JSON, nullable=True),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Index("idx_projection_query_outcomes_company_mirror", "company_id"),
    Index(
        "idx_projection_query_outcomes_agent_query_mirror",
        "agent_query_id",
    ),
)


projection_query_templates = Table(
    "projection_query_templates",
    metadata,
    Column("id", String, primary_key=True),
    Column("company_id", String, nullable=False),
    Column("domain_id", String, nullable=False),
    Column("nl_intent", Text, nullable=False),
    Column("query_spec", JSON, nullable=False),
    Column("promoted_from_outcome_ids", JSON, nullable=False),
    Column("quality_score", Numeric(6, 4), nullable=False),
    Column("hit_count", Integer, nullable=False, default=0),
    Column("promoted_at", DateTime(timezone=True), nullable=False),
    Index("idx_projection_query_templates_company_mirror", "company_id"),
    Index("idx_projection_query_templates_domain_mirror", "domain_id"),
)


# ---------------------------------------------------------------------------
# L3 Sub-wave A — projection_lineage_edges (2026-05-29).
#
# Mirror of the v021 migration so fresh installs (tests, in-memory replay)
# materialise the table through ``metadata.create_all`` alongside the rest
# of the projection surface. The migration stays the canonical source of
# truth for production schema; this mirror exists so the projection
# builder can write to both Postgres and SQLite paths through SQLAlchemy
# Core ``insert()``/``update()``.
#
# Fold semantics live in ``projections/builder.py`` — three kinds map to
# this single row:
#
# * ``lineage_edge_proposed`` → INSERT (or UPDATE evidence on re-proposal)
# * ``lineage_edge_confirmed`` → UPDATE state = "confirmed"
# * ``lineage_edge_rejected`` → UPDATE state = "rejected"
#
# Composite PK (company_id, edge_id) per spec §3.5 — re-proposal of the
# same logical edge folds onto the same row; tenant isolation rides the
# company_id leg.
# ---------------------------------------------------------------------------

projection_lineage_edges = Table(
    "projection_lineage_edges",
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
        name="ck_projection_lineage_edges_state_mirror",
    ),
    Index(
        "ix_projection_lineage_edges_state_mirror",
        "company_id",
        "state",
    ),
    Index(
        "ix_projection_lineage_edges_src_mirror",
        "company_id",
        "src_table_id",
    ),
    Index(
        "ix_projection_lineage_edges_tgt_mirror",
        "company_id",
        "tgt_table_id",
    ),
)


# ---------------------------------------------------------------------------
# L7 Sub-wave A — projection_quality_checks (2026-05-30).
#
# Mirror of the v022 migration so fresh installs (tests, in-memory replay)
# materialise the table through ``metadata.create_all`` alongside the rest
# of the projection surface. The migration stays the canonical source of
# truth for production schema; this mirror exists so the projection
# builder can write to both Postgres and SQLite paths through SQLAlchemy
# Core ``insert()``/``update()``.
#
# Fold semantics live in ``projections/builder.py`` — three kinds map to
# this single row:
#
# * ``quality_check_proposed`` → INSERT (or UPDATE evidence on re-proposal)
# * ``quality_check_confirmed`` → UPDATE state = "confirmed"
# * ``quality_check_rejected`` → UPDATE state = "rejected"
#
# Composite PK (company_id, check_id) per spec §3.6 — re-proposal of the
# same logical check folds onto the same row; tenant isolation rides the
# company_id leg.
# ---------------------------------------------------------------------------

projection_quality_checks = Table(
    "projection_quality_checks",
    metadata,
    Column("company_id", String, primary_key=True, nullable=False),
    Column("check_id", String, primary_key=True, nullable=False),
    Column("table_id", String, nullable=False),
    Column("column", String, nullable=True),
    Column("check_kind", String, nullable=False),
    Column("config", JSON, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("strategy", String, nullable=False),
    Column("reasoning", Text, nullable=False),
    Column("evidence", JSON, nullable=False),
    Column("state", String, nullable=False),
    Column("state_changed_at", DateTime(timezone=True), nullable=False),
    Column("state_changed_by", String, nullable=True),
    CheckConstraint(
        "state IN ('proposed', 'confirmed', 'rejected')",
        name="ck_projection_quality_checks_state_mirror",
    ),
    Index(
        "ix_projection_quality_checks_state_mirror",
        "company_id",
        "state",
    ),
    Index(
        "ix_projection_quality_checks_table_mirror",
        "company_id",
        "table_id",
    ),
    Index(
        "ix_projection_quality_checks_kind_mirror",
        "company_id",
        "check_kind",
    ),
)


# ---------------------------------------------------------------------------
# L4 Sub-wave A — projection_schema_impacts (2026-06-02).
#
# Mirror of the v023 migration so fresh installs (tests, in-memory replay)
# materialise the table through ``metadata.create_all`` alongside the rest
# of the projection surface. The migration stays the canonical source of
# truth for production schema; this mirror exists so the projection
# builder can write to both Postgres and SQLite paths through SQLAlchemy
# Core ``insert()``/``update()``.
#
# Fold semantics live in ``projections/builder.py`` — three kinds map to
# this single row:
#
# * ``schema_impact_proposed`` → INSERT (or UPDATE evidence on re-proposal)
# * ``schema_impact_confirmed`` → UPDATE state = "confirmed"
# * ``schema_impact_rejected`` → UPDATE state = "rejected"
#
# Composite PK (company_id, impact_id) per spec §3.5 — re-proposal of the
# same logical impact folds onto the same row; tenant isolation rides the
# company_id leg. ``upstream_lineage_edge_id`` is nullable (None for
# ``type_coercion`` strategy proposals derived from sample-stats).
# ---------------------------------------------------------------------------

projection_schema_impacts = Table(
    "projection_schema_impacts",
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
        name="ck_projection_schema_impacts_state_mirror",
    ),
    Index(
        "ix_projection_schema_impacts_state_mirror",
        "company_id",
        "state",
    ),
    Index(
        "ix_projection_schema_impacts_source_mirror",
        "company_id",
        "source_id",
    ),
    Index(
        "ix_projection_schema_impacts_tgt_table_mirror",
        "company_id",
        "tgt_table_id",
    ),
    Index(
        "ix_projection_schema_impacts_change_kind_mirror",
        "company_id",
        "change_kind",
    ),
)


# ---------------------------------------------------------------------------
# L5 Sub-wave A — projection_semantic_types (2026-06-05).
#
# Mirror of the v024 migration so fresh installs (tests, in-memory replay)
# materialise the table through ``metadata.create_all`` alongside the rest
# of the projection surface. The migration stays the canonical source of
# truth for production schema; this mirror exists so the projection
# builder can write to both Postgres and SQLite paths through SQLAlchemy
# Core ``insert()``/``update()``.
#
# Fold semantics live in ``projections/builder.py`` — three kinds map to
# this single row:
#
# * ``semantic_type_proposed`` → INSERT (or UPDATE evidence on re-proposal)
# * ``semantic_type_confirmed`` → UPDATE state = "confirmed"
# * ``semantic_type_rejected`` → UPDATE state = "rejected"
#
# Composite PK (company_id, type_id) per spec §3.5 — re-proposal of the
# same logical type proposal folds onto the same row; tenant isolation
# rides the company_id leg. ``semantic_type`` is one of 19 strict Literal
# values per spec §3.2; the column itself is plain String — drift
# prevention is enforced at the payload validator.
# ---------------------------------------------------------------------------

projection_semantic_types = Table(
    "projection_semantic_types",
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
        name="ck_projection_semantic_types_state_mirror",
    ),
    Index(
        "ix_projection_semantic_types_state_mirror",
        "company_id",
        "state",
    ),
    Index(
        "ix_projection_semantic_types_table_id_mirror",
        "company_id",
        "table_id",
    ),
    Index(
        "ix_projection_semantic_types_semantic_type_mirror",
        "company_id",
        "semantic_type",
    ),
)


# ---------------------------------------------------------------------------
# L6 Sub-wave A — projection_column_classifications (2026-06-06).
#
# Mirror of the v025 migration so fresh installs (tests, in-memory replay)
# materialise the table through ``metadata.create_all`` alongside the rest
# of the projection surface. The migration stays the canonical source of
# truth for production schema; this mirror exists so the projection
# builder can write to both Postgres and SQLite paths through SQLAlchemy
# Core ``insert()``/``update()``.
#
# Fold semantics live in ``projections/builder.py`` — three kinds map to
# this single row:
#
# * ``column_classification_proposed`` → INSERT (or UPDATE evidence on
#   re-proposal)
# * ``column_classification_confirmed`` → UPDATE state = "confirmed"
# * ``column_classification_rejected`` → UPDATE state = "rejected"
#
# Composite PK (company_id, classification_id) per spec §4.5 — re-
# proposal of the same logical classification proposal folds onto the
# same row; tenant isolation rides the company_id leg.
# ``classification_level`` is one of 5 strict ``ClassificationLevel``
# Literal values {public, internal, confidential, pii, regulated} per
# spec §4.2; the column itself is plain String — drift prevention is
# enforced at the payload validator. ``upstream_semantic_type_id`` is
# NULL-able — populated when strategy was ``semantic_type`` (the L6→L5
# cross-axis chain), NULL otherwise.
# ---------------------------------------------------------------------------

projection_column_classifications = Table(
    "projection_column_classifications",
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
        name="ck_projection_column_classifications_state_mirror",
    ),
    Index(
        "ix_projection_column_classifications_state_mirror",
        "company_id",
        "state",
    ),
    Index(
        "ix_projection_column_classifications_table_id_mirror",
        "company_id",
        "table_id",
    ),
    Index(
        "ix_projection_column_classifications_level_mirror",
        "company_id",
        "classification_level",
    ),
)


# ---------------------------------------------------------------------------
# L8 Sub-wave A — projection_entity_stitches (2026-06-07).
#
# Mirror of the v026 migration so fresh installs (tests, in-memory replay)
# materialise the table through ``metadata.create_all`` alongside the rest
# of the projection surface. The migration stays the canonical source of
# truth for production schema; this mirror exists so the projection
# builder can write to both Postgres and SQLite paths through SQLAlchemy
# Core ``insert()``/``update()``.
#
# Fold semantics live in ``projections/builder.py`` — three kinds map to
# this single row:
#
# * ``entity_stitch_proposed`` → INSERT (or UPDATE evidence on
#   re-proposal)
# * ``entity_stitch_confirmed`` → UPDATE state = "confirmed"
# * ``entity_stitch_rejected`` → UPDATE state = "rejected"
#
# Composite PK (company_id, stitch_id) per spec §4.5 — re-proposal of
# the same logical stitch proposal folds onto the same row; tenant
# isolation rides the company_id leg. ``entity_kind`` is one of 8
# strict ``EntityKind`` Literal values {person, organization,
# transaction, product, event, location, session, other} per spec §4.2;
# the column itself is plain String — drift prevention is enforced at
# the payload validator. ``upstream_semantic_type_id`` is NULL-able —
# populated when a strategy consulted a confirmed L5 semantic type
# (the L8→L5 cross-axis chain shared with L6), NULL otherwise.
# ---------------------------------------------------------------------------

projection_entity_stitches = Table(
    "projection_entity_stitches",
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
        name="ck_projection_entity_stitches_state_mirror",
    ),
    Index(
        "ix_projection_entity_stitches_state_mirror",
        "company_id",
        "state",
    ),
    Index(
        "ix_projection_entity_stitches_src_a_mirror",
        "company_id",
        "src_source_id_a",
    ),
    Index(
        "ix_projection_entity_stitches_src_b_mirror",
        "company_id",
        "src_source_id_b",
    ),
    Index(
        "ix_projection_entity_stitches_entity_kind_mirror",
        "company_id",
        "entity_kind",
    ),
)


# ---------------------------------------------------------------------------
# L1 Sub-wave A — projection_source_candidates (2026-06-08).
#
# Mirror of the v027 migration so fresh installs (tests, in-memory replay)
# materialise the table through ``metadata.create_all`` alongside the rest
# of the projection surface. The migration stays the canonical source of
# truth for production schema; this mirror exists so the projection
# builder can write to both Postgres and SQLite paths through SQLAlchemy
# Core ``insert()``/``update()``.
#
# Fold semantics live in ``projections/builder.py`` — three kinds map to
# this single row:
#
# * ``source_candidate_proposed`` → INSERT (or UPDATE evidence on
#   re-proposal)
# * ``source_candidate_promoted`` → UPDATE state = "promoted"
# * ``source_candidate_rejected`` → UPDATE state = "rejected"
#
# Composite PK (company_id, candidate_id) per spec §4.5 — re-proposal of
# the same logical source-candidate proposal (same strategy proposing the
# same source twice) folds onto the same row; tenant isolation rides the
# company_id leg. ``proposed_kind`` is a connector-registry string; the
# column itself is plain String — drift prevention is enforced at the
# payload validator via a runtime check against
# ``wormbase_connectors.registry.default_registry()``.
# ``downstream_source_proposed_id`` is NULL-able — populated when a
# promote action threads back the entry-id of the downstream
# ``source_proposed`` it triggered (NOT a peer-L-axis cross-axis link;
# points downstream into the source-pipeline lifecycle).
# ---------------------------------------------------------------------------

projection_source_candidates = Table(
    "projection_source_candidates",
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
        name="ck_projection_source_candidates_state_mirror",
    ),
    Index(
        "ix_projection_source_candidates_state_mirror",
        "company_id",
        "state",
    ),
    Index(
        "ix_projection_source_candidates_strategy_mirror",
        "company_id",
        "strategy",
    ),
    Index(
        "ix_projection_source_candidates_proposed_kind_mirror",
        "company_id",
        "proposed_kind",
    ),
    Index(
        "ix_projection_source_candidates_domain_id_hint_mirror",
        "company_id",
        "domain_id_hint",
    ),
)


# ---------------------------------------------------------------------------
# L2 Sub-wave A — projection_catalog_drifts (2026-06-09).
#
# Mirror of the v028 migration so fresh installs (tests, in-memory replay)
# materialise the table through ``metadata.create_all`` alongside the rest
# of the projection surface. The migration stays the canonical source of
# truth for production schema; this mirror exists so the projection
# builder can write to both Postgres and SQLite paths through SQLAlchemy
# Core ``insert()``/``update()``.
#
# Fold semantics live in ``projections/builder.py`` — three kinds map to
# this single row:
#
# * ``catalog_drift_proposed`` → INSERT (or UPDATE evidence on
#   re-proposal)
# * ``catalog_drift_acknowledged`` → UPDATE state = "acknowledged"
# * ``catalog_drift_rejected`` → UPDATE state = "rejected"
#
# Composite PK (company_id, drift_id) per spec §3.6 — re-proposal of
# the same logical catalog-drift (same strategy detecting the same
# drift twice) folds onto the same row; tenant isolation rides the
# company_id leg. ``drift_kind`` is pinned to the 5-value Literal via
# a CHECK constraint (unlike L1's free-form ``proposed_kind``).
# ``column`` is NULL-able — NULL for ``table_*`` drifts, required for
# ``column_*`` drifts (the payload validator enforces the nullability
# rules at write time). ``before``/``after`` are NULL-able JSON for
# the same reason (NULL for ``*_added`` / ``*_removed`` respectively).
# ---------------------------------------------------------------------------

projection_catalog_drifts = Table(
    "projection_catalog_drifts",
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
        name="ck_projection_catalog_drifts_state_mirror",
    ),
    CheckConstraint(
        "drift_kind IN ('table_added', 'table_removed', "
        "'column_added', 'column_removed', 'column_type_changed')",
        name="ck_projection_catalog_drifts_drift_kind_mirror",
    ),
    Index(
        "ix_projection_catalog_drifts_state_mirror",
        "company_id",
        "state",
    ),
    Index(
        "ix_projection_catalog_drifts_source_id_mirror",
        "company_id",
        "source_id",
    ),
    Index(
        "ix_projection_catalog_drifts_drift_kind_mirror",
        "company_id",
        "drift_kind",
    ),
    Index(
        "ix_projection_catalog_drifts_table_id_mirror",
        "company_id",
        "table_id",
    ),
)


# ---------------------------------------------------------------------------
# Catalog-mirror Wave 2 Sub-wave A — projection_catalog_tables (2026-06-09
# follow-on).
#
# Mirror of the v029 migration so fresh installs (tests, in-memory replay)
# materialise the table through ``metadata.create_all`` alongside the rest
# of the projection surface. The migration stays the canonical source of
# truth for production schema; this mirror exists so the projection
# builder can write to both Postgres and SQLite paths through SQLAlchemy
# Core ``insert()``/``update()``.
#
# Wave 2 substrate: today's ``ExternalCatalogImportedPayload`` carries
# only counts + hashes — no per-table column structure. This blocks
# productivity gates on L2 TableSet + L8 SchemaShape strategies (see the
# Sub-wave A spec note). ``projection_catalog_tables`` is the folded
# view of the new ``catalog_table_imported`` ledger kind: one row per
# (source, table, snapshot) triple, ``columns`` carrying the list of
# ``{name, type}`` dicts.
#
# Composite PK (company_id, source_id, table_id, snapshot_hash) — same
# logical (source, table) across multiple snapshots produces multiple
# rows because each snapshot is a point-in-time. L2 TableSet needs to
# fetch tables from BOTH current AND baseline snapshots; that requires
# both snapshots' rows to coexist. Tenant isolation rides the
# company_id leg as elsewhere.
# ---------------------------------------------------------------------------

projection_catalog_tables = Table(
    "projection_catalog_tables",
    metadata,
    Column("company_id", String, primary_key=True, nullable=False),
    Column("source_id", String, primary_key=True, nullable=False),
    Column("table_id", String, primary_key=True, nullable=False),
    Column("snapshot_hash", String, primary_key=True, nullable=False),
    Column("columns", JSON, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Index(
        "ix_catalog_tables_source_mirror",
        "company_id",
        "source_id",
    ),
    Index(
        "ix_catalog_tables_snapshot_mirror",
        "company_id",
        "snapshot_hash",
    ),
)

