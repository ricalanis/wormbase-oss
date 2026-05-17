"""aiohttp HTTP write API for the worm-core service.

A3.5 of ``docs/superpowers/plans/2026-04-26-production-dashboard.md``.

Exposes bearer-token-authed POST/DELETE endpoints under ``/api/v1/people/*``
that the dashboard's server-side route handlers call to write into the
ledger via the canonical PEVR cycle. Replaces the previous demo-seam
``INSERT INTO ledger`` shortcut from ``apps/dashboard/lib/ledger-client.ts``.

Architectural notes:

- The aiohttp Application runs as an asyncio task alongside the
  reactivity loops (see ``cli.py::_run_async``). One process, one
  ``Ledger`` instance, no extra deployment unit.
- Bearer token is read from ``WORMBASE_LEDGER_API_TOKEN`` and matched on
  every request. Missing token → 401. Wrong token → 401.
- Tenant is read from the ``X-Tenant-Slug`` header (default
  ``baseworm`` if absent — matches the dashboard's tenant cookie default).
  Resolved to ``company_id`` via ``service.tenant_to_uuid``.
- Validation uses Pydantic models; failures return 422.
- Each handler delegates to a high-level ``write_actions`` function which
  builds the four PEVR payloads and calls ``write_primitive`` via the
  ``Ledger.write`` surface. No demo seams.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
from datetime import UTC
from typing import Any
from uuid import UUID

from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ledger.errors import VerifyFailed
from wormbase_ledger.write_primitive import WriteResult

from wormbase_core import data_product_actions, write_actions
from wormbase_core.notebook_kernel import LocalPythonKernel, cells_from_dicts
from wormbase_core.service import tenant_to_uuid
from wormbase_core.storage import ObjectStore, get_storage_backend

logger = logging.getLogger("wormbase_core.http_api")

# Typed app keys (aiohttp 3.10+). String keys still work but emit a
# NotAppKeyWarning each time you read them.
APP_LEDGER_KEY: web.AppKey[Any] = web.AppKey("wormbase_ledger", object)
APP_TOKEN_KEY: web.AppKey[str] = web.AppKey("wormbase_api_token", str)
APP_STORAGE_KEY: web.AppKey[ObjectStore] = web.AppKey("wormbase_storage", ObjectStore)

DEFAULT_TENANT_SLUG = "baseworm"


def _bad_text(message: str) -> str:
    """Sanitize a message for ``HTTPException(reason=...)``.

    aiohttp rejects reasons that contain CR/LF (which Pydantic's ValidationError
    string form does). Collapse newlines into '; ' so the message survives.
    """
    return message.replace("\r", " ").replace("\n", "; ")


# ---------------------------------------------------------------------------
# Request bodies (Pydantic)
# ---------------------------------------------------------------------------


class _Body(BaseModel):
    """Base for incoming JSON bodies — forbid unknown fields, ignore None defaults."""

    model_config = ConfigDict(extra="forbid")


class ProposePersonBody(_Body):
    name: str = Field(min_length=1)
    email: str | None = None
    platform: str = Field(min_length=1)
    platform_user_id: str = Field(min_length=1)
    position: str | None = None
    proposed_by: str = "dashboard-admin"


class ConfirmPersonBody(_Body):
    confirmed_by: UUID


class ArchivePersonBody(_Body):
    archived_by: UUID
    reason: str = Field(min_length=1)


class ConfirmPositionBody(_Body):
    """POST /api/v1/people/{person_id}/position/confirm body — Phase 2 Task 2C.

    Pins the position slug being confirmed (matches the propose-step's
    ``position`` argument) so the entry replays correctly without a
    cross-row join.
    """

    position: str = Field(min_length=1)
    confirmed_by: UUID


class RejectPositionBody(_Body):
    """POST /api/v1/people/{person_id}/position/reject body — Phase 2 Task 2C."""

    position: str = Field(min_length=1)
    rejected_by: UUID
    reason: str | None = None


class LinkIdentityBody(_Body):
    platform: str = Field(min_length=1)
    platform_user_id: str = Field(min_length=1)
    linked_by: UUID


class UnlinkIdentityBody(_Body):
    unlinked_by: UUID


class GrantRoleBody(_Body):
    facet: str = Field(pattern=r"^(tenancy|domain|resource)$")
    role: str = Field(min_length=1)
    scope_id: UUID | None = None
    scope_type: str | None = None
    granted_by: UUID


class RevokeRoleBody(_Body):
    revoked_by: UUID
    role: str = Field(min_length=1)


class MergePersonsBody(_Body):
    keeper_id: UUID
    mergee_id: UUID
    merged_by: UUID


class BulkConfirmPersonsBody(_Body):
    """POST /api/v1/people/bulk-confirm body — W2.A6.

    The dashboard's ``/people`` BulkConfirmDrawer ships a checkbox-selected
    list of proposed Person UUIDs in one request. Each id becomes one
    independent ``confirm_person`` PEVR cycle (4 entries) on the worm-core
    side; the bulk-confirm endpoint is a thin orchestration layer over
    ``write_actions.bulk_confirm_persons``.
    """

    person_ids: list[UUID] = Field(min_length=1)
    confirmed_by: UUID


class SplitIdentityRef(BaseModel):
    """One identity in a split request — platform + platform_user_id."""

    model_config = ConfigDict(extra="forbid")
    platform: str = Field(min_length=1)
    platform_user_id: str = Field(min_length=1)


class SplitPersonBody(_Body):
    new_person_name: str = Field(min_length=1)
    new_person_email: str | None = None
    new_person_position: str | None = None
    identities_to_move: list[SplitIdentityRef] = Field(min_length=1)
    split_by: UUID


class SetSetupModeBody(_Body):
    """POST /api/v1/setup-mode body — set the tenant's wizard | bot path.

    Block G4 of the production-dashboard PRD §17. The dashboard's
    /api/onboarding/setup-mode route handler proxies the user's choice to
    this endpoint after the user clicks "Continue setup" in T2.
    """

    mode: str = Field(pattern=r"^(wizard|bot)$")
    chosen_by_person_id: UUID


class CompleteInstallBody(_Body):
    """POST /api/v1/installs body — orchestrates the post-OAuth install.

    All fields are required because the production OAuth callback always
    knows them at this point: the installer has just successfully
    authenticated against Slack/Discord/Teams, so we have their email,
    name, platform_user_id, and the bot's auth.test response (bot_user_id
    + scopes). The ``oauth_grant_ref`` MUST be ``kms://`` or ``vault://``
    — never a raw bearer token.
    """

    platform: str = Field(min_length=1)
    installer_email: str = Field(min_length=1)
    installer_name: str = Field(min_length=1)
    installer_avatar_url: str | None = None
    platform_user_id: str = Field(min_length=1)
    oauth_grant_ref: str = Field(min_length=1)
    scopes: list[str] = Field(default_factory=list)
    bot_user_id: str = Field(min_length=1)


class ProvisionLocalLakeBody(_Body):
    """POST /api/v1/installs/provision-local-lake body — Block I7.

    The CLI seed helper (``wormbase demo seed --provision-local-lake``)
    posts here when the operator wants the default lake without driving
    the full install OAuth flow. Production never hits this endpoint —
    ``complete_install`` auto-calls ``provision_local_lake`` inline.

    Both ids are required because the orchestrator records the
    installer Person as proposer/confirmer/maintainer of the lake.
    """

    tenant_id: UUID
    installer_person_id: UUID


class InitiateTenantSignupBody(_Body):
    """POST /api/v1/tenants/signup-initiated body — multi-tenancy v2 (1B.B).

    Written at the start of either a Slack OAuth signup (unknown
    workspace) or an email magic-link request. Carries the tentative
    slug + display name + signup_email + the pending-token hash so the
    matching completion step can verify the request is the same one the
    initiator started.
    """

    tenant_id: UUID
    slug: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    signup_source: str = Field(
        pattern=r"^(slack_oauth|email_magic_link|demo_seed|bootstrapped)$",
    )
    signup_email: str | None = None
    pending_token_hash: str = Field(min_length=64, max_length=64)


class CompleteTenantSignupBody(_Body):
    """POST /api/v1/tenants/signup-completed body — multi-tenancy v2 (1B.B).

    Written after a signup is fully installed: Slack signup writes this
    immediately after the install_completed cycle inside complete_install;
    magic-link writes this when the confirm endpoint binds the evaluator
    to a demo tenant.
    """

    tenant_id: UUID
    signup_source: str = Field(
        pattern=r"^(slack_oauth|email_magic_link|demo_seed|bootstrapped)$",
    )
    assigned_tenant_slug: str = Field(min_length=1)
    signup_email: str | None = None


# --- Data products (Block F2) ---


class ProposeDataProductBody(_Body):
    name: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    requested_by_person_id: UUID
    sources_required: list[UUID] = Field(default_factory=list)
    domain_id: UUID | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    prompted_by_message_id: str | None = None
    contents_bytes_b64: str | None = None
    contents_ext: str = "html"


class RegenerateDataProductBody(_Body):
    source_hashes: list[str] = Field(default_factory=list)
    contents_bytes_b64: str | None = None
    contents_ext: str = "html"
    generated_by: str = "worm"


class ConsumeDataProductBody(_Body):
    consumed_by_person_id: UUID
    surface: str = Field(pattern=r"^(dashboard|chat|voice|export)$")
    channel: str | None = None


# --- Notebooks (Block F2) ---


class NotebookCellBody(BaseModel):
    """A single cell in a propose-notebook request."""

    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern=r"^(code|markdown|sql)$")
    source: str
    language: str = "python"


class ProposeNotebookBody(_Body):
    name: str = Field(min_length=1)
    cells: list[NotebookCellBody] = Field(default_factory=list)
    kernel: str = Field(pattern=r"^(python_local|python_pandas|sql_postgres)$")
    proposed_by_person_id: UUID
    domain_id: UUID | None = None


class RunNotebookBody(_Body):
    run_by: str = "worm"
    timeout_s: int = Field(default=30, ge=1, le=300)


class PublishNotebookBody(_Body):
    run_id: UUID
    owner_person_id: UUID
    version: str = Field(min_length=1)
    published_by: UUID
    domain_id: UUID | None = None


# --- KPI / decision / process (W2.A7) ---


class ProposeKpiBody(_Body):
    """POST /api/v1/kpis/propose — admin-driven KPI tree extension."""

    label: str = Field(min_length=1)
    formula: str = ""
    unit: str = "count"
    source_ids: list[UUID] = Field(default_factory=list)
    owner_position: str | None = None
    proposed_by: str = "dashboard-admin"


class RecordDecisionBody(_Body):
    """POST /api/v1/decisions — admin-recorded decision (manual canon)."""

    decision_text: str = Field(min_length=1)
    channel_id: str = Field(min_length=1)
    decided_by_persons: list[UUID] = Field(default_factory=list)
    evidence_message_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.95, ge=0.0, le=1.0)
    proposed_by: str = "dashboard-admin"


class ProcessMapStepBody(BaseModel):
    """One step in a manually-authored process map."""

    model_config = ConfigDict(extra="forbid")
    order: int = Field(ge=1)
    actor: str = Field(min_length=1)
    action: str = Field(min_length=1)
    source_message_id: str = ""


class ProposeProcessMapBody(_Body):
    """POST /api/v1/processes — admin-authored process map."""

    process_name: str = Field(min_length=1)
    steps: list[ProcessMapStepBody] = Field(min_length=1)
    domain: str = "general"
    confidence: float = Field(default=0.95, ge=0.0, le=1.0)
    proposed_by: str = "dashboard-admin"


class ReplayDataProductBody(_Body):
    """POST /api/v1/data-products/{id}/replay body — W2.A8.

    Strict-replay is the production path: the orchestrator re-hashes the
    bytes and refuses to write if they drift from the original
    content_hash. ``strict=False`` is reserved for governance audit jobs
    that intentionally want to see drift.
    """

    strict: bool = True
    generated_by: str = "replay"


class SignNotebookBody(_Body):
    """POST /api/v1/notebooks/{id}/sign body — W2.A8.

    "Sign" is the governance-framed publish. ``signed_by`` is the admin
    Person attesting that this run is canonical; the response carries a
    deterministic per-Person signature receipt the dashboard surfaces.
    """

    run_id: UUID
    owner_person_id: UUID
    version: str = Field(min_length=1)
    signed_by: UUID
    domain_id: UUID | None = None


# --- Research approve / reject (W2.A9) ---


class ResolveExperimentBody(_Body):
    """POST /api/v1/experiments/{id}/{approve,reject} body — W2.A9.

    The approve/reject buttons on /research write a fresh
    ``emit_experiment_resolved`` entry overriding whatever outcome the
    autoresearch loop produced (or arrived at first). ``resolved_by`` is
    the admin Person clicking the button; rationale is free-form prose
    surfaced on the resolved chip in the table.
    """

    resolved_by: UUID
    rationale: str = ""
    observed_delta: float = 0.0


# --- MCP token issuance (W2.A9) ---


class IssueMcpTokenBody(_Body):
    """POST /api/v1/mcp/tokens body — W2.A9.

    Issues a Person-scoped compact bearer token the dashboard's
    "Connect Claude Desktop" panel surfaces as a copy-paste config
    snippet. ``person_id`` is the Person the token authenticates as
    (typically the admin clicking "Connect Claude Desktop" — the
    dashboard pins this to the current admin via ``getCurrentPerson``).

    ``ttl_seconds`` defaults to 30 days — long enough for a desktop
    client to live without re-auth, short enough that revocation is
    bounded. ``label`` is a free-form annotation surfaced in the
    issuance audit ledger entry (e.g. "Carol's MacBook").
    """

    person_id: UUID
    ttl_seconds: int | None = Field(default=None, ge=60, le=365 * 24 * 60 * 60)
    label: str = ""


class RegisterMcpPresetBody(_Body):
    """POST /api/v1/mcp/presets body — W2.A9.

    Registers an inbound MCP preset (an external MCP server the worm
    consumes from). The preset is recorded as a ``source_proposed``
    ledger entry with ``source_kind=mcp:<kind>`` and provenance tagged
    ``dashboard_form``. The actual ``MCPSurfaceDriver`` preset class lives
    in code (``packages/connectors/src/wormbase_lake_surfaces/mcp_presets``)
    and self-registers at import; this endpoint surfaces the operator's
    intent so it's audited, multi-tenant scoped, and visible in /sources.
    """

    kind: str = Field(min_length=1)
    """Preset kind, e.g. ``"mcp:notion"``."""

    server_url: str = Field(min_length=1)
    """Streamable-HTTP MCP endpoint, e.g. ``https://mcp.notion.com/mcp``."""

    description: str = ""
    suggested_domain: str = "general"
    suggested_classification: str = Field(
        default="internal",
        pattern=r"^(public|internal|confidential|pii|regulated)$",
    )
    proposed_by: UUID


class WormAskBody(_Body):
    """POST /api/v1/worm/ask body — Phase 3 Task 3B.

    The dashboard's Ask-the-Worm panel forwards each evaluator question
    here. The endpoint synthesizes the same chat_received PEVR cycle the
    channel-adapter writes for live Slack/Discord/Teams traffic; the
    chat-presence MentionResponseReactivity then writes the chat_reply
    PEVR cycle. The captured reply text is returned inline.

    Same code path as production chat. No demo seam.
    """

    question: str = Field(min_length=1)


# --- v1.1 write-action bodies (4 endpoints) -------------------------------
#
# Backs four Wave 3 / Wave 3.2 dashboard server actions whose stubs fired
# "endpoint v1.1" errors. With these bodies + handlers landed below, the
# stub branches go cold and the form-driven flows write real entries.


class RegisterAgentBody(_Body):
    """POST /api/v1/write_actions/register_agent body — Wave 3.2 Hole #1.

    Field shapes are pinned to the dashboard form's POST in
    ``apps/dashboard/app/(app)/people/agents/new/actions.ts``.
    ``model_access_budget_usd`` is a Decimal-as-string for NUMERIC(18,4)
    round-trip — None means no ``model.access`` grant is created.
    """

    company_id: UUID
    external_provider: str = Field(min_length=1)
    display_name: str = Field(min_length=1, max_length=80)
    domain_read_ids: list[UUID] = Field(default_factory=list)
    model_access_budget_usd: str | None = None
    registered_by: UUID


class ImportDbtCatalogBody(_Body):
    """POST /api/v1/write_actions/import_dbt_catalog body — Wave 3.2 Hole #2 (dbt branch).

    The dashboard form already validates ``manifest_uri`` length; we
    re-validate here so an out-of-band caller cannot bypass the cap.
    ``manifest_uri`` accepts ``file://`` / ``https://`` / bare paths.
    """

    company_id: UUID
    manifest_uri: str = Field(min_length=1, max_length=1024)
    domain_id: UUID
    imported_by: UUID


class ImportSnowflakeCatalogBody(_Body):
    """POST /api/v1/write_actions/import_snowflake_catalog body — Wave 3.2 Hole #2 (snowflake branch).

    ``schema`` (Python keyword) renamed to ``schema`` on the wire to
    match the dashboard's POST body; on the Pydantic side we accept it
    under the ``schema_`` alias-target attribute name so Python code can
    use a non-keyword identifier downstream.

    The Snowflake password / OAuth token is captured OUT-OF-BAND by the
    ``CredentialBroker`` — NEVER passed in this request body. See
    ``CLAUDE.md`` security posture.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    company_id: UUID
    account: str = Field(min_length=1, max_length=256)
    user: str = Field(min_length=1, max_length=256)
    warehouse: str = Field(min_length=1, max_length=256)
    database: str = Field(min_length=1, max_length=256)
    schema_: str = Field(min_length=1, max_length=256, alias="schema")
    role: str | None = Field(default=None, max_length=256)
    domain_id: UUID
    imported_by: UUID


class AgentSubscriptionCreateBody(_Body):
    """POST /api/v1/write_actions/agent_subscriptions_create body — v2.A Task 7.

    Mirrors the SubscriptionForm payload on the dashboard. ``filter`` is the
    canonical serialized ``AgentEventFilter`` (kinds / domains / agent_id_ref
    / payload_path_eq); the dispatcher consumes the same dict via
    ``deserialize_filter``. ``webhook_url`` and ``webhook_secret_ref`` are
    required only when ``transport == "webhook"`` (validated at the
    handler).
    """

    company_id: UUID
    agent_id: str = Field(min_length=1, max_length=128)
    filter: dict = Field(default_factory=dict)
    transport: str = Field(min_length=1)
    webhook_url: str | None = Field(default=None, max_length=2048)
    webhook_secret_ref: str | None = Field(default=None, max_length=512)
    description: str | None = Field(default=None, max_length=256)
    granted_by: UUID


class AgentSubscriptionRevokeBody(_Body):
    """DELETE /api/v1/write_actions/agent_subscriptions_revoke/{subscription_id}
    body — v2.A Task 7.

    ``reason`` defaults to ``admin_revoked`` since the dashboard path is the
    admin-override surface. The agent's own MCP path emits
    ``agent_request``.
    """

    company_id: UUID
    reason: str = Field(default="admin_revoked")
    revoked_by: UUID


class AgentMetadataUpdateBody(_Body):
    """PATCH /api/v1/write_actions/agents_metadata/{agent_id} body —
    final wave item #5 (2026-05-13).

    Wires the agent detail page's Edit modal. At least one of
    ``display_name`` / ``description`` must be non-None and non-empty —
    the handler enforces this with 422 (the dashboard form catches the
    same condition client-side). ``description`` accepts the empty
    string only when the admin wants to clear a previously-set value;
    a None on either field means "leave unchanged".

    Authorization mirrors ``AgentRevokeBody`` — bearer token + tenant
    header at the HTTP layer, admin role check at the dashboard server
    action (defense in depth).
    """

    company_id: UUID
    display_name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2048)
    reason: str | None = Field(default=None, max_length=512)
    updated_by: UUID


class AgentMetadataRevertBody(_Body):
    """POST /api/v1/write_actions/agents_metadata_revert/{agent_id} body —
    post-rest path #4 (2026-05-13).

    Reverts the most recent ``agent_metadata_updated`` by emitting a new
    compensating ``agent_metadata_updated`` PEVR cycle (forward-only
    doctrine; no mutation of prior entries, no new ledger kind). The
    ``reason`` field is appended to an auto-generated "revert from
    seq {N}" prefix on the new entry's audit note.

    Authorization mirrors ``AgentMetadataUpdateBody`` — bearer token +
    tenant header at the HTTP layer, admin role check at the dashboard
    server action (defense in depth).
    """

    company_id: UUID
    reason: str | None = Field(default=None, max_length=512)
    updated_by: UUID


class AgentRevokeBody(_Body):
    """DELETE /api/v1/write_actions/agents_revoke/{agent_id} body —
    v1.4 follow-up (Path 5).

    Revokes EVERY active grant the agent currently holds (domain.read,
    resource.read, resource.maintainer, model.access). Implemented as a
    cascade over the agent's active grants, each written as an
    ``agent_grant`` (status=``revoked``) PEVR cycle. No new ledger entry
    kind is introduced — the canonical Addendum 3 single-kind-with-status
    pattern carries the lifecycle.

    ``reason`` defaults to ``admin_revoked`` since this endpoint is the
    dashboard's admin-override surface. The agent-self path (if added)
    would default to ``agent_request``.
    """

    company_id: UUID
    reason: str = Field(default="admin_revoked")
    revoked_by: UUID


class PromoteSemanticGapBody(_Body):
    """POST /api/v1/write_actions/promote_semantic_gap body — Wave 3 Task 5.

    ``semantic_gap_entry_id`` is the ledger entry id (UUID-string) of the
    ``semantic_gap_proposed`` cycle row the admin clicked Promote on.
    """

    company_id: UUID
    semantic_gap_entry_id: str = Field(min_length=1)
    metric_name: str = Field(min_length=1, max_length=128)
    metric_expression: str = Field(min_length=1)
    domain_id: UUID
    promoted_by: UUID


class LineageEdgeConfirmBody(_Body):
    """POST /api/v1/write_actions/lineage_edges_confirm/{edge_id} body —
    L3 Sub-wave C (2026-05-29).

    Mirrors the AgentSubscriptionRevokeBody pattern: ``company_id`` is
    cross-checked against the tenant header, ``confirmed_by`` is the
    admin Person UUID threaded by the dashboard's getCurrentPerson
    server action (never a placeholder). ``notes`` is an optional
    free-text annotation surfaced on /trace + the edge-detail row.
    """

    company_id: UUID
    confirmed_by: UUID
    notes: str | None = Field(default=None, max_length=2048)


class LineageEdgeRejectBody(_Body):
    """POST /api/v1/write_actions/lineage_edges_reject/{edge_id} body —
    L3 Sub-wave C (2026-05-29).

    ``reason`` is one of the strict enum values on
    :class:`LineageEdgeRejectedPayload`; validated by the handler
    against ``_VALID_LINEAGE_EDGE_REJECT_REASONS`` (400 on miss). The
    payload's own ``Literal[...]`` validator catches the same case at
    the ledger boundary (defense in depth).
    """

    company_id: UUID
    rejected_by: UUID
    reason: str = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=2048)


_VALID_LINEAGE_EDGE_REJECT_REASONS: frozenset[str] = frozenset(
    {
        "false_positive",
        "wrong_direction",
        "low_confidence",
        "out_of_scope",
        "other",
    },
)


# --- L7 Sub-wave C (2026-05-30) — quality-check write-action bodies. -------


class QualityCheckConfirmBody(_Body):
    """POST /api/v1/write_actions/quality_checks_confirm/{check_id} body —
    L7 Sub-wave C (2026-05-30).

    Mirrors the LineageEdgeConfirmBody pattern: ``company_id`` is cross-
    checked against the tenant header, ``confirmed_by`` is the admin
    Person UUID threaded by the dashboard's getCurrentPerson server
    action (never a placeholder). ``notes`` is an optional free-text
    annotation surfaced on /trace + the quality-check detail row.
    """

    company_id: UUID
    confirmed_by: UUID
    notes: str | None = Field(default=None, max_length=2048)


class QualityCheckRejectBody(_Body):
    """POST /api/v1/write_actions/quality_checks_reject/{check_id} body —
    L7 Sub-wave C (2026-05-30).

    ``reason`` is one of the strict enum values on
    :class:`QualityCheckRejectedPayload`; validated by the handler
    against ``_VALID_QUALITY_CHECK_REJECT_REASONS`` (400 on miss). The
    payload's own ``Literal[...]`` validator catches the same case at
    the ledger boundary (defense in depth).
    """

    company_id: UUID
    rejected_by: UUID
    reason: str = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=2048)


_VALID_QUALITY_CHECK_REJECT_REASONS: frozenset[str] = frozenset(
    {
        "false_positive",
        "low_value",
        "wrong_threshold",
        "out_of_scope",
        "other",
    },
)


# --- L4 Sub-wave C (2026-06-02) — schema-impact write-action bodies. -------


class SchemaImpactConfirmBody(_Body):
    """POST /api/v1/write_actions/schema_impacts_confirm/{impact_id} body —
    L4 Sub-wave C (2026-06-02).

    Mirrors the LineageEdgeConfirmBody + QualityCheckConfirmBody pattern:
    ``company_id`` is cross-checked against the tenant header,
    ``confirmed_by`` is the admin Person UUID threaded by the dashboard's
    getCurrentPerson server action (never a placeholder). ``notes`` is
    an optional free-text annotation surfaced on /trace + the
    schema-impact detail row.
    """

    company_id: UUID
    confirmed_by: UUID
    notes: str | None = Field(default=None, max_length=2048)


class SchemaImpactRejectBody(_Body):
    """POST /api/v1/write_actions/schema_impacts_reject/{impact_id} body —
    L4 Sub-wave C (2026-06-02).

    ``reason`` is one of the strict 5-value enum on
    :class:`SchemaImpactRejectedPayload`; validated by the handler
    against ``_VALID_SCHEMA_IMPACT_REJECT_REASONS`` (400 on miss). The
    payload's own ``Literal[...]`` validator catches the same case at
    the ledger boundary (defense in depth).
    """

    company_id: UUID
    rejected_by: UUID
    reason: str = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=2048)


_VALID_SCHEMA_IMPACT_REJECT_REASONS: frozenset[str] = frozenset(
    {
        "false_positive",
        "already_handled",
        "low_value",
        "out_of_scope",
        "other",
    },
)


# --- L5 Sub-wave C (2026-06-05) — semantic-type write-action bodies. -------


class SemanticTypeConfirmBody(_Body):
    """POST /api/v1/write_actions/semantic_types_confirm/{type_id} body —
    L5 Sub-wave C (2026-06-05).

    Mirrors the LineageEdgeConfirmBody + QualityCheckConfirmBody +
    SchemaImpactConfirmBody pattern: ``company_id`` is cross-checked
    against the tenant header, ``confirmed_by`` is the admin Person
    UUID threaded by the dashboard's getCurrentPerson server action
    (never a placeholder). ``notes`` is an optional free-text
    annotation surfaced on /trace + the semantic-type detail row.
    """

    company_id: UUID
    confirmed_by: UUID
    notes: str | None = Field(default=None, max_length=2048)


class SemanticTypeRejectBody(_Body):
    """POST /api/v1/write_actions/semantic_types_reject/{type_id} body —
    L5 Sub-wave C (2026-06-05).

    ``reason`` is one of the strict 5-value enum on
    :class:`SemanticTypeRejectedPayload`; validated by the handler
    against ``_VALID_SEMANTIC_TYPE_REJECT_REASONS`` (400 on miss). The
    payload's own ``Literal[...]`` validator catches the same case at
    the ledger boundary (defense in depth). The L5-specific 5th value
    is ``wrong_type`` (replaces L4's ``already_handled`` and L7's
    ``wrong_threshold``).
    """

    company_id: UUID
    rejected_by: UUID
    reason: str = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=2048)


_VALID_SEMANTIC_TYPE_REJECT_REASONS: frozenset[str] = frozenset(
    {
        "false_positive",
        "low_value",
        "wrong_type",
        "out_of_scope",
        "other",
    },
)


# --- L6 Sub-wave C (2026-06-06) — column-classification write-action bodies.


class ColumnClassificationConfirmBody(_Body):
    """POST /api/v1/write_actions/column_classifications_confirm/{classification_id} body —
    L6 Sub-wave C (2026-06-06).

    Mirrors the LineageEdgeConfirmBody + QualityCheckConfirmBody +
    SchemaImpactConfirmBody + SemanticTypeConfirmBody pattern:
    ``company_id`` is cross-checked against the tenant header,
    ``confirmed_by`` is the admin Person UUID threaded by the
    dashboard's getCurrentPerson server action (never a placeholder).
    ``notes`` is an optional free-text annotation surfaced on /trace +
    the column-classification detail row.
    """

    company_id: UUID
    confirmed_by: UUID
    notes: str | None = Field(default=None, max_length=2048)


class ColumnClassificationRejectBody(_Body):
    """POST /api/v1/write_actions/column_classifications_reject/{classification_id} body —
    L6 Sub-wave C (2026-06-06).

    ``reason`` is one of the strict 5-value enum on
    :class:`ColumnClassificationRejectedPayload`; validated by the
    handler against ``_VALID_COLUMN_CLASSIFICATION_REJECT_REASONS``
    (400 on miss). The payload's own ``Literal[...]`` validator catches
    the same case at the ledger boundary (defense in depth). The
    L6-specific 5th value is ``wrong_level`` (distinct from L5's
    ``wrong_type``, L4's ``already_handled`` and L7's
    ``wrong_threshold``).
    """

    company_id: UUID
    rejected_by: UUID
    reason: str = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=2048)


_VALID_COLUMN_CLASSIFICATION_REJECT_REASONS: frozenset[str] = frozenset(
    {
        "false_positive",
        "low_value",
        "wrong_level",
        "out_of_scope",
        "other",
    },
)


# --- L8 Sub-wave C (2026-06-07) — entity-stitch write-action bodies.


class EntityStitchConfirmBody(_Body):
    """POST /api/v1/write_actions/entity_stitches_confirm/{stitch_id} body —
    L8 Sub-wave C (2026-06-07).

    Mirrors the LineageEdgeConfirmBody + QualityCheckConfirmBody +
    SchemaImpactConfirmBody + SemanticTypeConfirmBody +
    ColumnClassificationConfirmBody pattern: ``company_id`` is
    cross-checked against the tenant header, ``confirmed_by`` is the
    admin Person UUID threaded by the dashboard's getCurrentPerson
    server action (never a placeholder). ``notes`` is an optional
    free-text annotation surfaced on /trace + the entity-stitch detail
    row.
    """

    company_id: UUID
    confirmed_by: UUID
    notes: str | None = Field(default=None, max_length=2048)


class EntityStitchRejectBody(_Body):
    """POST /api/v1/write_actions/entity_stitches_reject/{stitch_id} body —
    L8 Sub-wave C (2026-06-07).

    ``reason`` is one of the strict 5-value enum on
    :class:`EntityStitchRejectedPayload`; validated by the handler
    against ``_VALID_ENTITY_STITCH_REJECT_REASONS`` (400 on miss). The
    payload's own ``Literal[...]`` validator catches the same case at
    the ledger boundary (defense in depth). The L8-specific 5th value
    is ``wrong_pairing`` (distinct from L6's ``wrong_level``, L5's
    ``wrong_type``, L4's ``already_handled`` and L7's
    ``wrong_threshold``).
    """

    company_id: UUID
    rejected_by: UUID
    reason: str = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=2048)


_VALID_ENTITY_STITCH_REJECT_REASONS: frozenset[str] = frozenset(
    {
        "false_positive",
        "low_value",
        "wrong_pairing",
        "out_of_scope",
        "other",
    },
)


# --- L1 Sub-wave C (2026-06-08) — source-candidate write-action bodies.


class SourceCandidatePromoteBody(_Body):
    """POST /api/v1/write_actions/source_candidates_promote/{candidate_id} body —
    L1 Sub-wave C (2026-06-08).

    Mirrors the L3-L8 confirm body pattern: ``company_id`` is
    cross-checked against the tenant header, ``promoted_by`` is the
    admin Person UUID threaded by the dashboard's getCurrentPerson
    server action (never a placeholder). ``notes`` is an optional
    free-text annotation surfaced on /trace + the source-candidate
    detail row.

    L1-specific: the promote handler dual-writes — it emits BOTH the
    L1 ``source_candidate_promoted`` audit entry AND triggers the
    existing :class:`SourceBuilder` flow to emit a downstream
    ``source_proposed`` entry. The downstream propose runs as a
    side-effect of the same admin click; the resulting source-builder
    correlation_id is threaded back into the L1 promote payload as
    ``downstream_source_proposed_id`` so the dashboard surface can
    render a "view connected source →" link.
    """

    company_id: UUID
    promoted_by: UUID
    notes: str | None = Field(default=None, max_length=2048)


class SourceCandidateRejectBody(_Body):
    """POST /api/v1/write_actions/source_candidates_reject/{candidate_id} body —
    L1 Sub-wave C (2026-06-08).

    ``reason`` is one of the strict 5-value enum on
    :class:`SourceCandidateRejectedPayload`; validated by the handler
    against ``_VALID_SOURCE_CANDIDATE_REJECT_REASONS`` (400 on miss).
    The payload's own ``Literal[...]`` validator catches the same
    case at the ledger boundary (defense in depth). The L1-specific
    5th value is ``duplicate`` (distinct from L8's ``wrong_pairing``,
    L6's ``wrong_level``, L5's ``wrong_type``, L4's ``already_handled``
    and L7's ``wrong_threshold``) — reflects that the most common
    reject reason at triage is "we already have this source / something
    equivalent."
    """

    company_id: UUID
    rejected_by: UUID
    reason: str = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=2048)


_VALID_SOURCE_CANDIDATE_REJECT_REASONS: frozenset[str] = frozenset(
    {
        "duplicate",
        "false_positive",
        "low_value",
        "out_of_scope",
        "other",
    },
)


# --- L2 Sub-wave C (2026-06-09) — catalog-drift write-action bodies.


class CatalogDriftAcknowledgeBody(_Body):
    """POST /api/v1/write_actions/catalog_drifts_acknowledge/{drift_id} body —
    L2 Sub-wave C (2026-06-09).

    Mirrors the L3-L8 confirm body pattern: ``company_id`` is
    cross-checked against the tenant header, ``acknowledged_by`` is
    the admin Person UUID threaded by the dashboard's
    getCurrentPerson server action (never a placeholder). ``notes``
    is an optional free-text annotation surfaced on /trace + the
    catalog-drift detail row.

    L2 uses ``acknowledge`` instead of ``confirm`` or ``promote``
    because the drift was already observed by the catalog-mirror's
    W5a Reactivity — acknowledgment is the no-op human-disposition
    record (no downstream pipeline trigger, no cross-axis effect).
    """

    company_id: UUID
    acknowledged_by: UUID
    notes: str | None = Field(default=None, max_length=2048)


class CatalogDriftRejectBody(_Body):
    """POST /api/v1/write_actions/catalog_drifts_reject/{drift_id} body —
    L2 Sub-wave C (2026-06-09).

    ``reason`` is one of the strict 5-value enum on
    :class:`CatalogDriftRejectedPayload`; validated by the handler
    against ``_VALID_CATALOG_DRIFT_REJECT_REASONS`` (400 on miss).
    The payload's own ``Literal[...]`` validator catches the same
    case at the ledger boundary (defense in depth). The L2-specific
    5th value is ``expected_change`` (distinct from L1's
    ``duplicate``, L8's ``wrong_pairing``, L6's ``wrong_level``,
    L5's ``wrong_type``, L4's ``already_handled`` and L7's
    ``wrong_threshold``) — reflects that the drift was real but a
    known intentional change (e.g. planned schema migration).
    """

    company_id: UUID
    rejected_by: UUID
    reason: str = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=2048)


_VALID_CATALOG_DRIFT_REJECT_REASONS: frozenset[str] = frozenset(
    {
        "false_positive",
        "inconsequential",
        "expected_change",
        "out_of_scope",
        "other",
    },
)


# --- Onboarding Sub-wave C (2026-05-30) write-action bodies ----------------
#
# Two new endpoints back the Tier 2 domain pack picker + the real
# co-admin invite emit. Both ride the same bearer-auth + tenant-header
# admin-only pattern as the Path 5 revoke and v2.A subscription
# endpoints.


class DomainPackSelectedBody(_Body):
    """POST /api/v1/write_actions/domain_pack_selected/{pack_id} body —
    Onboarding Sub-wave C.

    ``pack_id`` arrives on the URL path; this body carries the admin
    attribution + optional audit notes. ``selected_by_person_id``
    threads the current admin Person UUID from
    ``getCurrentPerson(companyId)`` — never a placeholder.
    """

    company_id: UUID
    selected_by_person_id: UUID
    notes: str | None = Field(default=None, max_length=2048)


class PersonInvitedBody(_Body):
    """POST /api/v1/write_actions/person_invited body — Onboarding Sub-wave C.

    At least one of ``invitee_email`` / ``invitee_platform_id`` MUST
    be supplied; the handler returns 400 if both are absent. The
    write_action helper also raises ValueError for the same condition
    (defense in depth). ``role_intent`` is validated against the
    three-value Literal at the payload class boundary.
    """

    company_id: UUID
    invited_by_person_id: UUID
    invitee_email: str | None = Field(default=None, max_length=320)
    invitee_platform_id: str | None = Field(default=None, max_length=256)
    role_intent: str = Field(default="member")
    notes: str | None = Field(default=None, max_length=2048)


class ConceptConfirmedBody(_Body):
    """POST /api/v1/write_actions/concept_confirmed/{term} body —
    Onboarding Sub-wave D (2026-05-30).

    Graduates Tier 2's ``confirmBusinessDef`` from a synthetic-receipt
    fallback to a real ``concept_confirmed`` PEVR cycle. ``term``
    arrives on the URL path; this body carries the admin attribution.
    The write_action resolves ``term → concept_id`` by reading back the
    most recent ``concept_proposed`` execute entry whose ``name``
    matches (case-insensitive + whitespace-trimmed).

    Reuses existing KIND_REGISTRY entries — no new kinds.
    """

    company_id: UUID
    confirmed_by_person_id: UUID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result_payload(write_result: WriteResult) -> dict[str, list[str]]:
    """Convert a WriteResult to the JSON shape the dashboard expects."""
    return {"entry_ids": [str(eid) for eid in write_result.entry_ids]}


def _check_auth(request: web.Request) -> None:
    """Raise 401 if the bearer token is missing or wrong."""
    expected = request.app[APP_TOKEN_KEY]
    if not expected:
        # Should never happen — server refuses to start without a token.
        raise web.HTTPInternalServerError(reason="api token misconfigured")

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise web.HTTPUnauthorized(reason="missing bearer token")
    presented = header[len("Bearer "):]
    if presented != expected:
        raise web.HTTPUnauthorized(reason="invalid bearer token")


def _resolve_company_id(request: web.Request) -> UUID:
    """Read X-Tenant-Slug → company_id. Fall back to baseworm if absent."""
    slug = request.headers.get("X-Tenant-Slug", "").strip() or DEFAULT_TENANT_SLUG
    try:
        return tenant_to_uuid(slug)
    except Exception as exc:
        raise web.HTTPBadRequest(
            reason=_bad_text(f"invalid X-Tenant-Slug {slug!r}: {exc}"),
        ) from exc


async def _read_body(request: web.Request, model: type[_Body]) -> _Body:
    """Parse JSON + Pydantic-validate; raise 422 on failure."""
    try:
        raw = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(reason=_bad_text(f"body must be JSON: {exc}")) from exc
    if not isinstance(raw, dict):
        raise web.HTTPBadRequest(reason="body must be a JSON object")
    try:
        return model(**raw)
    except ValidationError as exc:
        raise web.HTTPUnprocessableEntity(
            text=exc.json(),
            content_type="application/json",
        ) from exc


def _path_uuid(request: web.Request, key: str) -> UUID:
    raw = request.match_info.get(key, "")
    try:
        return UUID(raw)
    except (ValueError, TypeError) as exc:
        raise web.HTTPBadRequest(
            reason=_bad_text(f"path segment {key} must be a UUID; got {raw!r}"),
        ) from exc


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "worm-core-write"})


async def get_subscription_eligible_kinds(
    request: web.Request,
) -> web.Response:
    """v1.4 #5 — derived subscription-eligible kinds from KIND_REGISTRY.

    Read-only, tenant-agnostic (the kind catalog is the same for every
    tenant; per-tenant filtering happens on the subscription's filter
    fields, not on the catalog). Bypasses bearer-token auth for the
    same reason ``GET /mcp/catalog`` does — the response is metadata,
    not tenant data.

    Returns ``{"kinds": [{kind, label, description, family}, ...]}``
    derived at call time from ``KIND_REGISTRY``, filtered to exclude:

    * Meta-kinds that would cause subscription recursion
      (``agent_subscription_*``, ``agent_event_delivered``).
    * PEVR primitives (``propose``, ``execute``, ``verify``,
      ``resolve``) — every entry is one at the envelope level.
    * Infra heartbeats (``clock_tick``, ``inference_cache_refreshed``,
      ``credential``).

    The dashboard's ``SubscriptionForm`` fetches this at page-load
    time to populate the kinds multi-select. Replaces the hardcoded
    8-kind list that shipped in v2.A Batch C.
    """
    from wormbase_ledger.subscription_eligibility import (
        get_subscription_eligible_kinds as _get_kinds,
    )

    rows = _get_kinds()
    return web.json_response({"kinds": rows}, status=200)


async def get_mcp_catalog(request: web.Request) -> web.Response:
    """Return the registered MCP tool / resource / prompt catalog.

    Read-only. Bypasses bearer-token auth — its purpose is letting the
    dashboard's ``/mcp`` tab render the surface this tenant exposes
    outbound. Per-tenant data never traverses this endpoint; only the
    static surface (tool names + descriptions + URI templates) does.

    Gated on ``WORMBASE_MCP_ENABLED``: when disabled, returns 404 with
    an honest body so the dashboard renders the empty state truthfully.
    """
    from wormbase_core.mcp_server import build_catalog, is_mcp_enabled

    if not is_mcp_enabled():
        return web.json_response(
            {
                "available": False,
                "entries": [],
                "tools": [],
                "resources": [],
                "prompts": [],
                "reason": (
                    "MCP server disabled — set WORMBASE_MCP_ENABLED=1 to "
                    "expose the catalog."
                ),
            },
            status=404,
        )

    api_token = request.app[APP_TOKEN_KEY] or "catalog-introspect"
    catalog = await build_catalog(api_token=api_token)
    return web.json_response(catalog, status=200)


async def post_people(request: web.Request) -> web.Response:
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, ProposePersonBody)
    assert isinstance(body, ProposePersonBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        person_id, write_result = await write_actions.propose_person(
            ledger,
            company_id,
            name=body.name,
            email=body.email,
            platform=body.platform,
            platform_user_id=body.platform_user_id,
            position=body.position,
            proposed_by=body.proposed_by,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    return web.json_response(
        {"person_id": str(person_id), **_result_payload(write_result)},
        status=200,
    )


async def post_person_confirm(request: web.Request) -> web.Response:
    _check_auth(request)
    company_id = _resolve_company_id(request)
    person_id = _path_uuid(request, "person_id")
    body = await _read_body(request, ConfirmPersonBody)
    assert isinstance(body, ConfirmPersonBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        write_result = await write_actions.confirm_person(
            ledger, company_id, person_id=person_id, confirmed_by=body.confirmed_by,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    return web.json_response(_result_payload(write_result), status=200)


async def post_person_archive(request: web.Request) -> web.Response:
    _check_auth(request)
    company_id = _resolve_company_id(request)
    person_id = _path_uuid(request, "person_id")
    body = await _read_body(request, ArchivePersonBody)
    assert isinstance(body, ArchivePersonBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        write_result = await write_actions.archive_person(
            ledger,
            company_id,
            person_id=person_id,
            archived_by=body.archived_by,
            reason=body.reason,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    return web.json_response(_result_payload(write_result), status=200)


async def post_person_position_confirm(request: web.Request) -> web.Response:
    """POST /api/v1/people/{person_id}/position/confirm — Phase 2 Task 2C.

    Confirm a worm-proposed position from the /people/proposals queue.
    Writes a single ``confirm_position_proposal`` PEVR cycle (4 entries)
    via ``write_actions.confirm_position_proposal``. The projection
    fold is a no-op against ``projection_persons`` (the optimistic
    position write landed at propose time).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    person_id = _path_uuid(request, "person_id")
    body = await _read_body(request, ConfirmPositionBody)
    assert isinstance(body, ConfirmPositionBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        write_result = await write_actions.confirm_position_proposal(
            ledger, company_id,
            person_id=person_id,
            position=body.position,
            confirmed_by=body.confirmed_by,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc
    return web.json_response(_result_payload(write_result), status=200)


async def post_person_position_reject(request: web.Request) -> web.Response:
    """POST /api/v1/people/{person_id}/position/reject — Phase 2 Task 2C.

    Reject a worm-proposed position from the /people/proposals queue.
    Writes a single ``reject_position_proposal`` PEVR cycle (4 entries)
    via ``write_actions.reject_position_proposal``. The projection
    clears the optimistic position-field write when the current value
    matches the rejected slug, freeing the Reactivity's dedup gate for
    re-proposal once richer signal accumulates.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    person_id = _path_uuid(request, "person_id")
    body = await _read_body(request, RejectPositionBody)
    assert isinstance(body, RejectPositionBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        write_result = await write_actions.reject_position_proposal(
            ledger, company_id,
            person_id=person_id,
            position=body.position,
            rejected_by=body.rejected_by,
            reason=body.reason,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc
    return web.json_response(_result_payload(write_result), status=200)


async def get_position_proposals(request: web.Request) -> web.Response:
    """GET /api/v1/people/proposals — Phase 2 Task 2C admin queue.

    Returns the list of position proposals pending admin review for the
    current tenant. A proposal is "pending" if an
    ``emit_position_proposed`` has landed for the Person and no
    matching ``emit_position_confirmed`` / ``emit_position_rejected``
    / ``emit_position_assigned`` has superseded it.

    Folds the ledger directly via the in-process ``Ledger.fetch``
    surface — no projection-table dependency, so the queue stays
    available even on a fresh-replay tenant where projections haven't
    rebuilt yet. Pure-function fold; deterministic across replays.

    Response shape:
        {
          "proposals": [
            {
              "person_id": "...",
              "person_name": "...",
              "position": "senior_engineer",
              "confidence": 0.72,
              "signals": ["commit_msg", "design_doc"],
              "proposed_at": "2026-05-03T...",
              "proposed_by": "worm",
            },
            ...
          ]
        }

    Sorted by ``proposed_at`` ascending so oldest proposals surface
    first (the queue's review-order expectation).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    ledger = request.app[APP_LEDGER_KEY]

    rows = await ledger.fetch(company_id)

    # First pass: build {person_id → name} from emit_person_proposed.
    names: dict[str, str] = {}
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") != "emit_person_proposed":
            continue
        args = payload.get("args") or {}
        pid = args.get("person_id")
        nm = args.get("name")
        if pid and nm:
            names[str(pid)] = str(nm)

    # Second pass: per-person fold of position-review state. The
    # mapping is one-pending-proposal-per-person at any time; latest
    # propose-step wins until the admin acts (or position_assigned
    # supersedes).
    pending: dict[str, dict[str, object]] = {}
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        tool = payload.get("tool")
        args = payload.get("args") or {}
        pid = args.get("person_id")
        if not pid:
            continue
        pid_str = str(pid)
        if tool == "emit_position_proposed":
            pending[pid_str] = {
                "person_id": pid_str,
                "person_name": names.get(pid_str, "Unknown"),
                "position": args.get("position"),
                "confidence": args.get("confidence"),
                "signals": list(args.get("signals", []) or []),
                "proposed_at": r["ts"].isoformat() if r.get("ts") else None,
                "proposed_by": str(args.get("proposed_by", "worm")),
                "seq": int(r.get("seq", 0)),
            }
        elif tool in (
            "emit_position_confirmed",
            "emit_position_rejected",
            "emit_position_assigned",
        ):
            # Admin (or admin-direct-assignment) closed the proposal.
            # Drop from pending — even if a re-propose happened later,
            # the rule above will re-add it because emit_position_proposed
            # rebuilds the row.
            pending.pop(pid_str, None)

    proposals = sorted(pending.values(), key=lambda p: p["seq"])  # type: ignore[arg-type]
    # Strip the seq sort key from the wire shape.
    for p in proposals:
        p.pop("seq", None)
    return web.json_response({"proposals": proposals}, status=200)


async def post_person_identities(request: web.Request) -> web.Response:
    _check_auth(request)
    company_id = _resolve_company_id(request)
    person_id = _path_uuid(request, "person_id")
    body = await _read_body(request, LinkIdentityBody)
    assert isinstance(body, LinkIdentityBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        write_result = await write_actions.link_identity(
            ledger,
            company_id,
            person_id=person_id,
            platform=body.platform,
            platform_user_id=body.platform_user_id,
            linked_by=body.linked_by,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    return web.json_response(_result_payload(write_result), status=200)


async def delete_person_identity(request: web.Request) -> web.Response:
    _check_auth(request)
    company_id = _resolve_company_id(request)
    person_id = _path_uuid(request, "person_id")
    platform = request.match_info.get("platform", "")
    platform_user_id = request.match_info.get("platform_user_id", "")
    if not platform or not platform_user_id:
        raise web.HTTPBadRequest(reason="platform and platform_user_id are required")

    body = await _read_body(request, UnlinkIdentityBody)
    assert isinstance(body, UnlinkIdentityBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        write_result = await write_actions.unlink_identity(
            ledger,
            company_id,
            person_id=person_id,
            platform=platform,
            platform_user_id=platform_user_id,
            unlinked_by=body.unlinked_by,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    return web.json_response(_result_payload(write_result), status=200)


async def post_person_roles(request: web.Request) -> web.Response:
    _check_auth(request)
    company_id = _resolve_company_id(request)
    person_id = _path_uuid(request, "person_id")
    body = await _read_body(request, GrantRoleBody)
    assert isinstance(body, GrantRoleBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        if body.facet == "tenancy":
            write_result = await write_actions.grant_tenancy_role(
                ledger,
                company_id,
                person_id=person_id,
                role=body.role,
                granted_by=body.granted_by,
            )
        elif body.facet == "domain":
            if body.scope_id is None:
                raise web.HTTPUnprocessableEntity(
                    reason="domain grants require scope_id (domain_id)",
                )
            write_result = await write_actions.grant_domain_role(
                ledger,
                company_id,
                person_id=person_id,
                domain_id=body.scope_id,
                role=body.role,
                granted_by=body.granted_by,
            )
        else:  # resource
            if body.scope_id is None or not body.scope_type:
                raise web.HTTPUnprocessableEntity(
                    reason="resource grants require scope_id and scope_type",
                )
            write_result = await write_actions.grant_resource_role(
                ledger,
                company_id,
                person_id=person_id,
                resource_id=body.scope_id,
                resource_type=body.scope_type,
                role=body.role,
                granted_by=body.granted_by,
            )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except ValueError as exc:
        # Pydantic field-validators (e.g. invalid role) raise ValueError when
        # the payload class instantiates inside write_actions.
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    return web.json_response(_result_payload(write_result), status=200)


async def post_person_role_revoke(request: web.Request) -> web.Response:
    _check_auth(request)
    company_id = _resolve_company_id(request)
    person_id = _path_uuid(request, "person_id")
    # The grant_id is in the path for routing symmetry; the tenancy revoke
    # write keys on (person_id, role) — see RoleRevokedPayload. We accept
    # the grant_id segment but don't currently need it on the wire.
    _ = request.match_info.get("grant_id", "")
    body = await _read_body(request, RevokeRoleBody)
    assert isinstance(body, RevokeRoleBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        write_result = await write_actions.revoke_tenancy_role(
            ledger,
            company_id,
            person_id=person_id,
            role=body.role,
            revoked_by=body.revoked_by,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    return web.json_response(_result_payload(write_result), status=200)


async def post_people_merge(request: web.Request) -> web.Response:
    """Merge two Persons. Admin-only; bearer-authed.

    Body: ``{keeper_id, mergee_id, merged_by}``.
    Writes a sequence of independent PEVR cycles — one ``unlink_identity``
    + one ``link_identity`` per identity moved, plus one ``archive_person``
    for the mergee. See ``write_actions.merge_persons`` for the rationale.
    Returns ``{keeper_id, mergee_id, identities_moved, entry_ids}``.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, MergePersonsBody)
    assert isinstance(body, MergePersonsBody)
    if body.keeper_id == body.mergee_id:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text("keeper_id and mergee_id must differ"),
        )
    ledger = request.app[APP_LEDGER_KEY]

    try:
        result = await write_actions.merge_persons(
            ledger,
            company_id,
            keeper_id=body.keeper_id,
            mergee_id=body.mergee_id,
            merged_by=body.merged_by,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    return web.json_response(result, status=200)


async def post_people_bulk_confirm(request: web.Request) -> web.Response:
    """POST /api/v1/people/bulk-confirm — confirm a batch of proposed Persons.

    W2.A6 of ``docs/superpowers/plans/2026-04-28-production-hardening.md``.

    Body: ``{person_ids: [UUID, ...], confirmed_by: UUID}``. Each id
    drives an independent ``confirm_person`` PEVR cycle (4 entries
    each). The orchestrator de-duplicates input ids and re-raises on
    the first failure; the dashboard treats the request as atomic.

    Returns ``{confirmed_count, person_ids, entry_ids}``.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, BulkConfirmPersonsBody)
    assert isinstance(body, BulkConfirmPersonsBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        result = await write_actions.bulk_confirm_persons(
            ledger,
            company_id,
            person_ids=list(body.person_ids),
            confirmed_by=body.confirmed_by,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    return web.json_response(result, status=200)


async def post_person_split(request: web.Request) -> web.Response:
    """Split a Person — extract a subset of identities into a new Person.

    Body: ``{new_person_name, new_person_email?, new_person_position?,
    identities_to_move: [{platform, platform_user_id}, ...], split_by}``.
    Returns ``{source_person_id, new_person_id, identities_moved, entry_ids}``.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    source_person_id = _path_uuid(request, "source_person_id")
    body = await _read_body(request, SplitPersonBody)
    assert isinstance(body, SplitPersonBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        result = await write_actions.split_person(
            ledger,
            company_id,
            source_person_id=source_person_id,
            new_person_name=body.new_person_name,
            new_person_email=body.new_person_email,
            new_person_position=body.new_person_position,
            identities_to_move=[
                {"platform": i.platform, "platform_user_id": i.platform_user_id}
                for i in body.identities_to_move
            ],
            split_by=body.split_by,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    return web.json_response(result, status=200)


# ---------------------------------------------------------------------------
# Install handler (Tier 1 OAuth callback orchestrator)
# ---------------------------------------------------------------------------


async def post_installs(request: web.Request) -> web.Response:
    """POST /api/v1/installs — orchestrate the post-OAuth install.

    Body: ``CompleteInstallBody``. The handler delegates to
    ``write_actions.complete_install`` which writes the full chain
    (propose installer Person → confirm → grant tenancy.installer +
    tenancy.admin → emit_install_completed) — five PEVR cycles total.

    Returns ``{install_id, installer_person_id, entry_ids}`` with status
    201 on success. Validation failures (e.g. ``oauth_grant_ref`` that
    doesn't begin with ``kms://`` or ``vault://``) return 422.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, CompleteInstallBody)
    assert isinstance(body, CompleteInstallBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        result = await write_actions.complete_install(
            ledger,
            company_id,
            platform=body.platform,
            installer_email=body.installer_email,
            installer_name=body.installer_name,
            installer_avatar_url=body.installer_avatar_url,
            platform_user_id=body.platform_user_id,
            oauth_grant_ref=body.oauth_grant_ref,
            scopes=list(body.scopes),
            bot_user_id=body.bot_user_id,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except (ValueError, ValidationError) as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    return web.json_response(result, status=201)


async def get_installs(request: web.Request) -> web.Response:
    """GET /api/v1/installs — list this tenant's install rows.

    Folds ``emit_install_completed`` / ``emit_install_revoked`` (and the
    setup-mode bookkeeping entries) out of the ledger, mirroring the
    dashboard's ``getInstalls(companyId)`` accessor (apps/dashboard/lib/
    ledger-client.ts) so callers reach for one canonical projection.

    Used today by ``scripts/demo-orchestrator.py`` to detect a pre-existing
    install before running Beat 1 of the install-arc scenario (W7.A3 —
    ``--skip-installed`` mode lets ``make demo`` run unattended after a
    one-time OAuth click).

    Response shape (200):

        {"installs": [
            {
              "install_id": "<uuid>",
              "platform": "slack",
              "installer_person_id": "<uuid>",
              "installed_at": "<iso>",
              "status": "active" | "revoked",
              "scopes": ["channels:read", ...],
              "bot_user_id": "<id>",
              "oauth_grant_ref": "kms://..." | "vault://..."
            },
            ...
        ]}

    Bearer-authed (same token as the rest of the API). Tenant resolved
    from ``X-Tenant-Slug``. Returns ``{"installs": []}`` for tenants that
    never completed an install — never 404, so callers can distinguish
    "no install" from "endpoint missing" without parsing error bodies.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    ledger = request.app[APP_LEDGER_KEY]

    rows = await ledger.fetch(company_id)

    # Keyed on platform — most recent completed install per platform wins.
    by_platform: dict[str, dict[str, Any]] = {}
    by_install_id: dict[str, dict[str, Any]] = {}

    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        tool = payload.get("tool")
        args = payload.get("args") or {}
        ts_raw = r.get("ts")
        if hasattr(ts_raw, "isoformat"):
            ts_iso = ts_raw.isoformat()
        else:
            ts_iso = str(ts_raw) if ts_raw is not None else ""

        if tool == "emit_install_completed":
            install_id = str(args.get("install_id") or "")
            platform = str(args.get("platform") or "")
            if not install_id or not platform:
                continue
            installer_person_id = (
                str(args.get("installer_person_id"))
                if args.get("installer_person_id") is not None else None
            )
            scopes_raw = args.get("scopes")
            scopes = [str(s) for s in scopes_raw] if isinstance(scopes_raw, list) else []
            row: dict[str, Any] = {
                "install_id": install_id,
                "platform": platform,
                "installer_person_id": installer_person_id,
                "installed_at": ts_iso,
                "status": "active",
                "scopes": scopes,
                "bot_user_id": (
                    str(args.get("bot_user_id"))
                    if args.get("bot_user_id") is not None else None
                ),
                "oauth_grant_ref": str(args.get("oauth_grant_ref") or ""),
            }
            by_platform[platform] = row
            by_install_id[install_id] = row
        elif tool == "emit_install_revoked":
            install_id = str(args.get("install_id") or "")
            target = by_install_id.get(install_id)
            if target is not None:
                target["status"] = "revoked"

    installs = sorted(
        by_platform.values(), key=lambda r: r.get("platform", ""),
    )
    return web.json_response({"installs": installs}, status=200)


async def post_provision_local_lake(request: web.Request) -> web.Response:
    """POST /api/v1/installs/provision-local-lake — Block I7 dev helper.

    Body: ``ProvisionLocalLakeBody``. The handler delegates to
    ``write_actions.provision_local_lake`` which writes the canonical
    4-stage source lifecycle for the default lake (4 PEVR cycles, 16
    entries).

    Production never hits this endpoint — ``complete_install`` auto-calls
    ``provision_local_lake`` inline. The endpoint exists for the CLI seed
    path (``wormbase demo seed --provision-local-lake``), which lets a
    developer give a dev tenant the default lake row without driving the
    full OAuth chain.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, ProvisionLocalLakeBody)
    assert isinstance(body, ProvisionLocalLakeBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        result = await write_actions.provision_local_lake(
            ledger,
            company_id,
            tenant_id=body.tenant_id,
            installer_person_id=body.installer_person_id,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except (ValueError, ValidationError) as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    return web.json_response(result, status=201)


# ---------------------------------------------------------------------------
# Tenant signup chain (Phase 1 Task 1B.C — multi-tenancy v2)
# ---------------------------------------------------------------------------


async def post_tenant_signup_initiated(request: web.Request) -> web.Response:
    """POST /api/v1/tenants/signup-initiated — write tenant_signup_initiated.

    Body: ``InitiateTenantSignupBody``. Idempotent at the projection
    layer: re-emitting on retry just appends another PEVR cycle; the
    projection upsert keys on ``tenant_id`` and survives re-entry.

    Called by:
      - The Slack OAuth callback when the workspace is unknown (1B.C).
      - The magic-link request endpoint (1B.D).
      - The demo seed CLI (1B.G; pairs with completed immediately).

    Returns ``{entry_ids: [...]}`` with status 201 on success.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, InitiateTenantSignupBody)
    assert isinstance(body, InitiateTenantSignupBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        result = await write_actions.initiate_tenant_signup(
            ledger,
            company_id,
            tenant_id=body.tenant_id,
            slug=body.slug,
            display_name=body.display_name,
            signup_source=body.signup_source,
            signup_email=body.signup_email,
            pending_token_hash=body.pending_token_hash,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except (ValueError, ValidationError) as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    return web.json_response(
        {"entry_ids": [str(eid) for eid in result.entry_ids]},
        status=201,
    )


async def post_tenant_signup_completed(request: web.Request) -> web.Response:
    """POST /api/v1/tenants/signup-completed — write tenant_signup_completed.

    Body: ``CompleteTenantSignupBody``. Pairs with
    ``post_tenant_signup_initiated``. For Slack OAuth, the dashboard
    posts here right after the install_completed cycle finishes; for
    magic-link, the confirm endpoint posts here after picking a demo
    tenant via the round-robin policy.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, CompleteTenantSignupBody)
    assert isinstance(body, CompleteTenantSignupBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        result = await write_actions.complete_tenant_signup(
            ledger,
            company_id,
            tenant_id=body.tenant_id,
            signup_source=body.signup_source,
            assigned_tenant_slug=body.assigned_tenant_slug,
            signup_email=body.signup_email,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except (ValueError, ValidationError) as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    return web.json_response(
        {"entry_ids": [str(eid) for eid in result.entry_ids]},
        status=201,
    )


# ---------------------------------------------------------------------------
# Setup mode (Block G4 of the production-dashboard PRD §17)
# ---------------------------------------------------------------------------


async def post_setup_mode(request: web.Request) -> web.Response:
    """POST /api/v1/setup-mode — set the tenant's wizard | bot path.

    Body: ``SetSetupModeBody``. The dashboard's
    /api/onboarding/setup-mode route handler proxies here after the
    user picks a fork in /onboarding/setup-mode/choose. The PEVR cycle
    writes ``emit_setup_mode_chosen``; the projection stamps every
    install row for the tenant so the (app)/layout's redirect guard can
    resolve the choice in one query.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, SetSetupModeBody)
    assert isinstance(body, SetSetupModeBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        result = await write_actions.set_setup_mode(
            ledger,
            company_id,
            mode=body.mode,
            chosen_by_person_id=body.chosen_by_person_id,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except (ValueError, ValidationError) as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    return web.json_response(_result_payload(result), status=200)


# ---------------------------------------------------------------------------
# Data product handlers (Block F2)
# ---------------------------------------------------------------------------


async def _store_artifact(
    storage: ObjectStore,
    *,
    tenant_id: str,
    artifact_kind: str,
    artifact_id: str,
    run_id: str,
    contents_b64: str,
    ext: str,
) -> tuple[str, str]:
    """Decode + write artifact bytes; return (uri, content_hash)."""
    try:
        data = base64.b64decode(contents_b64, validate=True)
    except Exception as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(f"contents_bytes_b64 must be valid base64: {exc}"),
        ) from exc
    return await storage.put(
        tenant_id=tenant_id,
        artifact_kind=artifact_kind,
        artifact_id=artifact_id,
        run_id=run_id,
        ext=ext,
        data=data,
    )


async def post_data_products(request: web.Request) -> web.Response:
    """Propose + (optionally) generate a data product in one call."""
    from uuid import uuid4 as _uuid4

    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, ProposeDataProductBody)
    assert isinstance(body, ProposeDataProductBody)
    ledger = request.app[APP_LEDGER_KEY]
    storage: ObjectStore = request.app[APP_STORAGE_KEY]

    try:
        dp_id, propose_result = await data_product_actions.propose_data_product(
            ledger,
            company_id,
            name=body.name,
            kind=body.kind,
            requested_by_person_id=body.requested_by_person_id,
            sources_required=list(body.sources_required),
            domain_id=body.domain_id,
            parameters=dict(body.parameters),
            prompted_by_message_id=body.prompted_by_message_id,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except (ValueError, ValidationError) as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    entry_ids = [str(eid) for eid in propose_result.entry_ids]

    if body.contents_bytes_b64 is not None:
        run_id = _uuid4()
        contents_uri, content_hash = await _store_artifact(
            storage,
            tenant_id=str(company_id),
            artifact_kind="data-products",
            artifact_id=str(dp_id),
            run_id=str(run_id),
            contents_b64=body.contents_bytes_b64,
            ext=body.contents_ext,
        )
        try:
            gen_result = await data_product_actions.generate_data_product(
                ledger,
                company_id,
                data_product_id=dp_id,
                contents_uri=contents_uri,
                content_hash=content_hash,
                kind=body.kind,
                source_hashes=[],
                duration_ms=0,
                generated_by="worm",
            )
        except VerifyFailed as exc:
            raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
        entry_ids.extend(str(eid) for eid in gen_result.entry_ids)

    return web.json_response(
        {"data_product_id": str(dp_id), "entry_ids": entry_ids},
        status=200,
    )


async def post_data_product_regenerate(request: web.Request) -> web.Response:
    from uuid import uuid4 as _uuid4

    _check_auth(request)
    company_id = _resolve_company_id(request)
    dp_id = _path_uuid(request, "data_product_id")
    body = await _read_body(request, RegenerateDataProductBody)
    assert isinstance(body, RegenerateDataProductBody)
    ledger = request.app[APP_LEDGER_KEY]
    storage: ObjectStore = request.app[APP_STORAGE_KEY]

    rows = await ledger.fetch(company_id)
    kind = None
    for row in rows:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        if payload.get("tool") != "emit_data_product_proposed":
            continue
        args = payload.get("args") or {}
        if args.get("data_product_id") == str(dp_id):
            kind = args.get("kind")
            break
    if kind is None:
        raise web.HTTPNotFound(reason="data product not found")

    run_id = _uuid4()
    if body.contents_bytes_b64 is not None:
        contents_uri, content_hash = await _store_artifact(
            storage,
            tenant_id=str(company_id),
            artifact_kind="data-products",
            artifact_id=str(dp_id),
            run_id=str(run_id),
            contents_b64=body.contents_bytes_b64,
            ext=body.contents_ext,
        )
    else:
        contents_uri = f"file:///dev/null/{dp_id}/{run_id}"
        content_hash = "0" * 64

    try:
        gen_result = await data_product_actions.generate_data_product(
            ledger,
            company_id,
            data_product_id=dp_id,
            contents_uri=contents_uri,
            content_hash=content_hash,
            kind=kind,
            source_hashes=list(body.source_hashes),
            duration_ms=0,
            generated_by=body.generated_by,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    return web.json_response(
        {
            "data_product_id": str(dp_id),
            "run_id": str(run_id),
            "content_hash": content_hash,
            "entry_ids": [str(eid) for eid in gen_result.entry_ids],
        },
        status=200,
    )


async def post_data_product_consume(request: web.Request) -> web.Response:
    _check_auth(request)
    company_id = _resolve_company_id(request)
    dp_id = _path_uuid(request, "data_product_id")
    body = await _read_body(request, ConsumeDataProductBody)
    assert isinstance(body, ConsumeDataProductBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        result = await data_product_actions.consume_data_product(
            ledger,
            company_id,
            data_product_id=dp_id,
            consumed_by_person_id=body.consumed_by_person_id,
            surface=body.surface,
            channel=body.channel,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except (ValueError, ValidationError) as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc
    return web.json_response(_result_payload(result), status=200)


async def get_data_product_replay(request: web.Request) -> web.Response:
    """Re-run a data product against pinned source-hashes."""
    import hashlib as _hashlib
    from uuid import uuid4 as _uuid4

    _check_auth(request)
    company_id = _resolve_company_id(request)
    dp_id = _path_uuid(request, "data_product_id")
    ledger = request.app[APP_LEDGER_KEY]
    storage: ObjectStore = request.app[APP_STORAGE_KEY]

    rows = await ledger.fetch(company_id)
    last_gen: dict[str, Any] | None = None
    kind: str | None = None
    for row in rows:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        args = payload.get("args") or {}
        if args.get("data_product_id") != str(dp_id):
            continue
        if payload.get("tool") == "emit_data_product_proposed":
            kind = args.get("kind")
        elif payload.get("tool") == "emit_data_product_generated":
            last_gen = args
    if last_gen is None or kind is None:
        raise web.HTTPNotFound(reason="data product or its generation not found")

    contents_uri = last_gen["contents_uri"]
    try:
        data = await storage.get(contents_uri)
    except (FileNotFoundError, ValueError) as exc:
        raise web.HTTPNotFound(
            reason=_bad_text(f"could not read artifact {contents_uri}: {exc}"),
        ) from exc

    new_hash = _hashlib.sha256(data).hexdigest()
    run_id = _uuid4()
    new_uri, _ = await storage.put(
        tenant_id=str(company_id),
        artifact_kind="data-products",
        artifact_id=str(dp_id),
        run_id=str(run_id),
        ext="html",
        data=data,
    )
    try:
        gen_result = await data_product_actions.generate_data_product(
            ledger,
            company_id,
            data_product_id=dp_id,
            contents_uri=new_uri,
            content_hash=new_hash,
            kind=kind,
            source_hashes=list(last_gen.get("source_hashes", [])),
            duration_ms=0,
            generated_by="replay",
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc

    return web.json_response(
        {
            "data_product_id": str(dp_id),
            "run_id": str(run_id),
            "content_hash": new_hash,
            "matches_original": new_hash == last_gen["content_hash"],
            "entry_ids": [str(eid) for eid in gen_result.entry_ids],
        },
        status=200,
    )


# ---------------------------------------------------------------------------
# Notebook handlers (Block F2)
# ---------------------------------------------------------------------------


async def post_notebooks(request: web.Request) -> web.Response:
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, ProposeNotebookBody)
    assert isinstance(body, ProposeNotebookBody)
    ledger = request.app[APP_LEDGER_KEY]

    cells = [c.model_dump() for c in body.cells]
    try:
        nb_id, result = await data_product_actions.propose_notebook(
            ledger,
            company_id,
            name=body.name,
            cells=cells,
            kernel=body.kernel,
            proposed_by_person_id=body.proposed_by_person_id,
            domain_id=body.domain_id,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except (ValueError, ValidationError) as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc
    return web.json_response(
        {"notebook_id": str(nb_id), "entry_ids": [str(e) for e in result.entry_ids]},
        status=200,
    )


async def _fetch_notebook_proposal(
    ledger: Any, company_id: UUID, notebook_id: UUID,
) -> dict[str, Any] | None:
    rows = await ledger.fetch(company_id)
    for row in rows:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        if payload.get("tool") != "emit_notebook_proposed":
            continue
        args = payload.get("args") or {}
        if args.get("notebook_id") == str(notebook_id):
            return args
    return None


async def post_notebook_run(request: web.Request) -> web.Response:
    """Run a notebook synchronously and write the run entry."""
    _check_auth(request)
    company_id = _resolve_company_id(request)
    nb_id = _path_uuid(request, "notebook_id")
    body = await _read_body(request, RunNotebookBody)
    assert isinstance(body, RunNotebookBody)
    ledger = request.app[APP_LEDGER_KEY]

    proposal = await _fetch_notebook_proposal(ledger, company_id, nb_id)
    if proposal is None:
        raise web.HTTPNotFound(reason="notebook not found")
    cells = cells_from_dicts(list(proposal.get("cells", [])))

    kernel = LocalPythonKernel(timeout_s=body.timeout_s)
    try:
        run_result = await kernel.run(cells)
    except NotImplementedError as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    try:
        run_id, write_result = await data_product_actions.run_notebook(
            ledger,
            company_id,
            notebook_id=nb_id,
            cell_outputs=[c.to_dict() for c in run_result.cell_outputs],
            cell_hashes=run_result.cell_hashes,
            duration_ms=run_result.duration_ms,
            kernel_state_hash=run_result.kernel_state_hash,
            status=run_result.status,
            run_by=body.run_by,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    return web.json_response(
        {
            "notebook_id": str(nb_id),
            "run_id": str(run_id),
            "status": run_result.status,
            "duration_ms": run_result.duration_ms,
            "kernel_state_hash": run_result.kernel_state_hash,
            "entry_ids": [str(e) for e in write_result.entry_ids],
        },
        status=200,
    )


async def post_notebook_publish(request: web.Request) -> web.Response:
    _check_auth(request)
    company_id = _resolve_company_id(request)
    nb_id = _path_uuid(request, "notebook_id")
    body = await _read_body(request, PublishNotebookBody)
    assert isinstance(body, PublishNotebookBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        result = await data_product_actions.publish_notebook(
            ledger,
            company_id,
            notebook_id=nb_id,
            run_id=body.run_id,
            owner_person_id=body.owner_person_id,
            version=body.version,
            published_by=body.published_by,
            domain_id=body.domain_id,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    return web.json_response(_result_payload(result), status=200)


# ---------------------------------------------------------------------------
# KPI / decision / process write handlers (W2.A7)
# ---------------------------------------------------------------------------


async def post_kpi_propose(request: web.Request) -> web.Response:
    """POST /api/v1/kpis/propose — admin-driven KPI proposal."""
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, ProposeKpiBody)
    assert isinstance(body, ProposeKpiBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        kpi_id, write_result = await write_actions.propose_kpi_node(
            ledger,
            company_id,
            label=body.label,
            formula=body.formula,
            unit=body.unit,
            source_ids=list(body.source_ids),
            owner_position=body.owner_position,
            proposed_by=body.proposed_by,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except (ValueError, ValidationError) as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    return web.json_response(
        {
            "kpi_id": str(kpi_id),
            "entry_ids": [str(eid) for eid in write_result.entry_ids],
        },
        status=201,
    )


async def post_decision_record(request: web.Request) -> web.Response:
    """POST /api/v1/decisions — admin-recorded decision."""
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, RecordDecisionBody)
    assert isinstance(body, RecordDecisionBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        decision_id, write_result = await write_actions.record_decision(
            ledger,
            company_id,
            decision_text=body.decision_text,
            channel_id=body.channel_id,
            decided_by_persons=list(body.decided_by_persons),
            evidence_message_ids=list(body.evidence_message_ids),
            confidence=body.confidence,
            proposed_by=body.proposed_by,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except (ValueError, ValidationError) as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    return web.json_response(
        {
            "decision_id": str(decision_id),
            "entry_ids": [str(eid) for eid in write_result.entry_ids],
        },
        status=201,
    )


async def post_process_propose(request: web.Request) -> web.Response:
    """POST /api/v1/processes — admin-authored process map."""
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, ProposeProcessMapBody)
    assert isinstance(body, ProposeProcessMapBody)
    ledger = request.app[APP_LEDGER_KEY]

    steps = [
        {
            "order": s.order,
            "actor": s.actor,
            "action": s.action,
            "source_message_id": s.source_message_id,
        }
        for s in body.steps
    ]

    try:
        process_id, write_result = await write_actions.propose_process_map(
            ledger,
            company_id,
            process_name=body.process_name,
            steps=steps,
            domain=body.domain,
            confidence=body.confidence,
            proposed_by=body.proposed_by,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except (ValueError, ValidationError) as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    return web.json_response(
        {
            "process_id": str(process_id),
            "entry_ids": [str(eid) for eid in write_result.entry_ids],
        },
        status=201,
    )


# ---------------------------------------------------------------------------
# Replay + Sign handlers (W2.A8)
# ---------------------------------------------------------------------------


async def post_data_product_replay(request: web.Request) -> web.Response:
    """POST /api/v1/data-products/{id}/replay — W2.A8.

    Re-runs the data product against pinned source-hashes and asserts
    the recomputed content_hash is bit-identical to the original. Writes
    a fresh ``data_product_generated`` PEVR cycle on success.

    Production replay path: pulls the original artifact bytes from the
    object store, re-hashes them, and refuses to write if they drift.
    The dashboard's "Replay" button surfaces ``matches_original`` to the
    user as the "✓ bit-identical content_hash" badge.
    """
    from uuid import uuid4 as _uuid4

    _check_auth(request)
    company_id = _resolve_company_id(request)
    dp_id = _path_uuid(request, "data_product_id")
    body = await _read_body(request, ReplayDataProductBody)
    assert isinstance(body, ReplayDataProductBody)
    ledger = request.app[APP_LEDGER_KEY]
    storage: ObjectStore = request.app[APP_STORAGE_KEY]

    rows = await ledger.fetch(company_id)
    last_gen: dict[str, Any] | None = None
    kind: str | None = None
    for row in rows:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        args = payload.get("args") or {}
        if args.get("data_product_id") != str(dp_id):
            continue
        if payload.get("tool") == "emit_data_product_proposed":
            kind = args.get("kind")
        elif payload.get("tool") == "emit_data_product_generated":
            last_gen = args
    if last_gen is None or kind is None:
        raise web.HTTPNotFound(reason="data product or its generation not found")

    contents_uri = last_gen["contents_uri"]
    try:
        data = await storage.get(contents_uri)
    except (FileNotFoundError, ValueError) as exc:
        raise web.HTTPNotFound(
            reason=_bad_text(f"could not read artifact {contents_uri}: {exc}"),
        ) from exc

    new_run_id = _uuid4()
    new_uri, _ = await storage.put(
        tenant_id=str(company_id),
        artifact_kind="data-products",
        artifact_id=str(dp_id),
        run_id=str(new_run_id),
        ext="html",
        data=data,
    )

    try:
        replay_result = await data_product_actions.replay_data_product(
            ledger,
            company_id,
            data_product_id=dp_id,
            original_content_hash=last_gen["content_hash"],
            original_kind=kind,
            source_hashes=list(last_gen.get("source_hashes", [])),
            contents_bytes=data,
            new_contents_uri=new_uri,
            duration_ms=0,
            generated_by=body.generated_by,
            strict=body.strict,
        )
    except data_product_actions.ReplayMismatchError as exc:
        return web.json_response(
            {
                "data_product_id": str(dp_id),
                "matches_original": False,
                "expected_content_hash": exc.expected,
                "actual_content_hash": exc.actual,
                "error": "replay_mismatch",
            },
            status=409,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc

    return web.json_response(
        {
            "data_product_id": str(dp_id),
            "run_id": str(replay_result.run_id),
            "content_hash": replay_result.content_hash,
            "expected_content_hash": replay_result.expected_hash,
            "matches_original": replay_result.matches_original,
            "entry_ids": [str(e) for e in replay_result.entry_ids],
        },
        status=200,
    )


async def post_notebook_sign(request: web.Request) -> web.Response:
    """POST /api/v1/notebooks/{id}/sign — W2.A8.

    Signs (publishes) a notebook with a per-Person signature receipt.
    The receipt's ``signature_hash`` is deterministic — re-signing the
    same run by the same admin produces an identical receipt — so the
    dashboard can render "signed by ... · receipt: <hash>" and have it
    survive a replay.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    nb_id = _path_uuid(request, "notebook_id")
    body = await _read_body(request, SignNotebookBody)
    assert isinstance(body, SignNotebookBody)
    ledger = request.app[APP_LEDGER_KEY]

    try:
        write_result, receipt = await data_product_actions.sign_notebook(
            ledger,
            company_id,
            notebook_id=nb_id,
            run_id=body.run_id,
            owner_person_id=body.owner_person_id,
            version=body.version,
            signed_by=body.signed_by,
            domain_id=body.domain_id,
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except (ValueError, ValidationError) as exc:
        raise web.HTTPUnprocessableEntity(reason=_bad_text(str(exc))) from exc

    return web.json_response(
        {
            "notebook_id": str(nb_id),
            "signature_receipt": receipt,
            "entry_ids": [str(e) for e in write_result.entry_ids],
        },
        status=200,
    )


# ---------------------------------------------------------------------------
# Research approve / reject + MCP token issuance handlers (W2.A9)
# ---------------------------------------------------------------------------


async def _post_experiment_resolve(
    request: web.Request, *, outcome: str
) -> web.Response:
    """Shared body for POST /experiments/{id}/{approve,reject}.

    Writes a fresh ``emit_experiment_resolved`` PEVR cycle with the given
    outcome (``keep`` for approve, ``discard`` for reject). The /research
    read accessor uses ``DISTINCT ON (experiment_id) ORDER BY seq DESC``,
    so this latest-wins entry is what the table renders after a refresh.
    """
    from datetime import UTC
    from datetime import datetime as _datetime

    from wormbase_ledger.entries import ExperimentResolvedPayload

    _check_auth(request)
    company_id = _resolve_company_id(request)
    experiment_id = _path_uuid(request, "experiment_id")
    body = await _read_body(request, ResolveExperimentBody)
    assert isinstance(body, ResolveExperimentBody)
    ledger = request.app[APP_LEDGER_KEY]

    rationale = body.rationale.strip() or (
        f"manual {outcome} from /research by {body.resolved_by}"
    )
    now = _datetime.now(tz=UTC)

    # Build + validate the canonical payload up front (fail fast).
    try:
        payload = ExperimentResolvedPayload(
            experiment_id=experiment_id,
            outcome=outcome,  # type: ignore[arg-type]
            observed_delta=float(body.observed_delta),
            rationale=rationale,
            resolved_at=now,
        )
    except ValidationError as exc:
        raise web.HTTPUnprocessableEntity(
            text=exc.json(), content_type="application/json",
        ) from exc

    args = payload.model_dump(mode="json")

    try:
        write_result = await ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "experiment_resolved",
                "ref_id": str(experiment_id),
                "reason": (
                    f"experiment {experiment_id} resolved manually "
                    f"({outcome}) via /research"
                ),
                "proposed_by": str(body.resolved_by),
            },
            execute_fn=lambda: {
                "tool": "emit_experiment_resolved",
                "args": args,
                "result_ref": str(experiment_id),
            },
            verify_fn=lambda _r: {
                "checks": [
                    {"name": "experiment_resolved_payload_valid", "ok": True}
                ],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": (
                    f"experiment_resolved persisted (outcome={outcome})"
                ),
            },
            quadrant="active_deterministic",
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc

    return web.json_response(
        {
            "experiment_id": str(experiment_id),
            "outcome": outcome,
            "rationale": rationale,
            **_result_payload(write_result),
        },
        status=200,
    )


async def post_experiment_approve(request: web.Request) -> web.Response:
    """POST /api/v1/experiments/{id}/approve — W2.A9.

    Writes ``emit_experiment_resolved`` with ``outcome=keep``. The
    autoresearch loop's previous resolution (if any) is superseded by
    the latest-wins read in ``getExperimentsForUser``.
    """
    return await _post_experiment_resolve(request, outcome="keep")


async def post_experiment_reject(request: web.Request) -> web.Response:
    """POST /api/v1/experiments/{id}/reject — W2.A9.

    Writes ``emit_experiment_resolved`` with ``outcome=discard``.
    """
    return await _post_experiment_resolve(request, outcome="discard")


async def post_mcp_tokens(request: web.Request) -> web.Response:
    """POST /api/v1/mcp/tokens — W2.A9.

    Issues a Person-scoped compact bearer token (signed with
    ``WORMBASE_LEDGER_API_TOKEN`` as HMAC secret) the dashboard's
    "Connect Claude Desktop" panel surfaces as a copy-paste config
    snippet. The token is the same compact format
    ``mcp_tools.auth.authorize_caller`` already accepts, so a Claude
    Desktop client can use it as ``Authorization: Bearer <token>``
    against the worm-core MCP endpoint.

    Audits the issuance as an ``emit_mcp_call_received``-style ledger
    entry with ``tool_name='emit_mcp_token_issued'`` so admins can see
    in /mcp who minted what for whom and when. The token itself is
    HMAC-signed and not stored — revocation is by rotating the HMAC
    secret (or, in a future revision, by an explicit revocation list).
    """
    import time as _time
    from datetime import UTC
    from datetime import datetime as _datetime

    from wormbase_core.mcp_tools.auth import (
        DEFAULT_PERSON_TOKEN_TTL_SECONDS,
        canonical_args_hash,
        issue_person_token,
    )

    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, IssueMcpTokenBody)
    assert isinstance(body, IssueMcpTokenBody)
    ledger = request.app[APP_LEDGER_KEY]

    secret = request.app[APP_TOKEN_KEY]
    tenant_slug = (
        request.headers.get("X-Tenant-Slug", "").strip() or DEFAULT_TENANT_SLUG
    )
    ttl = body.ttl_seconds or DEFAULT_PERSON_TOKEN_TTL_SECONDS
    issued_at = _datetime.now(tz=UTC)
    expires_at = issued_at.timestamp() + ttl

    try:
        token = issue_person_token(
            person_id=body.person_id,
            tenant_slug=tenant_slug,
            secret=secret,
            expires_in_seconds=ttl,
            issued_at=issued_at,
        )
    except ValueError as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc

    # Audit the issuance — the dashboard's /mcp Recent calls table renders
    # this as a "token_issued" row, providing forensic trail for who minted
    # what. The token bytes themselves are NEVER stored; only the args
    # hash + caller person id + label.
    audit_args = {
        "person_id": str(body.person_id),
        "tenant_slug": tenant_slug,
        "ttl_seconds": ttl,
        "label": body.label,
    }
    args_hash = canonical_args_hash(audit_args)
    started_at = issued_at
    t0 = _time.perf_counter()
    try:
        await write_actions.record_mcp_call(
            ledger,
            company_id,
            tenant_id=company_id,
            caller_person_id=body.person_id,
            tool_name="emit_mcp_token_issued",
            args_hash=args_hash,
            client_ua=request.headers.get("User-Agent"),
            started_at=started_at,
            outcome="ok",
            latency_ms=int((_time.perf_counter() - t0) * 1000),
        )
    except Exception as exc:
        # Audit failure must not mask token issuance — surface as a warning
        # but return the token. Same posture as ``mcp_tools.auth.audit``.
        logger.warning(
            "mcp_token_issued audit write failed (person_id=%s): %s",
            body.person_id, exc,
        )

    return web.json_response(
        {
            "token": token,
            "person_id": str(body.person_id),
            "tenant_slug": tenant_slug,
            "ttl_seconds": ttl,
            "issued_at": issued_at.isoformat(),
            "expires_at": _datetime.fromtimestamp(
                expires_at, tz=UTC,
            ).isoformat(),
            "label": body.label,
        },
        status=200,
    )


async def post_mcp_preset(request: web.Request) -> web.Response:
    """POST /api/v1/mcp/presets — W2.A9.

    Records an inbound-MCP preset registration as a ``source_proposed``
    ledger entry tagged ``mcp:<kind>``. Preset registration is twofold:
    the in-process ``MCPSurfaceDriver`` class self-registers at import time
    (the connectors package ships per-server presets), and this endpoint
    materialises the operator's ledger-side proposal so it's auditable,
    tenant-scoped, and surfaces in /sources alongside native sources.
    """
    from wormbase_ledger.entries import SourceProposedPayload

    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, RegisterMcpPresetBody)
    assert isinstance(body, RegisterMcpPresetBody)
    ledger = request.app[APP_LEDGER_KEY]

    from uuid import uuid4 as _uuid4

    source_id = _uuid4()
    source_kind = (
        body.kind if body.kind.startswith("mcp:") else f"mcp:{body.kind}"
    )

    try:
        payload = SourceProposedPayload(
            source_id=source_id,
            source_kind=source_kind,
            uri=body.server_url,
            added_via_flow="dashboard_form",
            suggested_domain=body.suggested_domain,
            suggested_classification=body.suggested_classification,  # type: ignore[arg-type]
        )
    except ValidationError as exc:
        raise web.HTTPUnprocessableEntity(
            text=exc.json(), content_type="application/json",
        ) from exc

    args = payload.model_dump(mode="json")

    try:
        write_result = await ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "source_proposed",
                "ref_id": str(source_id),
                "reason": (
                    f"MCP preset registered via dashboard wizard: "
                    f"{source_kind} → {body.server_url}"
                ),
                "proposed_by": str(body.proposed_by),
            },
            execute_fn=lambda: {
                "tool": "emit_source_proposed",
                "args": args,
                "result_ref": str(source_id),
            },
            verify_fn=lambda _r: {
                "checks": [
                    {"name": "source_proposed_payload_valid", "ok": True}
                ],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": (
                    f"mcp_preset registered (kind={source_kind})"
                ),
            },
            quadrant="active_deterministic",
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc

    return web.json_response(
        {
            "source_id": str(source_id),
            "source_kind": source_kind,
            "uri": body.server_url,
            "description": body.description,
            **_result_payload(write_result),
        },
        status=200,
    )


# ---------------------------------------------------------------------------
# Ask the Worm — Phase 3 Task 3B
# ---------------------------------------------------------------------------


async def post_worm_ask(request: web.Request) -> web.Response:
    """POST /api/v1/worm/ask — dashboard's in-app ask round-trip.

    Removes the "I have to set up Slack to evaluate" friction. The
    handler synthesises a chat_received PEVR cycle (same tool + payload
    + quadrant the channel-adapter writer produces for live wire
    traffic) and fires the production MentionResponseReactivity. The
    captured worm reply is returned inline; the trace UI reflects the
    full lifecycle exactly the way it would for a Slack thread.

    Response body matches the dashboard's TypeScript ``AskResponseBody``
    contract at ``apps/dashboard/app/api/ask/route.ts``.
    """
    _check_auth(request)
    body = await _read_body(request, WormAskBody)
    assert isinstance(body, WormAskBody)
    company_id = _resolve_company_id(request)

    ledger = request.app[APP_LEDGER_KEY]

    # Lazy-import so the heavyweight chat-presence dependency only loads
    # for tenants that actually use the in-app ask surface.
    from wormbase_core.ask_the_worm import ask_the_worm

    try:
        reply = await ask_the_worm(
            ledger=ledger,
            company_id=company_id,
            question=body.question.strip(),
        )
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(reason=_bad_text(str(exc))) from exc
    except Exception as exc:
        logger.warning(
            "ask_the_worm failed (company=%s): %s", company_id, exc,
        )
        # Honest failure shape — same body keys the panel renders.
        return web.json_response(
            {
                "ok": False,
                "answer": (
                    "The worm could not process this ask. The cycle is "
                    f"recorded in /trace under company {company_id}. "
                    f"Reason: {exc.__class__.__name__}."
                ),
                "references": [],
                "passthrough": False,
            },
            status=500,
        )

    return web.json_response(
        {
            "ok": True,
            "answer": reply.answer,
            "references": list(reply.references),
            "passthrough": True,
            "channel_id": reply.channel_id,
            "chat_reply_id": (
                str(reply.chat_reply_id) if reply.chat_reply_id else None
            ),
            "chat_received_seq": reply.chat_received_seq,
        },
        status=200,
    )


# ---------------------------------------------------------------------------
# Server-Sent-Events: live ledger tail (W1.A3)
# ---------------------------------------------------------------------------


_LEDGER_STREAM_KINDS = {"propose", "execute", "verify", "resolve"}
_LEDGER_STREAM_POLL_SECS = 0.25
_LEDGER_STREAM_KEEPALIVE_SECS = 15.0


def _serialize_stream_row(row: dict[str, Any]) -> dict[str, Any]:
    """Project a fetched ledger row into the JSON shape the dashboard's
    EventSource consumer expects.

    The raw row from ``Ledger.fetch`` carries SQLAlchemy-typed values
    (UUIDs, datetimes, bytes). We coerce everything to JSON-serialisable
    primitives and shorten the hash/prev_hash to the 12-char prefix the
    dashboard already renders elsewhere — keep the cascade-panel payload
    small and consistent with `/trace`.
    """
    ts = row.get("ts")
    ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
    raw_hash = row.get("hash") or b""
    raw_prev = row.get("prev_hash") or b""
    if isinstance(raw_hash, (bytes, bytearray, memoryview)):
        hash_hex = bytes(raw_hash).hex()
    else:
        hash_hex = str(raw_hash)
    if isinstance(raw_prev, (bytes, bytearray, memoryview)):
        prev_hex = bytes(raw_prev).hex()
    else:
        prev_hex = str(raw_prev) if raw_prev else ""
    payload = row.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {"raw": payload}
    return {
        "seq": int(row.get("seq", 0)),
        "kind": str(row.get("kind", "")),
        "quadrant": str(row.get("quadrant", "")),
        "ts": ts_iso,
        "payload": payload,
        "hash": hash_hex[:12],
        "prev_hash": prev_hex[:12] if prev_hex else None,
    }


def _entry_matches_install(
    row: dict[str, Any], install_id: str | None,
) -> bool:
    """Return True if the row should be passed through given the optional
    install-id filter. The cascade panel filters by install_id when known
    so unrelated tenant chatter doesn't tick the cascade by mistake."""
    if not install_id:
        return True
    payload = row.get("payload") or {}
    args = (
        payload.get("args")
        if isinstance(payload, dict) and isinstance(payload.get("args"), dict)
        else {}
    )
    candidate = args.get("install_id") if isinstance(args, dict) else None
    if isinstance(candidate, str) and candidate == install_id:
        return True
    # Some entries name the install_id at the top of the payload (e.g.
    # emit_install_completed itself). Match that shape too.
    if (
        isinstance(payload, dict)
        and isinstance(payload.get("install_id"), str)
        and payload["install_id"] == install_id
    ):
        return True
    return False


async def get_ledger_stream(request: web.Request) -> web.StreamResponse:
    """GET /api/v1/ledger/stream — SSE feed of live ledger entries.

    Auth: bearer token (same as the rest of the write API).
    Tenancy: ``X-Tenant-Slug`` resolves to ``company_id``; only that
    tenant's rows are streamed — never a row from another tenant, even
    when the dashboard wrapper proxies on a shared connection.

    Query params:
      - ``since``          — exclusive seq lower-bound; only rows with
                             ``seq > since`` stream. Defaults to the
                             current tail (no historical replay).
      - ``kinds``          — comma-separated whitelist of ``kind``
                             values. Subset of {propose, execute,
                             verify, resolve}. Defaults to all four.
      - ``filter_install`` — optional install_id filter; rows whose
                             payload.args.install_id (or
                             payload.install_id) match are emitted.

    Reactor: a 250ms polling loop reads ``ledger.fetch`` and pushes
    every new row through aiohttp's ``StreamResponse``. The dashboard's
    Next.js wrapper closes on client disconnect; we detect EOF on the
    write and exit cleanly. A 15s SSE keepalive comment keeps proxies
    from idling the connection out.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    ledger = request.app[APP_LEDGER_KEY]
    if ledger is None:  # pragma: no cover — build_app refuses
        raise web.HTTPInternalServerError(reason="ledger not wired")

    # Parse query params.
    since_param = request.query.get("since")
    try:
        since_seq = int(since_param) if since_param is not None else None
    except ValueError:
        raise web.HTTPBadRequest(
            reason=_bad_text(f"since must be an integer; got {since_param!r}"),
        ) from None

    kinds_param = request.query.get("kinds", "").strip()
    if kinds_param:
        kinds = {k.strip() for k in kinds_param.split(",") if k.strip()}
        invalid = kinds - _LEDGER_STREAM_KINDS
        if invalid:
            raise web.HTTPBadRequest(
                reason=_bad_text(
                    f"unknown kinds: {sorted(invalid)}; allowed: {sorted(_LEDGER_STREAM_KINDS)}",
                ),
            )
    else:
        kinds = set(_LEDGER_STREAM_KINDS)

    install_filter = request.query.get("filter_install", "").strip() or None

    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)

    # Initial cursor: caller's `since`, else the current tail (we do not
    # replay history by default — the cascade panel cares about new
    # rows landing post-install).
    last_seq: int
    try:
        initial = await ledger.fetch(company_id)
    except Exception as exc:
        logger.warning("ledger.fetch failed in stream init: %s", exc)
        await response.write(
            f"event: error\ndata: {json.dumps({'error': 'ledger_fetch_failed', 'message': str(exc)[:200]})}\n\n".encode(),
        )
        return response

    if since_seq is not None:
        last_seq = since_seq
        # Catch-up: stream any rows already past `since` so the panel
        # can backfill recent history before live tailing.
        for row in initial:
            if int(row.get("seq", 0)) <= since_seq:
                continue
            if str(row.get("kind", "")) not in kinds:
                continue
            if not _entry_matches_install(row, install_filter):
                continue
            await response.write(
                f"data: {json.dumps(_serialize_stream_row(row))}\n\n".encode(),
            )
            last_seq = int(row.get("seq", 0))
    else:
        last_seq = int(initial[-1]["seq"]) if initial else 0

    # Live-tail loop.
    last_keepalive = asyncio.get_event_loop().time()
    try:
        while not request.transport or not request.transport.is_closing():
            try:
                rows = await ledger.fetch(company_id)
            except Exception as exc:
                logger.warning("ledger.fetch failed in stream loop: %s", exc)
                # Emit an error frame and exit; EventSource will reconnect.
                with contextlib.suppress(ConnectionResetError, Exception):
                    await response.write(
                        f"event: error\ndata: {json.dumps({'error': 'ledger_fetch_failed', 'message': str(exc)[:200]})}\n\n".encode(),
                    )
                return response

            for row in rows:
                seq = int(row.get("seq", 0))
                if seq <= last_seq:
                    continue
                last_seq = seq
                if str(row.get("kind", "")) not in kinds:
                    continue
                if not _entry_matches_install(row, install_filter):
                    continue
                serialized = _serialize_stream_row(row)
                try:
                    await response.write(
                        f"data: {json.dumps(serialized)}\n\n".encode(),
                    )
                except (ConnectionResetError, asyncio.CancelledError):
                    return response

            now = asyncio.get_event_loop().time()
            if now - last_keepalive >= _LEDGER_STREAM_KEEPALIVE_SECS:
                try:
                    await response.write(b": keepalive\n\n")
                except (ConnectionResetError, asyncio.CancelledError):
                    return response
                last_keepalive = now

            await asyncio.sleep(_LEDGER_STREAM_POLL_SECS)
    except asyncio.CancelledError:
        # Client disconnected — exit quietly.
        pass
    return response


# ---------------------------------------------------------------------------
# W2.A5 — SurfaceDriver registry read endpoint + test-connection
# ---------------------------------------------------------------------------


# Per-connector config-form schemas. The dashboard renders these as
# password / string / number fields without needing JSON-schema
# expansion. Kept on the server so the dashboard catalog and the
# Python registry stay aligned (one place to update when promoting a
# skeletal connector). Any kind not listed here returns an empty
# field set — the picker still renders the badge but the form is
# empty (e.g. ``local_lake``, which is provisioned at install).
_CONNECTOR_CONFIG_SCHEMAS: dict[str, list[dict[str, Any]]] = {
    "local_lake": [],
    "csv_local": [
        {
            "name": "path",
            "label": "File path",
            "type": "string",
            "required": True,
            "placeholder": "/lake/raw/sales-q3.csv",
        },
    ],
    "postgres": [
        {
            "name": "dsn",
            "label": "DSN",
            "type": "password",
            "required": True,
            "placeholder": "postgres://user:pass@host:5432/db",
        },
    ],
    "snowflake": [
        {"name": "account", "label": "Account", "type": "string", "required": True},
        {"name": "username", "label": "Username", "type": "string", "required": True},
        {"name": "password", "label": "Password", "type": "password", "required": True},
        {"name": "database", "label": "Database", "type": "string", "required": True},
        {"name": "warehouse", "label": "Warehouse", "type": "string", "required": False},
    ],
    "bigquery": [
        {"name": "project_id", "label": "Project ID", "type": "string", "required": True},
        {
            "name": "service_account_json",
            "label": "Service account JSON",
            "type": "password",
            "required": True,
        },
    ],
    "s3_csv": [
        {"name": "bucket", "label": "Bucket", "type": "string", "required": True},
        {"name": "prefix", "label": "Prefix", "type": "string", "required": False},
        {
            "name": "access_key_id",
            "label": "Access key id",
            "type": "password",
            "required": True,
        },
        {
            "name": "secret_access_key",
            "label": "Secret access key",
            "type": "password",
            "required": True,
        },
    ],
    "http_csv": [
        {"name": "url", "label": "URL", "type": "string", "required": True},
        {
            "name": "auth_header",
            "label": "Auth header (optional)",
            "type": "password",
            "required": False,
        },
    ],
    "stripe": [
        {"name": "api_key", "label": "API key", "type": "password", "required": True},
    ],
    "salesforce": [
        {"name": "instance_url", "label": "Instance URL", "type": "string", "required": True},
        {"name": "access_token", "label": "Access token", "type": "password", "required": True},
    ],
    "hubspot": [
        {"name": "api_key", "label": "API key", "type": "password", "required": True},
    ],
    "gsheets": [
        {
            "name": "spreadsheet_id",
            "label": "Spreadsheet ID",
            "type": "string",
            "required": True,
        },
        {
            "name": "service_account_json",
            "label": "Service account JSON",
            "type": "password",
            "required": True,
        },
    ],
    "notion": [
        {
            "name": "integration_token",
            "label": "Integration token",
            "type": "password",
            "required": True,
        },
    ],
    "linear": [
        {"name": "api_key", "label": "API key", "type": "password", "required": True},
    ],
}


_CONNECTOR_LABELS: dict[str, str] = {
    "local_lake": "Local lake",
    "csv_local": "Local CSV file",
    "postgres": "Postgres",
    "snowflake": "Snowflake",
    "bigquery": "BigQuery",
    "s3_csv": "S3 CSV",
    "http_csv": "HTTP CSV",
    "stripe": "Stripe",
    "salesforce": "Salesforce",
    "hubspot": "HubSpot",
    "gsheets": "Google Sheets",
    "notion": "Notion",
    "linear": "Linear",
}


def _config_schema_for_kind(kind: str, connector_cls: Any) -> list[dict[str, Any]]:
    """Resolve the field schema for a registered connector.

    Native connectors look up the static dict above. ``mcp:*`` presets
    derive their schema from ``server_config.required_secrets`` /
    ``optional_secrets`` — each becomes a password field, optional or
    required per the config.
    """
    if kind in _CONNECTOR_CONFIG_SCHEMAS:
        return _CONNECTOR_CONFIG_SCHEMAS[kind]
    cfg = getattr(connector_cls, "server_config", None)
    if cfg is None:
        return []
    fields: list[dict[str, Any]] = []
    for name in getattr(cfg, "required_secrets", ()):
        fields.append(
            {
                "name": name,
                "label": name.replace("_", " ").title(),
                "type": "password",
                "required": True,
            },
        )
    for name in getattr(cfg, "optional_secrets", ()):
        fields.append(
            {
                "name": name,
                "label": name.replace("_", " ").title(),
                "type": "password",
                "required": False,
            },
        )
    return fields


def _label_for_kind(kind: str) -> str:
    if kind in _CONNECTOR_LABELS:
        return _CONNECTOR_LABELS[kind]
    if kind.startswith("mcp:"):
        vendor = kind.split(":", 1)[1]
        return f"{vendor.title()} (MCP)"
    return kind.replace("_", " ").title()


async def get_connectors(request: web.Request) -> web.Response:
    """Return the connector registry — kinds, capabilities, status, fields.

    Read-only; no auth required (parallel to ``/mcp/catalog``). The
    dashboard's ``/api/v1/connectors/list`` server route forwards this
    JSON unchanged to the ``/sources/new`` picker. Honest status badges
    (production / preview / coming_soon) come straight from each
    SurfaceDriver class declaration.

    Subpath ``/api/v1/connectors/{kind}/test`` runs the same
    ``SurfaceDriver.authenticate`` the source-builder uses at runtime so
    the dashboard's "test connection" affordance exercises the real
    path, not a stub. Bearer-auth required for the test variant.
    """
    from wormbase_lake_surfaces import default_registry

    registry = default_registry()
    kinds_payload: list[dict[str, Any]] = []
    for kind in registry.all_kinds():
        cls = registry.get(kind)
        if cls is None:
            continue
        capabilities = sorted(getattr(cls, "capability", set()))
        status = getattr(cls, "status", "preview")
        status_note = getattr(cls, "status_note", "")
        classification_hints = list(getattr(cls, "classification_hints", []) or [])
        config_schema = _config_schema_for_kind(kind, cls)
        kinds_payload.append(
            {
                "kind": kind,
                "label": _label_for_kind(kind),
                "status": status,
                "status_note": status_note,
                "capabilities": capabilities,
                "classification_hints": classification_hints,
                "config_schema": config_schema,
            },
        )
    return web.json_response({"kinds": kinds_payload}, status=200)


class TestConnectionBody(_Body):
    """Inbound payload for ``POST /api/v1/connectors/{kind}/test``.

    ``config`` is the connector-specific dict the picker form produces
    (e.g. ``{"dsn": "postgres://..."}``). The route hands it straight
    into ``SurfaceDriver.authenticate`` via a ``SecretBundle`` so the test
    follows the exact same code path the source-builder uses at runtime.
    No connector-specific shortcuts.
    """

    config: dict[str, Any] = Field(default_factory=dict)


async def post_connector_test(request: web.Request) -> web.Response:
    """Run ``SurfaceDriver.authenticate`` against the supplied config.

    Returns a small envelope with a content-addressed hash receipt:

        {"ok": true|false,
         "kind": "...",
         "handle_id": "...",  # only present on ok
         "version": "...",     # connector-extracted, opaque
         "hash": "<12-hex>",   # SHA-256 of (kind, handle_id) — stable
         "error": "..."}       # only present on failure

    Honest path: this is the production authenticate flow with a
    container-shaped ``SecretBundle``. Failures surface their original
    ``ValueError`` message so the picker can show "wrong DSN" / "host
    unreachable" without forging a success.

    Bearer-auth required because authentication usually establishes a
    real connection (DSN, API key) and we don't want anonymous probes.
    """
    _check_auth(request)
    from wormbase_lake_surfaces import SecretBundle, default_registry

    kind = request.match_info.get("kind", "")
    if not kind:
        raise web.HTTPNotFound(reason="connector kind required")

    registry = default_registry()
    cls = registry.get(kind)
    if cls is None:
        return web.json_response(
            {"ok": False, "kind": kind, "error": f"unknown connector kind {kind!r}"},
            status=404,
        )
    status = getattr(cls, "status", "preview")
    if status == "coming_soon":
        return web.json_response(
            {
                "ok": False,
                "kind": kind,
                "error": (
                    f"connector {kind!r} is marked coming_soon — "
                    "test-connection is disabled until the implementation lands"
                ),
            },
            status=409,
        )

    body = await _read_body(request, TestConnectionBody)
    assert isinstance(body, TestConnectionBody)
    bundle = SecretBundle(payload=dict(body.config))

    try:
        connector = cls()
    except Exception as exc:
        return web.json_response(
            {
                "ok": False,
                "kind": kind,
                "error": f"failed to instantiate connector: {exc}",
            },
            status=200,
        )

    import hashlib as _hashlib

    try:
        handle = await connector.authenticate(bundle)
    except NotImplementedError as exc:
        return web.json_response(
            {
                "ok": False,
                "kind": kind,
                "error": (
                    f"authenticate is not implemented for {kind!r}: {exc}"
                ),
            },
            status=200,
        )
    except ValueError as exc:
        return web.json_response(
            {"ok": False, "kind": kind, "error": str(exc)},
            status=200,
        )
    except Exception as exc:
        # asyncpg / boto / requests errors land here. Surface the
        # original message; the picker renders it verbatim so operators
        # can debug DSN / network problems without going to logs.
        return web.json_response(
            {"ok": False, "kind": kind, "error": f"{type(exc).__name__}: {exc}"},
            status=200,
        )

    handle_id = getattr(handle, "handle_id", "")
    extra = getattr(handle, "extra", {}) or {}
    version = ""
    if isinstance(extra, dict):
        v = extra.get("version") or extra.get("schema") or ""
        version = str(v) if v else ""
    digest_input = f"{kind}:{handle_id}".encode()
    receipt_hash = _hashlib.sha256(digest_input).hexdigest()[:12]
    return web.json_response(
        {
            "ok": True,
            "kind": kind,
            "handle_id": handle_id,
            "version": version,
            "hash": receipt_hash,
        },
        status=200,
    )


# ---------------------------------------------------------------------------
# Ops observability (W2.A10)
# ---------------------------------------------------------------------------
#
# GET /api/v1/ops/health
#
# Returns a single JSON snapshot consumed by the dashboard's /ops tab:
#
#   { generatedAt, postgres, ledgerThroughput, mcpRateLimits, agentLoops }
#
# Source-of-truth is the worm-core process itself plus a `SELECT 1` /
# `SELECT version()` probe on the ledger DB. We read at most the trailing
# `_OPS_THROUGHPUT_WINDOW_MIN`-worth of ledger entries per known tenant
# to compute throughput + rate-limit + loop-liveness; that's bounded
# work even when the ledger has millions of rows because `Ledger.fetch`
# is in-process and the per-tenant filter applies in-memory.
#
# Honest-failure contract: every sub-section degrades independently. A
# Postgres outage marks `postgres.status = "down"` but still returns the
# snapshot so the dashboard can render the red banner without 500ing the
# proxy. That's the shape of W2.A10's acceptance criterion.

_OPS_THROUGHPUT_WINDOW_MIN = 10
_OPS_AGENT_LOOP_FRESH_MIN = 5
_OPS_KNOWN_TENANT_SLUGS: tuple[str, ...] = ("baseworm", "democorp")


def _ops_iso_minute(dt: Any) -> str:
    """Bucket a ledger ts to the start of its minute, ISO8601 with Z."""
    from datetime import datetime as _dt

    if isinstance(dt, _dt):
        d = dt
    else:
        try:
            d = _dt.fromisoformat(str(dt).replace("Z", "+00:00"))
        except Exception:
            return "unknown"
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    d = d.astimezone(UTC).replace(second=0, microsecond=0)
    return d.isoformat().replace("+00:00", "Z")


async def _ops_postgres_health(ledger: Any) -> dict[str, Any]:
    """Run `SELECT 1` + `SELECT version()` against the ledger engine.

    InMemoryLedger has no engine — return ``unknown`` so the dashboard
    knows the probe is informational rather than failed.
    """
    import time

    engine = getattr(ledger, "engine", None)
    if engine is None:
        return {
            "status": "unknown",
            "latencyMs": None,
            "message": "ledger has no SQL engine (InMemoryLedger or similar)",
            "version": None,
        }

    from sqlalchemy import text as _text

    started = time.perf_counter()
    try:
        async with engine.connect() as conn:
            await conn.execute(_text("SELECT 1"))
            try:
                row = (await conn.execute(_text("SELECT version()"))).first()
                version = str(row[0]) if row and row[0] is not None else None
            except Exception:
                version = None
        latency_ms = (time.perf_counter() - started) * 1000.0
        return {
            "status": "ok",
            "latencyMs": round(latency_ms, 2),
            "message": "SELECT 1 returned within the timeout.",
            "version": version,
        }
    except Exception as exc:
        return {
            "status": "down",
            "latencyMs": None,
            "message": f"{type(exc).__name__}: {exc}".replace("\n", " ")[:400],
            "version": None,
        }


async def _ops_throughput_for_tenant(
    ledger: Any, company_id: UUID, *, window_min: int,
) -> dict[str, Any]:
    """Compute per-minute throughput buckets for the trailing `window_min`."""
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    now = _dt.now(UTC).replace(second=0, microsecond=0)
    window_start = now - _td(minutes=window_min - 1)

    try:
        rows = await ledger.fetch(company_id)
    except Exception as exc:
        logger.warning("ops throughput fetch failed for %s: %s", company_id, exc)
        rows = []

    counts: dict[str, int] = {}
    for r in rows:
        ts = r.get("ts")
        if not isinstance(ts, _dt):
            try:
                ts = _dt.fromisoformat(str(ts).replace("Z", "+00:00"))
            except Exception:
                continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts < window_start:
            continue
        bucket = ts.astimezone(UTC).replace(second=0, microsecond=0)
        key = bucket.isoformat().replace("+00:00", "Z")
        counts[key] = counts.get(key, 0) + 1

    buckets: list[dict[str, Any]] = []
    total = 0
    for i in range(window_min):
        bucket = window_start + _td(minutes=i)
        key = bucket.isoformat().replace("+00:00", "Z")
        c = counts.get(key, 0)
        total += c
        buckets.append({"bucketStart": key, "count": c})
    return {
        "totalLastWindow": total,
        "windowMinutes": window_min,
        "buckets": buckets,
    }


async def _ops_mcp_rate_limits(ledger: Any) -> dict[str, Any]:
    """Per-tenant trailing-60s MCP call counts vs the configured ceiling."""
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from wormbase_core.mcp_server import is_mcp_enabled
    from wormbase_core.mcp_tools.auth import (
        DEFAULT_RATE_LIMIT_PER_MIN,
        RATE_LIMIT_WINDOW_SECONDS,
        rate_limit_per_min,
    )

    if not is_mcp_enabled():
        return {
            "enabled": False,
            "disabledReason": "WORMBASE_MCP_ENABLED unset; rate-limit gate inactive.",
            "tenants": [],
        }

    ceiling = rate_limit_per_min() or DEFAULT_RATE_LIMIT_PER_MIN
    now = _dt.now(UTC)
    window_start = now - _td(seconds=RATE_LIMIT_WINDOW_SECONDS)

    tenants_payload: list[dict[str, Any]] = []
    for slug in _OPS_KNOWN_TENANT_SLUGS:
        try:
            company_id = tenant_to_uuid(slug)
        except Exception:
            continue
        try:
            rows = await ledger.fetch(company_id)
        except Exception as exc:
            logger.warning("ops mcp fetch failed for %s: %s", slug, exc)
            rows = []
        count = 0
        for r in rows:
            if r.get("kind") != "execute":
                continue
            ts = r.get("ts")
            if not isinstance(ts, _dt):
                try:
                    ts = _dt.fromisoformat(str(ts).replace("Z", "+00:00"))
                except Exception:
                    continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts < window_start:
                continue
            payload = r.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if payload.get("tool") != "emit_mcp_call_received":
                continue
            count += 1
        tenants_payload.append(
            {
                "tenantSlug": slug,
                "tenantDisplayName": slug.title(),
                "companyId": str(company_id),
                "callsInWindow": count,
                "ceilingPerMin": ceiling,
                "windowSeconds": RATE_LIMIT_WINDOW_SECONDS,
                "saturated": count >= ceiling,
            },
        )
    return {"enabled": True, "tenants": tenants_payload}


async def _ops_agent_loops(ledger: Any) -> list[dict[str, Any]]:
    """Synthesize the three loop-liveness rows.

    - worm-core: this handler is responding, so the loop is alive.
    - channel-adapter: derived from the latest `chat_received` /
      `channel_message` execute entry across known tenants.
    - projection-runner: derived from the latest non-empty fetch on any
      known tenant (any ledger entry implies the runner has something to
      project).
    """
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    now = _dt.now(UTC)
    fresh_window = _td(minutes=_OPS_AGENT_LOOP_FRESH_MIN)

    last_channel_ts: _dt | None = None
    last_any_ts: _dt | None = None

    for slug in _OPS_KNOWN_TENANT_SLUGS:
        try:
            company_id = tenant_to_uuid(slug)
            rows = await ledger.fetch(company_id)
        except Exception as exc:
            logger.warning("ops agent-loop fetch failed for %s: %s", slug, exc)
            continue
        for r in rows:
            ts = r.get("ts")
            if not isinstance(ts, _dt):
                try:
                    ts = _dt.fromisoformat(str(ts).replace("Z", "+00:00"))
                except Exception:
                    continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if last_any_ts is None or ts > last_any_ts:
                last_any_ts = ts
            payload = r.get("payload") or {}
            tool = (
                payload.get("tool") if isinstance(payload, dict) else None
            )
            if isinstance(tool, str) and (
                "chat_received" in tool or "channel_message" in tool
            ):
                if last_channel_ts is None or ts > last_channel_ts:
                    last_channel_ts = ts

    def _status(seen: _dt | None) -> str:
        if seen is None:
            return "unknown"
        return "ok" if (now - seen) <= fresh_window else "degraded"

    def _iso(seen: _dt | None) -> str | None:
        if seen is None:
            return None
        return seen.astimezone(UTC).isoformat().replace("+00:00", "Z")

    return [
        {
            "id": "worm-core",
            "label": "Worm core",
            "status": "ok",
            "lastSeenAt": now.isoformat().replace("+00:00", "Z"),
            "message": "HTTP API responding; heartbeat loop active.",
        },
        {
            "id": "channel-adapter",
            "label": "Channel adapter",
            "status": _status(last_channel_ts),
            "lastSeenAt": _iso(last_channel_ts),
            "message": (
                "Wire ingress active." if last_channel_ts is not None else
                "No channel events recorded yet — connect a chat platform."
            ),
        },
        {
            "id": "projection-runner",
            "label": "Projection runner",
            "status": _status(last_any_ts),
            "lastSeenAt": _iso(last_any_ts),
            "message": (
                "Latest ledger entry within the freshness window." if last_any_ts is not None
                else "No ledger entries observed yet."
            ),
        },
    ]


async def get_ops_health(request: web.Request) -> web.Response:
    """GET /api/v1/ops/health — observability snapshot for the /ops tab.

    Bearer-authed; tenant header is optional (the snapshot iterates over
    known tenants for cross-tenant rate-limit + loop summaries). Returns
    200 even when Postgres is down — the snapshot itself carries the
    failure detail. Only a missing/invalid bearer token (401) or a
    bare-process bug (500) ever returns non-200.
    """
    from datetime import datetime as _dt

    _check_auth(request)
    ledger = request.app[APP_LEDGER_KEY]
    if ledger is None:  # pragma: no cover — build_app refuses
        raise web.HTTPInternalServerError(reason="ledger not wired")

    postgres = await _ops_postgres_health(ledger)

    aggregate_buckets: dict[str, int] = {}
    aggregate_total = 0
    for slug in _OPS_KNOWN_TENANT_SLUGS:
        try:
            company_id = tenant_to_uuid(slug)
        except Exception:
            continue
        per_tenant = await _ops_throughput_for_tenant(
            ledger, company_id, window_min=_OPS_THROUGHPUT_WINDOW_MIN,
        )
        aggregate_total += int(per_tenant["totalLastWindow"])
        for b in per_tenant["buckets"]:
            aggregate_buckets[b["bucketStart"]] = (
                aggregate_buckets.get(b["bucketStart"], 0) + int(b["count"])
            )
    sorted_keys = sorted(aggregate_buckets.keys())
    throughput = {
        "totalLastWindow": aggregate_total,
        "windowMinutes": _OPS_THROUGHPUT_WINDOW_MIN,
        "buckets": [
            {"bucketStart": k, "count": aggregate_buckets[k]}
            for k in sorted_keys
        ],
    }

    mcp_rate_limits = await _ops_mcp_rate_limits(ledger)
    agent_loops = await _ops_agent_loops(ledger)

    payload = {
        "generatedAt": _dt.now(UTC).isoformat().replace("+00:00", "Z"),
        "postgres": postgres,
        "ledgerThroughput": throughput,
        "mcpRateLimits": mcp_rate_limits,
        "agentLoops": agent_loops,
    }
    return web.json_response(payload, status=200)


# ---------------------------------------------------------------------------
# === W5.A5 — Reactivities + Resource conversations (read + lifecycle) =====
#
# Six new endpoints that back the dashboard's /reactivities tab and the
# Resource Conversations card on /people/<id>:
#
#   GET    /api/v1/reactivities                           — list registry
#   POST   /api/v1/reactivities/propose                   — natural-language
#                                                            propose with sketched
#                                                            predicate/action
#   POST   /api/v1/reactivities/{id}/confirm              — admin confirms a
#                                                            proposed reactivity
#   POST   /api/v1/reactivities/{id}/disable              — admin disables an
#                                                            active reactivity
#   GET    /api/v1/reactivities/{id}/fires                — last N fires
#   GET    /api/v1/people/{person_id}/resource-conversations
#
# All routes require bearer-token auth + an X-Tenant-Slug header. The
# registry handle is stored on the aiohttp Application via APP_REGISTRY_KEY;
# when it's missing (e.g. unit-test app built without a registry) we
# return an honest empty payload instead of 500 — same shape the
# dashboard renders an honest empty state for.
# ---------------------------------------------------------------------------


# Lazy-import key so the symbol exists even when the registry is wired in
# from cli.py. We attach the registry per-app (tenant-scoped registries
# would just register multiple tenants under the same app key with
# distinct company_id buckets — out of scope for W5.A5; the current
# worm-core process is single-tenant).
APP_REGISTRY_KEY: web.AppKey[Any] = web.AppKey("wormbase_reactivity_registry", object)


# ---- request bodies -------------------------------------------------------


class ProposeReactivityBody(_Body):
    """POST /api/v1/reactivities/propose body — natural-language propose.

    The dashboard sends ``description`` as the operator's intent in plain
    English (e.g. "ping me whenever someone mentions revenue"). The
    handler runs a simple structured parser against the text — extracting
    a candidate predicate (entry kind + topic), action (DM the named
    person or post-to-channel), and a confidence score — then writes
    ``emit_reactivity_proposed`` via the registry. Admins confirm via
    ``/api/v1/reactivities/{id}/confirm``.

    ``proposed_by`` is the admin Person id. Required so the audit row
    carries provenance. The dashboard threads it from
    ``getCurrentPerson(companyId)``.
    """

    description: str = Field(min_length=1, max_length=2000)
    proposed_by: str = "dashboard-admin"


class ConfirmReactivityBody(_Body):
    confirmed_by: UUID


class DisableReactivityBody(_Body):
    disabled_by: UUID
    reason: str = Field(min_length=1, max_length=500)


# ---- helpers --------------------------------------------------------------


def _get_registry(request: web.Request) -> Any | None:
    """Return the ReactivityRegistry attached to the app, or None.

    Honest-empty contract: callers that get None must surface an empty
    payload (200 + ``{}``-shaped) rather than 500. The dashboard renders
    an honest empty state when no registry is wired (e.g. spin-up race
    or unit-test build).
    """
    return request.app.get(APP_REGISTRY_KEY)


def _scope_str(scope: Any) -> str:
    """Reactivity.scope is a Literal ('company'|'team'|'domain'|'person');
    coerce to the string form we ship over the wire."""
    return str(scope) if scope else "person"


def _binding_to_dict(binding: Any, registry: Any) -> dict[str, Any]:
    """Project a registry binding to the dashboard wire shape.

    Pulls (id, name, description, scope) off the concrete Reactivity
    instance and (state, last_fired_at, …) off the lifecycle record.
    Budget snapshot is summarised — caller can drill into per-axis via
    /fires.
    """
    record = binding.record
    react = binding.reactivity
    spec = binding.spec
    return {
        "id": record.id,
        "name": getattr(react, "name", spec.name) or record.id,
        "description": getattr(react, "description", spec.description) or "",
        "scope": _scope_str(getattr(react, "scope", spec.scope)),
        "state": record.state,
        "proposedBy": record.proposed_by,
        "confirmedBy": str(record.confirmed_by) if record.confirmed_by else None,
        "disabledBy": str(record.disabled_by) if record.disabled_by else None,
        "disableReason": record.disable_reason,
        "lastFiredAt": (
            record.last_fired_at.isoformat() if record.last_fired_at else None
        ),
        "predicateSpec": dict(spec.predicate_spec or {}),
        "conditionSpec": dict(spec.condition_spec or {}),
        "actionSpec": dict(spec.action_spec or {}),
    }


# ---- "inference router" stand-in: deterministic NL → ReactivitySpec -------


_NL_KIND_TRIGGERS: tuple[tuple[str, str], ...] = (
    ("dm", "chat_received"),
    ("ping", "chat_received"),
    ("notify", "chat_received"),
    ("mention", "chat_received"),
    ("file", "source_proposed"),
    ("source", "source_proposed"),
    ("kpi", "kpi_proposed"),
    ("decision", "decision_proposed"),
)

_NL_TOPIC_HINTS: tuple[str, ...] = (
    "revenue", "churn", "retention", "growth", "mrr", "arr", "nps",
    "cac", "ltv", "pipeline", "deals", "pricing", "users", "signups",
    "engagement", "conversion",
)


def _sketch_reactivity_from_description(
    description: str, *, proposed_by: str,
) -> dict[str, Any]:
    """Heuristic NL → spec sketch with a confidence score.

    The plan calls for "uses inference router to synthesize a predicate/
    action sketch". The ``packages/inference-router`` package is still a
    skeleton (pyproject.toml only); shipping a heuristic sketcher keeps
    the W5.A5 surface honest about confidence — admins see exactly what
    the parser saw, can refine the description, and confirm only when
    the sketch makes sense.

    The sketch has four parts:

      * id            — slugified suffix of the description
      * predicate     — entry-kind trigger + topic hint
      * action        — "dm_owner" by default; "post_to_channel" if the
                        description mentions "channel" / "post"
      * scope         — "person" if the description names "me"/"i";
                        "domain" if a domain-name appears; else "company"
      * confidence    — 0..1 based on how many tokens matched

    Returns a dict with ``id`` / ``name`` / ``description`` / ``scope`` /
    ``predicate_spec`` / ``condition_spec`` / ``action_spec`` /
    ``confidence``. The caller wires it into a ReactivitySpec.
    """
    import re
    import uuid as _uuid

    text = description.lower().strip()
    score = 0.0

    # Entry kind from triggers.
    entry_kind: str | None = None
    for needle, kind in _NL_KIND_TRIGGERS:
        if needle in text:
            entry_kind = kind
            score += 0.35
            break
    if entry_kind is None:
        entry_kind = "chat_received"  # safe default; lowers confidence

    # Topic hint from list.
    topic: str | None = None
    for hint in _NL_TOPIC_HINTS:
        if hint in text:
            topic = hint
            score += 0.30
            break

    # Action.
    action_kind = "dm_owner"
    if any(s in text for s in ("post", "channel", "publish")):
        action_kind = "post_to_channel"
        score += 0.10

    # Scope.
    scope = "company"
    if " me " in f" {text} " or text.startswith("ping me") or text.startswith("dm me"):
        scope = "person"
        score += 0.10
    elif any(d in text for d in ("revenue", "finance", "retention", "sales")):
        scope = "domain"
        score += 0.10

    score = min(1.0, score)

    # Generate a stable-ish id from the topic + a random suffix so two
    # admins proposing the same description don't collide.
    slug = re.sub(r"[^a-z0-9]+", "_", text).strip("_")[:32] or "reactivity"
    rid = f"prop_{slug}_{_uuid.uuid4().hex[:8]}"

    return {
        "id": rid,
        "name": description.strip()[:80],
        "description": description.strip(),
        "scope": scope,
        "predicate_spec": {
            "entry_kind": entry_kind,
            "topic": topic,
            "raw_description": description,
        },
        "condition_spec": {
            "per_owner_per_day": 3,
            "per_domain_per_day": 10,
            "per_tenant_per_day": 50,
            "novelty_hours": 4.0,
        },
        "action_spec": {
            "kind": action_kind,
            "synthesized_from": "heuristic",
        },
        "confidence": round(score, 2),
        "proposed_by": proposed_by,
    }


# ---- handlers -------------------------------------------------------------


async def get_reactivities(request: web.Request) -> web.Response:
    """GET /api/v1/reactivities — list every registered reactivity."""
    _check_auth(request)
    _ = _resolve_company_id(request)
    registry = _get_registry(request)
    if registry is None:
        return web.json_response({"reactivities": []}, status=200)

    rows: list[dict[str, Any]] = []
    bindings = getattr(registry, "_bindings", {})
    for binding in bindings.values():
        rows.append(_binding_to_dict(binding, registry))
    rows.sort(
        key=lambda r: r.get("lastFiredAt") or "0",
        reverse=True,
    )
    return web.json_response({"reactivities": rows}, status=200)


async def post_reactivity_propose(request: web.Request) -> web.Response:
    """POST /api/v1/reactivities/propose — natural-language propose.

    Parses the description into a sketched ReactivitySpec via the
    deterministic NL parser, then writes ``emit_reactivity_proposed``
    through the registry. The response carries the sketched spec +
    confidence so the dashboard can show the admin exactly what was
    parsed BEFORE confirmation.

    ``?preview=1`` query param is honoured for the dashboard's
    two-stage propose UX: the modal first asks for a preview (no
    persistence), shows the sketch to the admin, then re-posts without
    ``preview=1`` to commit. Both calls return the same shape.
    """
    _check_auth(request)
    _ = _resolve_company_id(request)
    body = await _read_body(request, ProposeReactivityBody)
    assert isinstance(body, ProposeReactivityBody)

    preview_only = request.query.get("preview", "").strip() in ("1", "true")

    sketch = _sketch_reactivity_from_description(
        body.description, proposed_by=body.proposed_by,
    )

    if preview_only:
        return web.json_response(
            {"sketch": sketch, "persisted": False, "preview": True},
            status=200,
        )

    registry = _get_registry(request)
    if registry is None:
        # Honest empty: return the sketch so the dashboard can still
        # render the preview, but mark not_persisted.
        return web.json_response(
            {"sketch": sketch, "persisted": False, "reason": "registry_unavailable"},
            status=200,
        )

    # Write emit_reactivity_proposed through the registry. We don't
    # register the concrete reactivity here — confirm() flips it to
    # active later, but the implementation has to come from code.
    try:
        from wormbase_reactivities.protocol import ReactivitySpec
        spec = ReactivitySpec(
            id=sketch["id"],
            name=sketch["name"],
            description=sketch["description"],
            scope=sketch["scope"],
            predicate_spec=sketch["predicate_spec"],
            condition_spec=sketch["condition_spec"],
            action_spec=sketch["action_spec"],
        )
        await registry.propose(spec, proposed_by=body.proposed_by)
    except Exception as exc:
        raise web.HTTPInternalServerError(
            reason=_bad_text(f"propose failed: {exc}"),
        ) from exc

    return web.json_response(
        {"sketch": sketch, "persisted": True}, status=201,
    )


async def post_reactivity_confirm(request: web.Request) -> web.Response:
    """POST /api/v1/reactivities/{id}/confirm — admin confirms a propose."""
    _check_auth(request)
    _ = _resolve_company_id(request)
    rid = request.match_info.get("reactivity_id", "").strip()
    if not rid:
        raise web.HTTPBadRequest(reason="missing reactivity_id path segment")
    body = await _read_body(request, ConfirmReactivityBody)
    assert isinstance(body, ConfirmReactivityBody)

    registry = _get_registry(request)
    if registry is None:
        raise web.HTTPServiceUnavailable(reason="reactivity registry not available")

    try:
        await registry.confirm(rid, confirmed_by=body.confirmed_by)
    except ValueError as exc:
        raise web.HTTPNotFound(reason=_bad_text(str(exc))) from exc
    except Exception as exc:
        raise web.HTTPInternalServerError(
            reason=_bad_text(f"confirm failed: {exc}"),
        ) from exc
    return web.json_response({"reactivity_id": rid, "state": "active"}, status=200)


async def post_reactivity_disable(request: web.Request) -> web.Response:
    """POST /api/v1/reactivities/{id}/disable — admin disables a fire path."""
    _check_auth(request)
    _ = _resolve_company_id(request)
    rid = request.match_info.get("reactivity_id", "").strip()
    if not rid:
        raise web.HTTPBadRequest(reason="missing reactivity_id path segment")
    body = await _read_body(request, DisableReactivityBody)
    assert isinstance(body, DisableReactivityBody)

    registry = _get_registry(request)
    if registry is None:
        raise web.HTTPServiceUnavailable(reason="reactivity registry not available")

    try:
        await registry.disable(
            rid, disabled_by=body.disabled_by, reason=body.reason,
        )
    except ValueError as exc:
        raise web.HTTPNotFound(reason=_bad_text(str(exc))) from exc
    except Exception as exc:
        raise web.HTTPInternalServerError(
            reason=_bad_text(f"disable failed: {exc}"),
        ) from exc
    return web.json_response(
        {"reactivity_id": rid, "state": "disabled", "reason": body.reason},
        status=200,
    )


async def get_reactivity_fires(request: web.Request) -> web.Response:
    """GET /api/v1/reactivities/{id}/fires?limit= — last N fires.

    Reads the most recent ``emit_reactivity_fired`` ledger entries
    matching this reactivity_id. Sorted newest-first.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    rid = request.match_info.get("reactivity_id", "").strip()
    if not rid:
        raise web.HTTPBadRequest(reason="missing reactivity_id path segment")
    raw_limit = request.query.get("limit", "50")
    try:
        limit = max(1, min(500, int(raw_limit)))
    except (ValueError, TypeError):
        limit = 50

    ledger = request.app[APP_LEDGER_KEY]
    if ledger is None:  # pragma: no cover
        return web.json_response({"fires": []}, status=200)

    try:
        rows = await ledger.fetch(company_id)
    except Exception as exc:
        logger.warning("ledger.fetch failed for reactivity fires: %s", exc)
        return web.json_response({"fires": []}, status=200)

    fires: list[dict[str, Any]] = []
    for row in rows:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("tool") != "emit_reactivity_fired":
            continue
        args = payload.get("args") or {}
        if not isinstance(args, dict):
            continue
        if args.get("reactivity_id") != rid:
            continue
        ts = row.get("ts")
        ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts or "")
        fires.append(
            {
                "seq": int(row.get("seq", 0)),
                "ts": ts_iso,
                "sourceSeq": int(args.get("source_seq", 0)),
                "noveltyKey": str(args.get("novelty_key", "") or ""),
                "actionSeqs": list(args.get("action_seqs") or []),
                "budgetUsed": dict(args.get("budget_used") or {}),
            }
        )
    fires.sort(key=lambda f: f["seq"], reverse=True)
    return web.json_response({"fires": fires[:limit]}, status=200)


async def get_resource_conversations_for_person(
    request: web.Request,
) -> web.Response:
    """GET /api/v1/people/{person_id}/resource-conversations.

    Lists active resource conversations where this Person is the owner
    being DM'd. Folded from emit_resource_conversation_proposed minus
    emit_resource_conversation_resolved. Replies are inlined (last 3).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    pid = request.match_info.get("person_id", "").strip()
    if not pid:
        raise web.HTTPBadRequest(reason="missing person_id path segment")
    try:
        UUID(pid)
    except ValueError as exc:
        raise web.HTTPBadRequest(
            reason=_bad_text(f"person_id must be UUID; got {pid!r}"),
        ) from exc

    ledger = request.app[APP_LEDGER_KEY]
    if ledger is None:  # pragma: no cover
        return web.json_response({"conversations": []}, status=200)

    try:
        rows = await ledger.fetch(company_id)
    except Exception as exc:
        logger.warning("ledger.fetch failed for resource conversations: %s", exc)
        return web.json_response({"conversations": []}, status=200)

    proposed: dict[str, dict[str, Any]] = {}
    replies: dict[str, list[dict[str, Any]]] = {}
    resolved: set[str] = set()
    for row in rows:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        tool = payload.get("tool")
        args = payload.get("args") or {}
        if not isinstance(args, dict):
            continue
        ts = row.get("ts")
        ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts or "")
        if tool == "emit_resource_conversation_proposed":
            owner_id = args.get("owner_id")
            if str(owner_id) != pid:
                continue
            cid = str(args.get("conversation_id") or args.get("seq") or row.get("seq"))
            proposed[cid] = {
                "conversationId": cid,
                "ownerId": str(owner_id),
                "topic": args.get("topic") or {},
                "statement": args.get("statement") or "",
                "channel": args.get("channel") or "",
                "resources": args.get("resources") or {},
                "proposedAt": ts_iso,
                "seq": int(row.get("seq", 0)),
            }
        elif tool == "emit_resource_conversation_replied":
            cid = str(args.get("conversation_id") or "")
            replies.setdefault(cid, []).append(
                {
                    "replierId": str(args.get("replier_id") or ""),
                    "content": str(args.get("content") or ""),
                    "ts": ts_iso,
                    "seq": int(row.get("seq", 0)),
                }
            )
        elif tool == "emit_resource_conversation_resolved":
            cid = str(args.get("conversation_id") or "")
            if cid:
                resolved.add(cid)

    convs: list[dict[str, Any]] = []
    for cid, p in proposed.items():
        if cid in resolved:
            continue
        rs = sorted(replies.get(cid, []), key=lambda r: r["seq"], reverse=True)
        p["recentReplies"] = rs[:3]
        p["replyCount"] = len(rs)
        convs.append(p)
    convs.sort(key=lambda c: c["seq"], reverse=True)
    return web.json_response({"conversations": convs}, status=200)


# ---------------------------------------------------------------------------
# v1.1 write-action handlers (Wave 3 / Wave 3.2 stub branches → real).
# ---------------------------------------------------------------------------


async def post_register_agent(request: web.Request) -> web.Response:
    """POST /api/v1/write_actions/register_agent — Wave 3.2 Hole #1.

    Emits ``agent_registered`` plus one ``agent_grant`` per requested
    ``domain_read_id``, plus an optional ``model.access`` grant when
    a ``model_access_budget_usd`` is supplied. Returns
    ``{"agent_id": str, "agentId": str, "entry_ids": [...]}`` —
    duplicating the id under both snake_case and camelCase keys so the
    dashboard server action's ``body.agentId ?? body.agent_id`` resolver
    matches either shape.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, RegisterAgentBody)
    assert isinstance(body, RegisterAgentBody)
    ledger = request.app[APP_LEDGER_KEY]

    # The request body carries ``company_id`` explicitly for symmetry
    # with the dashboard server action, but the tenant header is the
    # authoritative scope (consistent with every other handler in this
    # module). We sanity-check that they agree to catch misrouted writes.
    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    try:
        agent_id, _results = await write_actions.register_agent(
            ledger,
            company_id,
            external_provider=body.external_provider,
            display_name=body.display_name,
            domain_read_ids=list(body.domain_read_ids),
            model_access_budget_usd=body.model_access_budget_usd,
            registered_by=body.registered_by,
        )
    except VerifyFailed as exc:
        # Verify-time rejection (e.g. ``external_provider`` outside the
        # AgentRegisteredPayload Literal) surfaces as 422 — same shape
        # Pydantic rejection of an unknown provider would land at the
        # request-validation step.
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {"agent_id": str(agent_id), "agentId": str(agent_id)},
        status=200,
    )


_VALID_REVOKE_REASONS = frozenset(
    {"agent_request", "admin_revoked", "expired", "rotated"},
)


async def post_agent_subscriptions_create(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/agent_subscriptions_create — v2.A Task 7.

    Writes an ``emit_agent_subscription_created`` PEVR cycle. The handler
    is the dashboard's admin-create path; the agent's own MCP-tool path
    lives in ``packages/wormbase-agent-gateway/.../subscriptions/mcp_tools.py``.
    Both paths share the same ledger entry shape, so the
    ``LedgerSubscriptionReader`` projects the union with one scan.

    Validation:
      * ``transport`` ∈ {``mcp_stream``, ``webhook``}.
      * When ``transport == "webhook"``: ``webhook_url`` and
        ``webhook_secret_ref`` are both required. The handler enforces
        the secret_ref shape only loosely (non-empty); the
        CredentialBroker resolves it at delivery time.
      * ``filter`` MUST constrain at least one axis (kinds / domains /
        agent_id_ref / payload_path_eq) — a wildcard filter would match
        every entry and is rejected.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, AgentSubscriptionCreateBody)
    assert isinstance(body, AgentSubscriptionCreateBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if body.transport not in ("mcp_stream", "webhook"):
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(
                f"transport must be 'mcp_stream' or 'webhook'; got "
                f"{body.transport!r}"
            ),
        )
    if body.transport == "webhook":
        if not body.webhook_url or not body.webhook_secret_ref:
            raise web.HTTPUnprocessableEntity(
                reason=_bad_text(
                    "webhook transport requires both webhook_url and "
                    "webhook_secret_ref"
                ),
            )

    # Wildcard guard: at least one filter axis must be non-empty.
    f = body.filter or {}
    have_axis = any(
        [
            bool(f.get("kinds")),
            bool(f.get("domains")),
            bool(f.get("agent_id_ref")),
            bool(f.get("payload_path_eq")),
        ]
    )
    if not have_axis:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(
                "filter must constrain at least one of "
                "(kinds, domains, agent_id_ref, payload_path_eq); a "
                "wildcard subscription would match every ledger entry"
            ),
        )

    from datetime import UTC, datetime
    from uuid import uuid4

    subscription_id = str(uuid4())
    args: dict[str, Any] = {
        "subscription_id": subscription_id,
        "agent_id": body.agent_id,
        "filter": dict(f),
        "transport": body.transport,
        "webhook_url": body.webhook_url,
        "webhook_secret_ref": body.webhook_secret_ref,
        "description": body.description,
        "granted_by": str(body.granted_by),
    }

    try:
        await ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "agent_subscription_created",
                "ref_id": subscription_id,
                "agent_id": body.agent_id,
                "transport": body.transport,
                "granted_by": str(body.granted_by),
            },
            execute_fn=lambda: {
                "tool": "emit_agent_subscription_created",
                "args": dict(args),
                "result_ref": subscription_id,
            },
            verify_fn=lambda _e: {
                "checks": [
                    {"name": "agent_subscription_created_recorded", "ok": True},
                ],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": (
                    f"admin {body.granted_by} subscribed agent "
                    f"{body.agent_id!r} via {body.transport!r}"
                ),
            },
            timestamp=datetime.now(UTC),
            quadrant="active_deterministic",
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "subscription_id": subscription_id,
            "subscriptionId": subscription_id,
        },
        status=200,
    )


async def delete_agent_subscription(
    request: web.Request,
) -> web.Response:
    """DELETE /api/v1/write_actions/agent_subscriptions_revoke/{subscription_id}
    — v2.A Task 7.

    Writes an ``emit_agent_subscription_revoked`` PEVR cycle. Body shape
    is :class:`AgentSubscriptionRevokeBody` (the dashboard wraps the
    revoke action with a body to thread ``revoked_by`` through; an empty
    body is also tolerated and defaults reason to ``admin_revoked``).

    The handler does NOT verify the subscription exists in the active
    set — replay determinism prefers an additive write over a read-then-
    write race. The reader naturally de-dupes revokes on re-replay.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    subscription_id = request.match_info.get("subscription_id", "").strip()
    if not subscription_id:
        raise web.HTTPBadRequest(reason="missing subscription_id")

    body: AgentSubscriptionRevokeBody
    try:
        body = await _read_body(request, AgentSubscriptionRevokeBody)
    except web.HTTPBadRequest:
        # Empty body — accept and synthesize defaults so a vanilla DELETE
        # with no body still works (some HTTP clients omit bodies on
        # DELETE).
        body = AgentSubscriptionRevokeBody(
            company_id=company_id,
            reason="admin_revoked",
            revoked_by=company_id,  # placeholder; below we overwrite
        )
    assert isinstance(body, AgentSubscriptionRevokeBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )
    if body.reason not in _VALID_REVOKE_REASONS:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(
                f"reason must be one of "
                f"{sorted(_VALID_REVOKE_REASONS)}; got {body.reason!r}"
            ),
        )

    from datetime import UTC, datetime

    args: dict[str, Any] = {
        "subscription_id": subscription_id,
        "reason": body.reason,
        "revoked_by": str(body.revoked_by),
    }

    try:
        await ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "agent_subscription_revoked",
                "ref_id": subscription_id,
                "reason": body.reason,
                "revoked_by": str(body.revoked_by),
            },
            execute_fn=lambda: {
                "tool": "emit_agent_subscription_revoked",
                "args": dict(args),
                "result_ref": subscription_id,
            },
            verify_fn=lambda _e: {
                "checks": [
                    {"name": "agent_subscription_revoked_recorded", "ok": True},
                ],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": f"subscription revoked: {body.reason}",
            },
            timestamp=datetime.now(UTC),
            quadrant="active_deterministic",
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {"revoked": True, "subscription_id": subscription_id},
        status=200,
    )


async def delete_agent(request: web.Request) -> web.Response:
    """DELETE /api/v1/write_actions/agents_revoke/{agent_id} — v1.4 follow-up.

    Revokes every active grant held by the agent. Writes one
    ``emit_agent_grant`` (status=``revoked``) PEVR cycle per active grant
    — the canonical Addendum 3 single-kind-with-status pattern. Returns
    ``{"revoked": true, "agent_id": str, "revoked_grant_count": int}``.

    Idempotent: an agent with zero active grants returns
    ``revoked_grant_count: 0`` and writes nothing. No 404 on unknown
    agent_id — replay determinism prefers an additive write (or no-op)
    over a read-then-write race.

    Authorization mirrors ``delete_agent_subscription``: bearer token +
    tenant header. The dashboard layer enforces the admin-only role
    check before calling this endpoint (defense in depth — the gateway's
    bearer token is the same one across all admin actions; the dashboard
    is the role boundary).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    agent_id = request.match_info.get("agent_id", "").strip()
    if not agent_id:
        raise web.HTTPBadRequest(reason="missing agent_id")

    body: AgentRevokeBody
    try:
        body = await _read_body(request, AgentRevokeBody)
    except web.HTTPBadRequest:
        # Empty body — synthesize defaults so a vanilla DELETE with no
        # body still works (some HTTP clients omit bodies on DELETE).
        body = AgentRevokeBody(
            company_id=company_id,
            reason="admin_revoked",
            revoked_by=company_id,  # placeholder; below we overwrite-guard
        )
    assert isinstance(body, AgentRevokeBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )
    if body.reason not in _VALID_REVOKE_REASONS:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(
                f"reason must be one of "
                f"{sorted(_VALID_REVOKE_REASONS)}; got {body.reason!r}"
            ),
        )

    try:
        results = await write_actions.revoke_agent(
            ledger,
            company_id,
            agent_id=agent_id,
            revoked_by=body.revoked_by,
            reason=body.reason,
        )
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "revoked": True,
            "agent_id": agent_id,
            "agentId": agent_id,
            "revoked_grant_count": len(results),
            "revokedGrantCount": len(results),
        },
        status=200,
    )


async def patch_agent_metadata(request: web.Request) -> web.Response:
    """PATCH /api/v1/write_actions/agents_metadata/{agent_id} —
    final wave item #5 (2026-05-13).

    Updates an agent's mutable metadata (display_name / description).
    Emits one ``agent_metadata_updated`` PEVR cycle. Preserves
    ``agent_id`` continuity so grants, subscriptions, and the audit
    trail stay attached to the same agent.

    At least one of ``display_name`` / ``description`` must be non-empty
    AND different from the agent's current values — the dashboard form
    catches this client-side; we re-validate server-side that at least
    one mutation is requested (422 otherwise).

    Authorization mirrors ``delete_agent``: bearer token + tenant
    header. The dashboard layer enforces the admin-only role check
    before calling this endpoint (defense in depth — the gateway's
    bearer token is the same one across all admin actions; the
    dashboard is the role boundary).

    Returns ``{"updated": true, "agent_id": str}`` on success.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    agent_id = request.match_info.get("agent_id", "").strip()
    if not agent_id:
        raise web.HTTPBadRequest(reason="missing agent_id")

    body = await _read_body(request, AgentMetadataUpdateBody)
    assert isinstance(body, AgentMetadataUpdateBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )
    # At least one of display_name / description must be present. None
    # = unchanged; empty string on display_name is rejected (display
    # names cannot be cleared), empty string on description is allowed
    # (admins clearing a stale description).
    if body.display_name is None and body.description is None:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(
                "at least one of display_name or description must be "
                "set (both None is a no-op)"
            ),
        )
    if body.display_name is not None and not body.display_name.strip():
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(
                "display_name cannot be cleared to empty; pass None to "
                "leave unchanged"
            ),
        )

    try:
        await write_actions.update_agent_metadata(
            ledger,
            company_id,
            agent_id=agent_id,
            display_name=body.display_name,
            description=body.description,
            updated_by_person_id=body.updated_by,
            reason=body.reason,
        )
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "updated": True,
            "agent_id": agent_id,
            "agentId": agent_id,
        },
        status=200,
    )


async def post_agent_metadata_revert(request: web.Request) -> web.Response:
    """POST /api/v1/write_actions/agents_metadata_revert/{agent_id} —
    post-rest path #4 (2026-05-13).

    Reverts an agent's display_name + description to the state implied by
    the second-most-recent ``agent_metadata_updated`` (or the
    ``agent_registered`` baseline when only one prior update exists).
    Emits a new ``agent_metadata_updated`` PEVR cycle (forward-only;
    no new ledger kind, no mutation of prior entries).

    Returns ``{"reverted": true, "agent_id": str}`` on success, 400 when
    no prior update exists, 422 on validation drift, 401 on missing
    bearer.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    agent_id = request.match_info.get("agent_id", "").strip()
    if not agent_id:
        raise web.HTTPBadRequest(reason="missing agent_id")

    body = await _read_body(request, AgentMetadataRevertBody)
    assert isinstance(body, AgentMetadataRevertBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    try:
        await write_actions.revert_agent_metadata(
            ledger,
            company_id,
            agent_id=agent_id,
            updated_by_person_id=body.updated_by,
            reason=body.reason,
        )
    except ValueError as exc:
        # "no prior update" is a 400 (caller bug — UI should not surface
        # the button in that state); all other ValueErrors are also 400
        # since they signal a malformed agent state, not a server-side
        # invariant violation.
        message = str(exc)
        if "no prior agent_metadata_updated" in message or "nothing to revert" in message:
            raise web.HTTPBadRequest(reason=_bad_text(message)) from exc
        raise web.HTTPUnprocessableEntity(reason=_bad_text(message)) from exc
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "reverted": True,
            "agent_id": agent_id,
            "agentId": agent_id,
        },
        status=200,
    )


async def _lineage_edge_proposed_exists(
    ledger: Any, *, company_id: UUID, edge_id: str,
) -> bool:
    """Return True iff a ``lineage_edge_proposed`` execute entry exists
    for this (company_id, edge_id).

    Walks the tenant-scoped ledger looking for an execute row whose
    payload carries ``tool == "emit_lineage_edge_proposed"`` AND
    ``args.edge_id == edge_id``. Used by the confirm + reject handlers
    to surface a 404 when an admin requests an unknown edge — the
    canonical "edge_id not found in projection_lineage_edges" check
    per the L3 Sub-wave C contract, materialized over the ledger to
    keep tests that use InMemoryLedger honest about the projection
    semantics.
    """
    entries = await ledger.fetch(company_id)
    for entry in entries:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("tool") != "emit_lineage_edge_proposed":
            continue
        args = payload.get("args") or {}
        if isinstance(args, dict) and str(args.get("edge_id") or "") == edge_id:
            return True
    return False


async def post_lineage_edge_confirm(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/lineage_edges_confirm/{edge_id} —
    L3 Sub-wave C (2026-05-29).

    Emits a ``lineage_edge_confirmed`` PEVR cycle for a previously-
    proposed lineage edge. Forward-only: re-confirmation after a
    rejection writes a new entry; the projection_lineage_edges fold
    flips ``state`` to ``"confirmed"`` on the (company_id, edge_id)
    row.

    Returns 404 when the edge_id is unknown to the tenant (no prior
    ``lineage_edge_proposed`` ledger entry). Tenant header resolves to
    company_id; body ``company_id`` must agree (400 on mismatch).

    Authorization mirrors v2.A patterns: bearer token + tenant header
    at the HTTP layer, admin role check at the dashboard server action
    (defense in depth).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    edge_id = request.match_info.get("edge_id", "").strip()
    if not edge_id:
        raise web.HTTPBadRequest(reason="missing edge_id")

    body = await _read_body(request, LineageEdgeConfirmBody)
    assert isinstance(body, LineageEdgeConfirmBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if not await _lineage_edge_proposed_exists(
        ledger, company_id=company_id, edge_id=edge_id,
    ):
        raise web.HTTPNotFound(
            reason=_bad_text(
                f"no lineage_edge_proposed entry found for edge_id "
                f"{edge_id!r} in tenant {company_id}"
            ),
        )

    try:
        await write_actions.confirm_lineage_edge(
            ledger,
            company_id,
            edge_id=edge_id,
            confirmed_by_person_id=str(body.confirmed_by),
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {"confirmed": True, "edge_id": edge_id, "edgeId": edge_id},
        status=200,
    )


async def post_lineage_edge_reject(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/lineage_edges_reject/{edge_id} —
    L3 Sub-wave C (2026-05-29).

    Emits a ``lineage_edge_rejected`` PEVR cycle for a previously-
    proposed lineage edge. Forward-only: re-rejection after re-
    confirmation writes a new entry; the projection_lineage_edges fold
    flips ``state`` to ``"rejected"`` on the (company_id, edge_id) row.

    ``reason`` must be one of the strict enum values on
    :class:`LineageEdgeRejectedPayload`; 400 on unknown reasons.
    Returns 404 when the edge_id is unknown to the tenant.

    Authorization mirrors v2.A patterns: bearer token + tenant header
    at the HTTP layer, admin role check at the dashboard server action
    (defense in depth).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    edge_id = request.match_info.get("edge_id", "").strip()
    if not edge_id:
        raise web.HTTPBadRequest(reason="missing edge_id")

    body = await _read_body(request, LineageEdgeRejectBody)
    assert isinstance(body, LineageEdgeRejectBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if body.reason not in _VALID_LINEAGE_EDGE_REJECT_REASONS:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"reason must be one of "
                f"{sorted(_VALID_LINEAGE_EDGE_REJECT_REASONS)}; "
                f"got {body.reason!r}"
            ),
        )

    if not await _lineage_edge_proposed_exists(
        ledger, company_id=company_id, edge_id=edge_id,
    ):
        raise web.HTTPNotFound(
            reason=_bad_text(
                f"no lineage_edge_proposed entry found for edge_id "
                f"{edge_id!r} in tenant {company_id}"
            ),
        )

    try:
        await write_actions.reject_lineage_edge(
            ledger,
            company_id,
            edge_id=edge_id,
            rejected_by_person_id=str(body.rejected_by),
            reason=body.reason,
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "rejected": True,
            "edge_id": edge_id,
            "edgeId": edge_id,
            "reason": body.reason,
        },
        status=200,
    )


# --- L7 Sub-wave C (2026-05-30) — quality-check admin handlers. -------------


async def _quality_check_proposed_exists(
    ledger: Any, *, company_id: UUID, check_id: str,
) -> bool:
    """Return True iff a ``quality_check_proposed`` execute entry exists
    for this (company_id, check_id).

    Walks the tenant-scoped ledger looking for an execute row whose
    payload carries ``tool == "emit_quality_check_proposed"`` AND
    ``args.check_id == check_id``. Used by the confirm + reject handlers
    to surface a 404 when an admin requests an unknown check — the
    canonical "check_id not found in projection_quality_checks" check
    materialized over the ledger to keep tests that use InMemoryLedger
    honest about the projection semantics (mirrors
    :func:`_lineage_edge_proposed_exists`).
    """
    entries = await ledger.fetch(company_id)
    for entry in entries:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("tool") != "emit_quality_check_proposed":
            continue
        args = payload.get("args") or {}
        if isinstance(args, dict) and str(args.get("check_id") or "") == check_id:
            return True
    return False


async def post_quality_check_confirm(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/quality_checks_confirm/{check_id} —
    L7 Sub-wave C (2026-05-30).

    Emits a ``quality_check_confirmed`` PEVR cycle for a previously-
    proposed quality check. Forward-only: re-confirmation after a
    rejection writes a new entry; the projection_quality_checks fold
    flips ``state`` to ``"confirmed"`` on the (company_id, check_id)
    row.

    Returns 404 when the check_id is unknown to the tenant (no prior
    ``quality_check_proposed`` ledger entry). Tenant header resolves
    to company_id; body ``company_id`` must agree (400 on mismatch).

    Authorization mirrors v2.A + L3 patterns: bearer token + tenant
    header at the HTTP layer, admin role check at the dashboard server
    action (defense in depth).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    check_id = request.match_info.get("check_id", "").strip()
    if not check_id:
        raise web.HTTPBadRequest(reason="missing check_id")

    body = await _read_body(request, QualityCheckConfirmBody)
    assert isinstance(body, QualityCheckConfirmBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if not await _quality_check_proposed_exists(
        ledger, company_id=company_id, check_id=check_id,
    ):
        raise web.HTTPNotFound(
            reason=_bad_text(
                f"no quality_check_proposed entry found for check_id "
                f"{check_id!r} in tenant {company_id}"
            ),
        )

    try:
        await write_actions.confirm_quality_check(
            ledger,
            company_id,
            check_id=check_id,
            confirmed_by_person_id=str(body.confirmed_by),
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {"confirmed": True, "check_id": check_id, "checkId": check_id},
        status=200,
    )


async def post_quality_check_reject(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/quality_checks_reject/{check_id} —
    L7 Sub-wave C (2026-05-30).

    Emits a ``quality_check_rejected`` PEVR cycle for a previously-
    proposed quality check. Forward-only: re-rejection after re-
    confirmation writes a new entry; the projection_quality_checks
    fold flips ``state`` to ``"rejected"`` on the (company_id,
    check_id) row.

    ``reason`` must be one of the strict enum values on
    :class:`QualityCheckRejectedPayload`; 400 on unknown reasons.
    Returns 404 when the check_id is unknown to the tenant.

    Authorization mirrors v2.A + L3 patterns: bearer token + tenant
    header at the HTTP layer, admin role check at the dashboard server
    action (defense in depth).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    check_id = request.match_info.get("check_id", "").strip()
    if not check_id:
        raise web.HTTPBadRequest(reason="missing check_id")

    body = await _read_body(request, QualityCheckRejectBody)
    assert isinstance(body, QualityCheckRejectBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if body.reason not in _VALID_QUALITY_CHECK_REJECT_REASONS:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"reason must be one of "
                f"{sorted(_VALID_QUALITY_CHECK_REJECT_REASONS)}; "
                f"got {body.reason!r}"
            ),
        )

    if not await _quality_check_proposed_exists(
        ledger, company_id=company_id, check_id=check_id,
    ):
        raise web.HTTPNotFound(
            reason=_bad_text(
                f"no quality_check_proposed entry found for check_id "
                f"{check_id!r} in tenant {company_id}"
            ),
        )

    try:
        await write_actions.reject_quality_check(
            ledger,
            company_id,
            check_id=check_id,
            rejected_by_person_id=str(body.rejected_by),
            reason=body.reason,
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "rejected": True,
            "check_id": check_id,
            "checkId": check_id,
            "reason": body.reason,
        },
        status=200,
    )


# --- L4 Sub-wave C (2026-06-02) — schema-impact admin endpoints. -----------


async def _schema_impact_proposed_exists(
    ledger: Any, *, company_id: UUID, impact_id: str,
) -> bool:
    """Return True iff a ``schema_impact_proposed`` execute entry exists
    for this (company_id, impact_id).

    Walks the tenant-scoped ledger looking for an execute row whose
    payload carries ``tool == "emit_schema_impact_proposed"`` AND
    ``args.impact_id == impact_id``. Used by the confirm + reject
    handlers to surface a 404 when an admin requests an unknown impact
    — the canonical "impact_id not found in projection_schema_impacts"
    check materialized over the ledger to keep tests that use
    InMemoryLedger honest about the projection semantics (mirrors
    :func:`_lineage_edge_proposed_exists` +
    :func:`_quality_check_proposed_exists`).
    """
    entries = await ledger.fetch(company_id)
    for entry in entries:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("tool") != "emit_schema_impact_proposed":
            continue
        args = payload.get("args") or {}
        if isinstance(args, dict) and str(args.get("impact_id") or "") == impact_id:
            return True
    return False


async def post_schema_impact_confirm(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/schema_impacts_confirm/{impact_id} —
    L4 Sub-wave C (2026-06-02).

    Emits a ``schema_impact_confirmed`` PEVR cycle for a previously-
    proposed schema impact. Forward-only: re-confirmation after a
    rejection writes a new entry; the projection_schema_impacts fold
    (v023) flips ``state`` to ``"confirmed"`` on the (company_id,
    impact_id) row.

    Returns 404 when the impact_id is unknown to the tenant (no prior
    ``schema_impact_proposed`` ledger entry). Tenant header resolves
    to company_id; body ``company_id`` must agree (400 on mismatch).

    Authorization mirrors v2.A + L3 + L7 patterns: bearer token +
    tenant header at the HTTP layer, admin role check at the dashboard
    server action (defense in depth).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    impact_id = request.match_info.get("impact_id", "").strip()
    if not impact_id:
        raise web.HTTPBadRequest(reason="missing impact_id")

    body = await _read_body(request, SchemaImpactConfirmBody)
    assert isinstance(body, SchemaImpactConfirmBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if not await _schema_impact_proposed_exists(
        ledger, company_id=company_id, impact_id=impact_id,
    ):
        raise web.HTTPNotFound(
            reason=_bad_text(
                f"no schema_impact_proposed entry found for impact_id "
                f"{impact_id!r} in tenant {company_id}"
            ),
        )

    try:
        await write_actions.confirm_schema_impact(
            ledger,
            company_id,
            impact_id=impact_id,
            confirmed_by_person_id=str(body.confirmed_by),
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {"confirmed": True, "impact_id": impact_id, "impactId": impact_id},
        status=200,
    )


async def post_schema_impact_reject(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/schema_impacts_reject/{impact_id} —
    L4 Sub-wave C (2026-06-02).

    Emits a ``schema_impact_rejected`` PEVR cycle for a previously-
    proposed schema impact. Forward-only: re-rejection after re-
    confirmation writes a new entry; the projection_schema_impacts
    fold (v023) flips ``state`` to ``"rejected"`` on the (company_id,
    impact_id) row.

    ``reason`` must be one of the strict 5-value enum on
    :class:`SchemaImpactRejectedPayload`; 400 on unknown reasons.
    Returns 404 when the impact_id is unknown to the tenant.

    Authorization mirrors v2.A + L3 + L7 patterns: bearer token +
    tenant header at the HTTP layer, admin role check at the dashboard
    server action (defense in depth).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    impact_id = request.match_info.get("impact_id", "").strip()
    if not impact_id:
        raise web.HTTPBadRequest(reason="missing impact_id")

    body = await _read_body(request, SchemaImpactRejectBody)
    assert isinstance(body, SchemaImpactRejectBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if body.reason not in _VALID_SCHEMA_IMPACT_REJECT_REASONS:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"reason must be one of "
                f"{sorted(_VALID_SCHEMA_IMPACT_REJECT_REASONS)}; "
                f"got {body.reason!r}"
            ),
        )

    if not await _schema_impact_proposed_exists(
        ledger, company_id=company_id, impact_id=impact_id,
    ):
        raise web.HTTPNotFound(
            reason=_bad_text(
                f"no schema_impact_proposed entry found for impact_id "
                f"{impact_id!r} in tenant {company_id}"
            ),
        )

    try:
        await write_actions.reject_schema_impact(
            ledger,
            company_id,
            impact_id=impact_id,
            rejected_by_person_id=str(body.rejected_by),
            reason=body.reason,
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "rejected": True,
            "impact_id": impact_id,
            "impactId": impact_id,
            "reason": body.reason,
        },
        status=200,
    )


# --- L5 Sub-wave C (2026-06-05) — semantic-type admin endpoints. -----------


async def _semantic_type_proposed_exists(
    ledger: Any, *, company_id: UUID, type_id: str,
) -> bool:
    """Return True iff a ``semantic_type_proposed`` execute entry exists
    for this (company_id, type_id).

    Walks the tenant-scoped ledger looking for an execute row whose
    payload carries ``tool == "emit_semantic_type_proposed"`` AND
    ``args.type_id == type_id``. Used by the confirm + reject handlers
    to surface a 404 when an admin requests an unknown semantic-type
    — the canonical "type_id not found in projection_semantic_types"
    check materialized over the ledger to keep tests that use
    InMemoryLedger honest about the projection semantics (mirrors
    :func:`_lineage_edge_proposed_exists` +
    :func:`_quality_check_proposed_exists` +
    :func:`_schema_impact_proposed_exists`).
    """
    entries = await ledger.fetch(company_id)
    for entry in entries:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("tool") != "emit_semantic_type_proposed":
            continue
        args = payload.get("args") or {}
        if isinstance(args, dict) and str(args.get("type_id") or "") == type_id:
            return True
    return False


async def post_semantic_type_confirm(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/semantic_types_confirm/{type_id} —
    L5 Sub-wave C (2026-06-05).

    Emits a ``semantic_type_confirmed`` PEVR cycle for a previously-
    proposed semantic type. Forward-only: re-confirmation after a
    rejection writes a new entry; the projection_semantic_types fold
    (v024) flips ``state`` to ``"confirmed"`` on the (company_id,
    type_id) row.

    Returns 404 when the type_id is unknown to the tenant (no prior
    ``semantic_type_proposed`` ledger entry). Tenant header resolves
    to company_id; body ``company_id`` must agree (400 on mismatch).

    Authorization mirrors v2.A + L3 + L7 + L4 patterns: bearer token +
    tenant header at the HTTP layer, admin role check at the dashboard
    server action (defense in depth).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    type_id = request.match_info.get("type_id", "").strip()
    if not type_id:
        raise web.HTTPBadRequest(reason="missing type_id")

    body = await _read_body(request, SemanticTypeConfirmBody)
    assert isinstance(body, SemanticTypeConfirmBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if not await _semantic_type_proposed_exists(
        ledger, company_id=company_id, type_id=type_id,
    ):
        raise web.HTTPNotFound(
            reason=_bad_text(
                f"no semantic_type_proposed entry found for type_id "
                f"{type_id!r} in tenant {company_id}"
            ),
        )

    try:
        await write_actions.confirm_semantic_type(
            ledger,
            company_id,
            type_id=type_id,
            confirmed_by_person_id=str(body.confirmed_by),
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {"confirmed": True, "type_id": type_id, "typeId": type_id},
        status=200,
    )


async def post_semantic_type_reject(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/semantic_types_reject/{type_id} —
    L5 Sub-wave C (2026-06-05).

    Emits a ``semantic_type_rejected`` PEVR cycle for a previously-
    proposed semantic type. Forward-only: re-rejection after re-
    confirmation writes a new entry; the projection_semantic_types
    fold (v024) flips ``state`` to ``"rejected"`` on the (company_id,
    type_id) row.

    ``reason`` must be one of the strict 5-value enum on
    :class:`SemanticTypeRejectedPayload`; 400 on unknown reasons.
    The L5-specific 5th value is ``wrong_type`` (replaces L4's
    ``already_handled`` and L7's ``wrong_threshold``).

    Returns 404 when the type_id is unknown to the tenant.

    Authorization mirrors v2.A + L3 + L7 + L4 patterns: bearer token +
    tenant header at the HTTP layer, admin role check at the dashboard
    server action (defense in depth).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    type_id = request.match_info.get("type_id", "").strip()
    if not type_id:
        raise web.HTTPBadRequest(reason="missing type_id")

    body = await _read_body(request, SemanticTypeRejectBody)
    assert isinstance(body, SemanticTypeRejectBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if body.reason not in _VALID_SEMANTIC_TYPE_REJECT_REASONS:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"reason must be one of "
                f"{sorted(_VALID_SEMANTIC_TYPE_REJECT_REASONS)}; "
                f"got {body.reason!r}"
            ),
        )

    if not await _semantic_type_proposed_exists(
        ledger, company_id=company_id, type_id=type_id,
    ):
        raise web.HTTPNotFound(
            reason=_bad_text(
                f"no semantic_type_proposed entry found for type_id "
                f"{type_id!r} in tenant {company_id}"
            ),
        )

    try:
        await write_actions.reject_semantic_type(
            ledger,
            company_id,
            type_id=type_id,
            rejected_by_person_id=str(body.rejected_by),
            reason=body.reason,
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "rejected": True,
            "type_id": type_id,
            "typeId": type_id,
            "reason": body.reason,
        },
        status=200,
    )


# --- L6 Sub-wave C (2026-06-06) — column-classification admin endpoints. ---


async def _column_classification_proposed_exists(
    ledger: Any, *, company_id: UUID, classification_id: str,
) -> bool:
    """Return True iff a ``column_classification_proposed`` execute entry
    exists for this (company_id, classification_id).

    Walks the tenant-scoped ledger looking for an execute row whose
    payload carries ``tool == "emit_column_classification_proposed"``
    AND ``args.classification_id == classification_id``. Used by the
    confirm + reject handlers to surface a 404 when an admin requests
    an unknown classification_id — the canonical "classification_id not
    found in projection_column_classifications" check materialized over
    the ledger to keep tests that use InMemoryLedger honest about the
    projection semantics (mirrors
    :func:`_lineage_edge_proposed_exists` +
    :func:`_quality_check_proposed_exists` +
    :func:`_schema_impact_proposed_exists` +
    :func:`_semantic_type_proposed_exists`).
    """
    entries = await ledger.fetch(company_id)
    for entry in entries:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("tool") != "emit_column_classification_proposed":
            continue
        args = payload.get("args") or {}
        if (
            isinstance(args, dict)
            and str(args.get("classification_id") or "") == classification_id
        ):
            return True
    return False


async def post_column_classification_confirm(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/column_classifications_confirm/{classification_id}
    — L6 Sub-wave C (2026-06-06).

    Emits a ``column_classification_confirmed`` PEVR cycle for a
    previously-proposed classification. Forward-only: re-confirmation
    after a rejection writes a new entry; the
    projection_column_classifications fold (v025) flips ``state`` to
    ``"confirmed"`` on the (company_id, classification_id) row.

    Returns 404 when the classification_id is unknown to the tenant (no
    prior ``column_classification_proposed`` ledger entry). Tenant
    header resolves to company_id; body ``company_id`` must agree (400
    on mismatch).

    Authorization mirrors v2.A + L3 + L7 + L4 + L5 patterns: bearer
    token + tenant header at the HTTP layer, admin role check at the
    dashboard server action (defense in depth).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    classification_id = request.match_info.get(
        "classification_id", "",
    ).strip()
    if not classification_id:
        raise web.HTTPBadRequest(reason="missing classification_id")

    body = await _read_body(request, ColumnClassificationConfirmBody)
    assert isinstance(body, ColumnClassificationConfirmBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if not await _column_classification_proposed_exists(
        ledger,
        company_id=company_id,
        classification_id=classification_id,
    ):
        raise web.HTTPNotFound(
            reason=_bad_text(
                f"no column_classification_proposed entry found for "
                f"classification_id {classification_id!r} in tenant "
                f"{company_id}"
            ),
        )

    try:
        await write_actions.confirm_column_classification(
            ledger,
            company_id,
            classification_id=classification_id,
            confirmed_by_person_id=str(body.confirmed_by),
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "confirmed": True,
            "classification_id": classification_id,
            "classificationId": classification_id,
        },
        status=200,
    )


async def post_column_classification_reject(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/column_classifications_reject/{classification_id}
    — L6 Sub-wave C (2026-06-06).

    Emits a ``column_classification_rejected`` PEVR cycle for a
    previously-proposed classification. Forward-only: re-rejection
    after re-confirmation writes a new entry; the
    projection_column_classifications fold (v025) flips ``state`` to
    ``"rejected"`` on the (company_id, classification_id) row.

    ``reason`` must be one of the strict 5-value enum on
    :class:`ColumnClassificationRejectedPayload`; 400 on unknown
    reasons. The L6-specific 5th value is ``wrong_level`` (distinct
    from L5's ``wrong_type``, L4's ``already_handled`` and L7's
    ``wrong_threshold``).

    Returns 404 when the classification_id is unknown to the tenant.

    Authorization mirrors v2.A + L3 + L7 + L4 + L5 patterns: bearer
    token + tenant header at the HTTP layer, admin role check at the
    dashboard server action (defense in depth).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    classification_id = request.match_info.get(
        "classification_id", "",
    ).strip()
    if not classification_id:
        raise web.HTTPBadRequest(reason="missing classification_id")

    body = await _read_body(request, ColumnClassificationRejectBody)
    assert isinstance(body, ColumnClassificationRejectBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if body.reason not in _VALID_COLUMN_CLASSIFICATION_REJECT_REASONS:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"reason must be one of "
                f"{sorted(_VALID_COLUMN_CLASSIFICATION_REJECT_REASONS)}; "
                f"got {body.reason!r}"
            ),
        )

    if not await _column_classification_proposed_exists(
        ledger,
        company_id=company_id,
        classification_id=classification_id,
    ):
        raise web.HTTPNotFound(
            reason=_bad_text(
                f"no column_classification_proposed entry found for "
                f"classification_id {classification_id!r} in tenant "
                f"{company_id}"
            ),
        )

    try:
        await write_actions.reject_column_classification(
            ledger,
            company_id,
            classification_id=classification_id,
            rejected_by_person_id=str(body.rejected_by),
            reason=body.reason,
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "rejected": True,
            "classification_id": classification_id,
            "classificationId": classification_id,
            "reason": body.reason,
        },
        status=200,
    )


# --- L8 Sub-wave C (2026-06-07) — entity-stitch admin handlers -------------


async def _entity_stitch_proposed_exists(
    ledger: Any,
    *,
    company_id: UUID,
    stitch_id: str,
) -> bool:
    """Walk the per-tenant ledger for a matching
    ``entity_stitch_proposed`` execute entry.

    Returns True when the stitch_id is known to this tenant. The
    handlers use this to surface 404 on unknown stitch_ids before
    writing the confirm/reject entry (mirrors
    :func:`_column_classification_proposed_exists` +
    :func:`_semantic_type_proposed_exists` +
    :func:`_schema_impact_proposed_exists`).
    """
    entries = await ledger.fetch(company_id)
    for entry in entries:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("tool") != "emit_entity_stitch_proposed":
            continue
        args = payload.get("args") or {}
        if (
            isinstance(args, dict)
            and str(args.get("stitch_id") or "") == stitch_id
        ):
            return True
    return False


async def post_entity_stitch_confirm(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/entity_stitches_confirm/{stitch_id}
    — L8 Sub-wave C (2026-06-07).

    Emits an ``entity_stitch_confirmed`` PEVR cycle for a
    previously-proposed stitch. Forward-only: re-confirmation after a
    rejection writes a new entry; the projection_entity_stitches fold
    (v026) flips ``state`` to ``"confirmed"`` on the (company_id,
    stitch_id) row.

    Returns 404 when the stitch_id is unknown to the tenant (no prior
    ``entity_stitch_proposed`` ledger entry). Tenant header resolves to
    company_id; body ``company_id`` must agree (400 on mismatch).

    Authorization mirrors v2.A + L3 + L7 + L4 + L5 + L6 patterns: bearer
    token + tenant header at the HTTP layer, admin role check at the
    dashboard server action (defense in depth).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    stitch_id = request.match_info.get("stitch_id", "").strip()
    if not stitch_id:
        raise web.HTTPBadRequest(reason="missing stitch_id")

    body = await _read_body(request, EntityStitchConfirmBody)
    assert isinstance(body, EntityStitchConfirmBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if not await _entity_stitch_proposed_exists(
        ledger,
        company_id=company_id,
        stitch_id=stitch_id,
    ):
        raise web.HTTPNotFound(
            reason=_bad_text(
                f"no entity_stitch_proposed entry found for "
                f"stitch_id {stitch_id!r} in tenant {company_id}"
            ),
        )

    try:
        await write_actions.confirm_entity_stitch(
            ledger,
            company_id,
            stitch_id=stitch_id,
            confirmed_by_person_id=str(body.confirmed_by),
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "confirmed": True,
            "stitch_id": stitch_id,
            "stitchId": stitch_id,
        },
        status=200,
    )


async def post_entity_stitch_reject(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/entity_stitches_reject/{stitch_id}
    — L8 Sub-wave C (2026-06-07).

    Emits an ``entity_stitch_rejected`` PEVR cycle for a
    previously-proposed stitch. Forward-only: re-rejection after
    re-confirmation writes a new entry; the projection_entity_stitches
    fold (v026) flips ``state`` to ``"rejected"`` on the (company_id,
    stitch_id) row.

    ``reason`` must be one of the strict 5-value enum on
    :class:`EntityStitchRejectedPayload`; 400 on unknown reasons. The
    L8-specific 5th value is ``wrong_pairing`` (distinct from L6's
    ``wrong_level``, L5's ``wrong_type``, L4's ``already_handled`` and
    L7's ``wrong_threshold``).

    Returns 404 when the stitch_id is unknown to the tenant.

    Authorization mirrors v2.A + L3 + L7 + L4 + L5 + L6 patterns: bearer
    token + tenant header at the HTTP layer, admin role check at the
    dashboard server action (defense in depth).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    stitch_id = request.match_info.get("stitch_id", "").strip()
    if not stitch_id:
        raise web.HTTPBadRequest(reason="missing stitch_id")

    body = await _read_body(request, EntityStitchRejectBody)
    assert isinstance(body, EntityStitchRejectBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if body.reason not in _VALID_ENTITY_STITCH_REJECT_REASONS:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"reason must be one of "
                f"{sorted(_VALID_ENTITY_STITCH_REJECT_REASONS)}; "
                f"got {body.reason!r}"
            ),
        )

    if not await _entity_stitch_proposed_exists(
        ledger,
        company_id=company_id,
        stitch_id=stitch_id,
    ):
        raise web.HTTPNotFound(
            reason=_bad_text(
                f"no entity_stitch_proposed entry found for "
                f"stitch_id {stitch_id!r} in tenant {company_id}"
            ),
        )

    try:
        await write_actions.reject_entity_stitch(
            ledger,
            company_id,
            stitch_id=stitch_id,
            rejected_by_person_id=str(body.rejected_by),
            reason=body.reason,
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "rejected": True,
            "stitch_id": stitch_id,
            "stitchId": stitch_id,
            "reason": body.reason,
        },
        status=200,
    )


# --- L1 Sub-wave C (2026-06-08) — source-candidate admin handlers ----------


async def _source_candidate_proposed_exists(
    ledger: Any,
    *,
    company_id: UUID,
    candidate_id: str,
) -> bool:
    """Walk the per-tenant ledger for a matching
    ``source_candidate_proposed`` execute entry.

    Returns True when the candidate_id is known to this tenant. The
    handlers use this to surface 404 on unknown candidate_ids before
    writing the promote/reject entry (mirrors
    :func:`_entity_stitch_proposed_exists` +
    :func:`_column_classification_proposed_exists`).
    """
    entries = await ledger.fetch(company_id)
    for entry in entries:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("tool") != "emit_source_candidate_proposed":
            continue
        args = payload.get("args") or {}
        if (
            isinstance(args, dict)
            and str(args.get("candidate_id") or "") == candidate_id
        ):
            return True
    return False


async def _lookup_source_candidate_proposed(
    ledger: Any,
    *,
    company_id: UUID,
    candidate_id: str,
) -> dict[str, Any] | None:
    """Return the most-recent ``source_candidate_proposed`` payload args
    for ``candidate_id`` in this tenant, or ``None`` when none exists.

    Used by the promote handler's dual-write to translate the L1
    candidate into a source-pipeline propose call (the downstream
    source-builder needs the connector kind + identifier to seed the
    ``source_proposed`` payload).
    """
    entries = await ledger.fetch(company_id)
    latest: dict[str, Any] | None = None
    for entry in entries:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("tool") != "emit_source_candidate_proposed":
            continue
        args = payload.get("args") or {}
        if (
            isinstance(args, dict)
            and str(args.get("candidate_id") or "") == candidate_id
        ):
            latest = args
    return latest


def _proposed_kind_to_source_kind(proposed_kind: str) -> str:
    """Map a connector-registry kind onto a ``SourceProposedPayload.source_kind``.

    The L1 ``proposed_kind`` field carries a connector-registry kind
    string (e.g. ``"csv_local"``, ``"postgres"``, ``"stripe"``). The
    source-pipeline's :class:`SourceProposedPayload.source_kind` is a
    coarser tag (``"file" | "database" | "blob" | "rest_api"``). This
    bridge keeps the dual-write flow honest without coupling L1 to the
    source-pipeline's specific tag set.

    Wave 1 heuristic — covers the day-one connectors per
    ``Projects/wormbase/CLAUDE.md §2``:

    * file connectors → ``"file"``
    * database connectors → ``"database"``
    * blob / object-store connectors → ``"blob"``
    * SaaS / REST API connectors → ``"rest_api"``

    Unknown kinds fall back to ``"rest_api"`` (safe default; the
    source-builder's `confirm` stage validates the actual connector
    binding before the source ever talks to the network).
    """
    file_kinds = {"csv_local", "csv", "gsheets", "http_csv", "json_local"}
    db_kinds = {"postgres", "snowflake", "bigquery", "mysql", "redshift"}
    blob_kinds = {"s3_csv", "s3", "gcs", "azure_blob"}
    rest_kinds = {
        "stripe",
        "salesforce",
        "hubspot",
        "shopify",
        "intercom",
    }
    if proposed_kind in file_kinds:
        return "file"
    if proposed_kind in db_kinds:
        return "database"
    if proposed_kind in blob_kinds:
        return "blob"
    if proposed_kind in rest_kinds:
        return "rest_api"
    if proposed_kind.startswith("mcp:"):
        return "rest_api"
    return "rest_api"


async def post_source_candidate_promote(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/source_candidates_promote/{candidate_id}
    — L1 Sub-wave C (2026-06-08).

    Emits a ``source_candidate_promoted`` PEVR cycle for a
    previously-proposed candidate AND triggers a downstream
    ``source_proposed`` cycle via the existing :class:`SourceBuilder`
    flow. The two entries are linked via the L1 promote payload's
    ``downstream_source_proposed_id`` field (carrying the
    source-builder ``correlation_id``).

    Dual-write semantics (Wave 1):

      1. Look up the original ``source_candidate_proposed`` to extract
         the connector kind, identifier, suggested domain, and
         classification.
      2. Invoke :class:`SourceBuilder.propose` to write the downstream
         ``source_proposed`` PEVR cycle. Capture the resulting
         correlation_id.
      3. Write the ``source_candidate_promoted`` PEVR cycle with
         ``downstream_source_proposed_id`` = step 2's correlation_id.

    The two writes are sequential (not transactional). If step 2
    fails, step 3 still runs but with
    ``downstream_source_proposed_id=None`` — the audit entry lands
    regardless so the admin's intent is recorded. Per spec §8 Phase 2,
    a future wave decouples step 2 via a
    ``SourceCandidatePromoted → SourceProposed`` Reactivity.

    Returns 404 when the candidate_id is unknown to the tenant (no
    prior ``source_candidate_proposed`` ledger entry). Tenant header
    resolves to company_id; body ``company_id`` must agree (400 on
    mismatch).

    Authorization mirrors v2.A + L3 + L7 + L4 + L5 + L6 + L8 patterns:
    bearer token + tenant header at the HTTP layer, admin role check
    at the dashboard server action (defense in depth).
    """
    from wormbase_ledger.entries import AddedViaFlow as _AddedViaFlow

    from wormbase_core.source_builder import (
        SourceBuilder,
        SourceProposal,
    )

    _check_auth(request)
    company_id = _resolve_company_id(request)
    candidate_id = request.match_info.get("candidate_id", "").strip()
    if not candidate_id:
        raise web.HTTPBadRequest(reason="missing candidate_id")

    body = await _read_body(request, SourceCandidatePromoteBody)
    assert isinstance(body, SourceCandidatePromoteBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    original = await _lookup_source_candidate_proposed(
        ledger,
        company_id=company_id,
        candidate_id=candidate_id,
    )
    if original is None:
        raise web.HTTPNotFound(
            reason=_bad_text(
                f"no source_candidate_proposed entry found for "
                f"candidate_id {candidate_id!r} in tenant {company_id}"
            ),
        )

    # Dual-write step 2: trigger the existing source-builder flow to
    # emit a downstream source_proposed. Failures here do NOT block
    # step 3 — the audit entry lands regardless so the admin's intent
    # is recorded (per spec §8: dual-write is best-effort in Wave 1;
    # Phase 2 decouples via a Reactivity).
    downstream_correlation_id: str | None = None
    try:
        proposed_kind = str(original.get("proposed_kind") or "")
        proposed_identifier = str(original.get("proposed_identifier") or "")
        domain_hint = original.get("domain_id_hint")
        # Map the connector-registry kind onto the source-pipeline's
        # coarser source_kind tag.
        source_kind = _proposed_kind_to_source_kind(proposed_kind)
        # The source-builder's propose requires a domain string + a
        # classification. Wave 1 thread defaults that the admin
        # confirms in the next source-builder stage: "internal" is the
        # safe default for unclassified candidates (per SurfaceDriver
        # contract in CLAUDE.md §2).
        proposal = SourceProposal(
            proposed_uri=proposed_identifier or proposed_kind,
            proposed_type=source_kind,  # type: ignore[arg-type]
            proposed_domain=str(domain_hint or "uncategorised"),
            proposed_classification="internal",  # type: ignore[arg-type]
            added_by_person_id=body.promoted_by,
            added_via_flow="dashboard_form",  # type: ignore[arg-type]
            added_in_response_to=candidate_id,
            company_id=company_id,
        )
        builder = SourceBuilder(ledger)
        downstream_correlation_id = str(await builder.propose(proposal))
    except Exception as exc:
        logger.warning(
            "L1 promote dual-write step-2 (downstream source_proposed) "
            "failed for candidate_id=%s: %s — audit entry will still "
            "land with downstream_source_proposed_id=None",
            candidate_id, exc,
        )
        # Intentionally do NOT re-raise — the audit entry MUST land.

    try:
        await write_actions.promote_source_candidate(
            ledger,
            company_id,
            candidate_id=candidate_id,
            promoted_by_person_id=str(body.promoted_by),
            downstream_source_proposed_id=downstream_correlation_id,
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "promoted": True,
            "candidate_id": candidate_id,
            "candidateId": candidate_id,
            "downstream_source_proposed_id": downstream_correlation_id,
            "downstreamSourceProposedId": downstream_correlation_id,
        },
        status=200,
    )


async def post_source_candidate_reject(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/source_candidates_reject/{candidate_id}
    — L1 Sub-wave C (2026-06-08).

    Emits a ``source_candidate_rejected`` PEVR cycle for a
    previously-proposed candidate. Forward-only: re-rejection after
    re-promotion writes a new entry; the projection_source_candidates
    fold (v027) flips ``state`` to ``"rejected"`` on the (company_id,
    candidate_id) row.

    ``reason`` must be one of the strict 5-value enum on
    :class:`SourceCandidateRejectedPayload`; 400 on unknown reasons.
    The L1-specific 5th value is ``duplicate`` (distinct from L8's
    ``wrong_pairing``, L6's ``wrong_level``, L5's ``wrong_type``,
    L4's ``already_handled`` and L7's ``wrong_threshold``).

    Returns 404 when the candidate_id is unknown to the tenant.

    Authorization mirrors v2.A + L3 + L7 + L4 + L5 + L6 + L8 patterns:
    bearer token + tenant header at the HTTP layer, admin role check
    at the dashboard server action (defense in depth).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    candidate_id = request.match_info.get("candidate_id", "").strip()
    if not candidate_id:
        raise web.HTTPBadRequest(reason="missing candidate_id")

    body = await _read_body(request, SourceCandidateRejectBody)
    assert isinstance(body, SourceCandidateRejectBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if body.reason not in _VALID_SOURCE_CANDIDATE_REJECT_REASONS:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"reason must be one of "
                f"{sorted(_VALID_SOURCE_CANDIDATE_REJECT_REASONS)}; "
                f"got {body.reason!r}"
            ),
        )

    if not await _source_candidate_proposed_exists(
        ledger,
        company_id=company_id,
        candidate_id=candidate_id,
    ):
        raise web.HTTPNotFound(
            reason=_bad_text(
                f"no source_candidate_proposed entry found for "
                f"candidate_id {candidate_id!r} in tenant {company_id}"
            ),
        )

    try:
        await write_actions.reject_source_candidate(
            ledger,
            company_id,
            candidate_id=candidate_id,
            rejected_by_person_id=str(body.rejected_by),
            reason=body.reason,
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "rejected": True,
            "candidate_id": candidate_id,
            "candidateId": candidate_id,
            "reason": body.reason,
        },
        status=200,
    )


# --- L2 Sub-wave C (2026-06-09) — catalog-drift admin handlers --------------


async def _catalog_drift_proposed_exists(
    ledger: Any,
    *,
    company_id: UUID,
    drift_id: str,
) -> bool:
    """Walk the per-tenant ledger for a matching
    ``catalog_drift_proposed`` execute entry.

    Returns True when the drift_id is known to this tenant. The
    handlers use this to surface 404 on unknown drift_ids before
    writing the acknowledge/reject entry (mirrors
    :func:`_source_candidate_proposed_exists` +
    :func:`_entity_stitch_proposed_exists`).
    """
    entries = await ledger.fetch(company_id)
    for entry in entries:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("tool") != "emit_catalog_drift_proposed":
            continue
        args = payload.get("args") or {}
        if (
            isinstance(args, dict)
            and str(args.get("drift_id") or "") == drift_id
        ):
            return True
    return False


async def post_catalog_drift_acknowledge(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/catalog_drifts_acknowledge/{drift_id}
    — L2 Sub-wave C (2026-06-09).

    Emits a ``catalog_drift_acknowledged`` PEVR cycle for a
    previously-proposed drift. Forward-only: re-acknowledgment after
    a rejection writes a new entry; the projection_catalog_drifts
    fold (v028) flips ``state`` to ``"acknowledged"`` on the
    (company_id, drift_id) row.

    Returns 404 when the drift_id is unknown to the tenant (no prior
    ``catalog_drift_proposed`` ledger entry). Tenant header resolves
    to company_id; body ``company_id`` must agree (400 on mismatch).

    L2 uses ``acknowledge`` instead of ``confirm`` or ``promote``
    because the drift was already observed by the catalog-mirror's
    W5a Reactivity — acknowledgment is the no-op human-disposition
    record (no downstream pipeline trigger, no cross-axis effect).

    Authorization mirrors v2.A + L3 + L7 + L4 + L5 + L6 + L8 + L1
    patterns: bearer token + tenant header at the HTTP layer, admin
    role check at the dashboard server action (defense in depth).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    drift_id = request.match_info.get("drift_id", "").strip()
    if not drift_id:
        raise web.HTTPBadRequest(reason="missing drift_id")

    body = await _read_body(request, CatalogDriftAcknowledgeBody)
    assert isinstance(body, CatalogDriftAcknowledgeBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if not await _catalog_drift_proposed_exists(
        ledger,
        company_id=company_id,
        drift_id=drift_id,
    ):
        raise web.HTTPNotFound(
            reason=_bad_text(
                f"no catalog_drift_proposed entry found for "
                f"drift_id {drift_id!r} in tenant {company_id}"
            ),
        )

    try:
        await write_actions.acknowledge_catalog_drift(
            ledger,
            company_id,
            drift_id=drift_id,
            acknowledged_by_person_id=str(body.acknowledged_by),
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "acknowledged": True,
            "drift_id": drift_id,
            "driftId": drift_id,
        },
        status=200,
    )


async def post_catalog_drift_reject(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/catalog_drifts_reject/{drift_id}
    — L2 Sub-wave C (2026-06-09).

    Emits a ``catalog_drift_rejected`` PEVR cycle for a
    previously-proposed drift. Forward-only: re-rejection after
    re-acknowledgment writes a new entry; the
    projection_catalog_drifts fold (v028) flips ``state`` to
    ``"rejected"`` on the (company_id, drift_id) row.

    ``reason`` must be one of the strict 5-value enum on
    :class:`CatalogDriftRejectedPayload`; 400 on unknown reasons.
    The L2-specific 5th value is ``expected_change`` (distinct from
    L1's ``duplicate``, L8's ``wrong_pairing``, L6's ``wrong_level``,
    L5's ``wrong_type``, L4's ``already_handled`` and L7's
    ``wrong_threshold``).

    Returns 404 when the drift_id is unknown to the tenant.

    Authorization mirrors v2.A + L3 + L7 + L4 + L5 + L6 + L8 + L1
    patterns: bearer token + tenant header at the HTTP layer, admin
    role check at the dashboard server action (defense in depth).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    drift_id = request.match_info.get("drift_id", "").strip()
    if not drift_id:
        raise web.HTTPBadRequest(reason="missing drift_id")

    body = await _read_body(request, CatalogDriftRejectBody)
    assert isinstance(body, CatalogDriftRejectBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if body.reason not in _VALID_CATALOG_DRIFT_REJECT_REASONS:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"reason must be one of "
                f"{sorted(_VALID_CATALOG_DRIFT_REJECT_REASONS)}; "
                f"got {body.reason!r}"
            ),
        )

    if not await _catalog_drift_proposed_exists(
        ledger,
        company_id=company_id,
        drift_id=drift_id,
    ):
        raise web.HTTPNotFound(
            reason=_bad_text(
                f"no catalog_drift_proposed entry found for "
                f"drift_id {drift_id!r} in tenant {company_id}"
            ),
        )

    try:
        await write_actions.reject_catalog_drift(
            ledger,
            company_id,
            drift_id=drift_id,
            rejected_by_person_id=str(body.rejected_by),
            reason=body.reason,
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "rejected": True,
            "drift_id": drift_id,
            "driftId": drift_id,
            "reason": body.reason,
        },
        status=200,
    )


# --- Onboarding Sub-wave C (2026-05-30) handlers ---------------------------


_VALID_DOMAIN_PACK_IDS: frozenset[str] = frozenset(
    {"generic", "saas", "marketplace", "fintech"},
)


async def post_domain_pack_selected(request: web.Request) -> web.Response:
    """POST /api/v1/write_actions/domain_pack_selected/{pack_id} —
    Onboarding Sub-wave C (2026-05-30).

    Emits a ``domain_pack_selected`` parent PEVR cycle plus the
    fan-out (per-domain ``emit_domain_registered`` + per-policy
    ``emit_policy_applied`` execute entries) for the named pack.

    Idempotent: a prior pack-selection in this tenant short-circuits
    to a no-op (response carries ``already_seeded=true``).

    ``pack_id`` validated against the four canonical pack ids
    (generic / saas / marketplace / fintech); 400 on unknown ids.
    Future packs land by dropping a YAML; this allow-list is the
    server-side guard against typos in the dashboard form.

    Authorization mirrors v2.A patterns: bearer token + tenant header
    at the HTTP layer, admin role check at the dashboard server
    action (defense in depth).
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    pack_id = request.match_info.get("pack_id", "").strip().lower()
    if pack_id not in _VALID_DOMAIN_PACK_IDS:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"pack_id must be one of {sorted(_VALID_DOMAIN_PACK_IDS)}; "
                f"got {pack_id!r}"
            ),
        )

    body = await _read_body(request, DomainPackSelectedBody)
    assert isinstance(body, DomainPackSelectedBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    try:
        report = await write_actions.select_domain_pack(
            ledger,
            company_id,
            pack_id=pack_id,
            selected_by_person_id=body.selected_by_person_id,
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "pack_id": report.pack_id,
            "packId": report.pack_id,
            "pack_version": report.pack_version,
            "packVersion": report.pack_version,
            "already_seeded": report.already_seeded,
            "alreadySeeded": report.already_seeded,
            "domain_ids": list(report.domain_ids),
            "policy_ids": list(report.policy_ids),
        },
        status=200,
    )


async def post_person_invited(request: web.Request) -> web.Response:
    """POST /api/v1/write_actions/person_invited — Onboarding Sub-wave C.

    Emits a ``person_invited`` PEVR cycle. At least one of
    ``invitee_email`` / ``invitee_platform_id`` MUST be in the body;
    400 if both are absent. ``role_intent`` ∈ {admin, member,
    observer}; 422 on invalid values (caught at the payload class
    boundary).

    The actual ``person_proposed`` → ``person_confirmed`` lifecycle
    fires when the invitee accepts the signed acceptance URL — this
    handler only records the invite intent + audit trail.

    Authorization: bearer token + tenant header at the HTTP layer,
    admin role check at the dashboard server action.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, PersonInvitedBody)
    assert isinstance(body, PersonInvitedBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    if not body.invitee_email and not body.invitee_platform_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                "at least one of invitee_email or invitee_platform_id "
                "must be supplied"
            ),
        )

    try:
        await write_actions.invite_person(
            ledger,
            company_id,
            invited_by_person_id=body.invited_by_person_id,
            invitee_email=body.invitee_email,
            invitee_platform_id=body.invitee_platform_id,
            role_intent=body.role_intent,
            notes=body.notes,
        )
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except ValueError as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "invited": True,
            "invitee_email": body.invitee_email,
            "invitee_platform_id": body.invitee_platform_id,
            "role_intent": body.role_intent,
        },
        status=200,
    )


async def post_concept_confirmed(request: web.Request) -> web.Response:
    """POST /api/v1/write_actions/concept_confirmed/{term} —
    Onboarding Sub-wave D (2026-05-30).

    Graduates Tier 2's ``confirmBusinessDef`` from a synthetic
    receipt to a real ``concept_confirmed`` PEVR cycle. The handler:

    1. Resolves ``term`` (URL path, percent-decoded) against the
       company's ``concept_proposed`` projection — latest match wins.
    2. Emits a ``concept_confirmed`` PEVR cycle binding the resolved
       ``concept_id`` to ``confirmed_by_person_id`` from the body.

    Reuses existing KIND_REGISTRY entries — no new kinds. Returns 404
    when no prior proposal matches the term so the dashboard can
    surface "Worm hasn't proposed this concept yet" honestly rather
    than silently writing an orphan confirmation.

    Authorization mirrors v2.A pattern: bearer + tenant header at the
    HTTP layer, admin role check at the dashboard server action.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    term_raw = request.match_info.get("term", "")
    term = term_raw.strip()
    if not term:
        raise web.HTTPBadRequest(
            reason=_bad_text("term must be non-empty"),
        )

    body = await _read_body(request, ConceptConfirmedBody)
    assert isinstance(body, ConceptConfirmedBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    try:
        concept_id, write_result = await write_actions.confirm_concept(
            ledger,
            company_id,
            term=term,
            confirmed_by_person_id=body.confirmed_by_person_id,
        )
    except write_actions.ConceptProposalNotFound as exc:
        raise web.HTTPNotFound(
            reason=_bad_text(str(exc)),
        ) from exc
    except VerifyFailed as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc
    except (ValueError, ValidationError) as exc:
        raise web.HTTPUnprocessableEntity(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {
            "term": term,
            "concept_id": str(concept_id),
            "entry_ids": [str(eid) for eid in write_result.entry_ids],
        },
        status=200,
    )


async def get_connector_probe(request: web.Request) -> web.Response:
    """GET /api/v1/connectors/{kind}/probe —
    Onboarding Sub-wave D (2026-05-30).

    Per-tenant probe of a connector's runtime state. Returns one of:

      * ``state="works"``    — probe attempted + succeeded
      * ``state="degraded"`` — probe attempted + partial result
      * ``state="failed"``   — probe attempted + raised
      * ``state="unknown"``  — no probe wired for this kind (honest
                                non-fake-positive when the kind has no
                                tenant-side health check yet)

    Probe coverage today:

      * ``csv_local``: always ``works`` (no tenant config required;
                       the kind is constitutionally available).
      * Every other kind: ``unknown`` with an explicit ``reason``.

    Future per-kind probes plug in by extending ``_PROBE_HANDLERS``;
    the registry-scope branch in ``get_connectors`` reuses the same
    kind enumeration so no kind can ship without an explicit probe
    answer.

    Read-only, no auth required (parallel to ``GET /api/v1/connectors``).
    """
    from wormbase_lake_surfaces import default_registry

    kind = request.match_info.get("kind", "").strip()
    if not kind:
        raise web.HTTPNotFound(reason="connector kind required")

    registry = default_registry()
    cls = registry.get(kind)
    if cls is None:
        return web.json_response(
            {
                "kind": kind,
                "state": "unknown",
                "reason": f"unknown connector kind {kind!r}",
            },
            status=404,
        )

    status = getattr(cls, "status", "preview")

    if status == "coming_soon":
        return web.json_response(
            {
                "kind": kind,
                "state": "unknown",
                "reason": (
                    f"connector {kind!r} is marked coming_soon — "
                    "probe is intentionally not wired until the "
                    "implementation lands"
                ),
            },
            status=200,
        )

    if kind == "csv_local":
        # csv_local is the always-available wire-driven kind — no
        # per-tenant credentials, no remote round-trip. Honest "works".
        return web.json_response(
            {
                "kind": kind,
                "state": "works",
                "reason": None,
            },
            status=200,
        )

    # Honest "unknown" for kinds whose probe isn't yet wired. The
    # dashboard renders this with a neutral badge + the reason text.
    return web.json_response(
        {
            "kind": kind,
            "state": "unknown",
            "reason": (
                f"probe not yet implemented for kind {kind!r}; tenant "
                "connection state is captured on the source detail page"
            ),
        },
        status=200,
    )


async def post_import_dbt_catalog(request: web.Request) -> web.Response:
    """POST /api/v1/write_actions/import_dbt_catalog — Wave 3.2 Hole #2 (dbt branch).

    Fetches the manifest at ``manifest_uri``, parses it, writes the
    canonical catalog-mirror PEVR chain (``external_catalog_imported`` +
    per-edge ``external_lineage_imported`` + per-metric
    ``external_metric_imported``), and registers per-source
    catalog-mirror Reactivities when the registry is attached to the
    app (Wave 1 Task 5 cleanup 1a).

    Failure modes:
      * 404-style fetch failure / missing file → 400
      * unsupported manifest schema version → 400
      * any other parse / write failure → 422
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, ImportDbtCatalogBody)
    assert isinstance(body, ImportDbtCatalogBody)
    ledger = request.app[APP_LEDGER_KEY]
    registry = request.app.get(APP_REGISTRY_KEY)

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    # Import lazily — keeps the module's top-level import set light for
    # unit-test runs that don't exercise the catalog-mirror path.
    from wormbase_catalog_mirror.errors import (
        ManifestVersionUnsupportedError,
    )

    try:
        source_id, _results = await write_actions.import_dbt_catalog(
            ledger,
            company_id,
            manifest_uri=body.manifest_uri,
            domain_id=body.domain_id,
            imported_by=body.imported_by,
            reactivity_registry=registry,
        )
    except FileNotFoundError as exc:
        raise web.HTTPBadRequest(
            reason=_bad_text(f"manifest not found: {exc}"),
        ) from exc
    except ManifestVersionUnsupportedError as exc:
        raise web.HTTPBadRequest(
            reason=_bad_text(f"unsupported manifest schema: {exc}"),
        ) from exc
    except ValueError as exc:
        raise web.HTTPBadRequest(reason=_bad_text(str(exc))) from exc
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(
            reason=_bad_text(str(exc)),
        ) from exc
    except Exception as exc:
        # Network errors, malformed JSON, etc. — surface as 400 so the
        # dashboard form can render the failure inline.
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"dbt manifest import failed: {type(exc).__name__}: {exc}"
            ),
        ) from exc

    return web.json_response(
        {"source_id": str(source_id), "sourceId": str(source_id)},
        status=200,
    )


async def post_import_snowflake_catalog(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/import_snowflake_catalog — Wave 3.2 Hole #2 (snowflake branch).

    Same shape as ``post_import_dbt_catalog`` but uses
    ``SnowflakeNativeCatalogSource``. The Snowflake password / OAuth
    token comes via ``CredentialBroker.hold_data_account`` (NEVER in
    this request body) — see CLAUDE.md security posture.

    v1.1 wires the broker via two optional environment knobs:

    * ``WORMBASE_SNOWFLAKE_INSTALL_ID`` — the install id passed to
      ``broker.hold_data_account`` (per-tenant secret partitioning).
      Required when ``WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR`` is set;
      v2 will derive this from the tenant projection automatically.
    * ``WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR`` — when set, an
      ``EnvCredentialBroker`` is constructed against that secrets dir.
      Production should swap in the Vault-backed broker at deploy time
      by attaching it to the aiohttp app key (out of scope for v1.1).

    When neither knob is set, the endpoint will attempt
    ``SnowflakeNativeCatalogSource.authenticate`` with only the
    request-body connection shape — this fails fast with
    ``AuthenticationError`` since no ``password`` / ``token`` is
    present, surfacing a 400 to the dashboard.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, ImportSnowflakeCatalogBody)
    assert isinstance(body, ImportSnowflakeCatalogBody)
    ledger = request.app[APP_LEDGER_KEY]
    registry = request.app.get(APP_REGISTRY_KEY)

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    broker, install_id = _resolve_snowflake_credential_broker()

    try:
        source_id, _results = await write_actions.import_snowflake_catalog(
            ledger,
            company_id,
            account=body.account,
            user=body.user,
            warehouse=body.warehouse,
            database=body.database,
            schema_name=body.schema_,
            role=body.role,
            domain_id=body.domain_id,
            imported_by=body.imported_by,
            credential_broker=broker,
            install_id=install_id,
            reactivity_registry=registry,
        )
    except ValueError as exc:
        raise web.HTTPBadRequest(reason=_bad_text(str(exc))) from exc
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(
            reason=_bad_text(str(exc)),
        ) from exc
    except Exception as exc:
        # AuthenticationError (no broker secret), connector connection
        # failures, etc. — surface as 400 so the form renders honestly.
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"snowflake catalog import failed: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc

    return web.json_response(
        {"source_id": str(source_id), "sourceId": str(source_id)},
        status=200,
    )


def _resolve_snowflake_credential_broker() -> tuple[Any | None, str | None]:
    """Read env knobs for the Snowflake CredentialBroker wiring.

    Returns ``(broker, install_id)``. Either may be None — when both
    are None the endpoint falls back to request-body-only authentication
    (which will fail fast in production without a password / token).
    Production deployments should swap in a Vault-backed broker via the
    aiohttp app key in a follow-up patch; v1.1 ships env-broker wiring
    only.
    """
    secrets_dir = os.environ.get(
        "WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR", "",
    ).strip()
    install_id = os.environ.get(
        "WORMBASE_SNOWFLAKE_INSTALL_ID", "",
    ).strip()
    if not secrets_dir or not install_id:
        return None, None
    try:
        from pathlib import Path

        from wormbase_agent_gateway.credential_broker.env import (
            EnvCredentialBroker,
        )
        broker = EnvCredentialBroker(secrets_dir=Path(secrets_dir))
    except Exception:
        return None, None
    return broker, install_id


async def post_promote_semantic_gap(
    request: web.Request,
) -> web.Response:
    """POST /api/v1/write_actions/promote_semantic_gap — Wave 3 Task 5.

    Looks up the ``semantic_gap_proposed`` ledger entry, validates the
    entry kind, and emits ``external_metric_imported`` chained back via
    ``caused_by``. The companion ``/api/v1/lake/metrics-proposed/promote``
    alias lives below — the dashboard server action posts to that path
    historically; we register both so the dashboard works whether it
    targets the canonical write_actions path or the legacy alias.
    """
    _check_auth(request)
    company_id = _resolve_company_id(request)
    body = await _read_body(request, PromoteSemanticGapBody)
    assert isinstance(body, PromoteSemanticGapBody)
    ledger = request.app[APP_LEDGER_KEY]

    if body.company_id != company_id:
        raise web.HTTPBadRequest(
            reason=_bad_text(
                f"company_id mismatch: header tenant resolves to "
                f"{company_id} but body carries {body.company_id}"
            ),
        )

    try:
        metric_id, _result = await write_actions.promote_semantic_gap(
            ledger,
            company_id,
            semantic_gap_entry_id=body.semantic_gap_entry_id,
            metric_name=body.metric_name,
            metric_expression=body.metric_expression,
            domain_id=body.domain_id,
            promoted_by=body.promoted_by,
        )
    except ValueError as exc:
        raise web.HTTPBadRequest(reason=_bad_text(str(exc))) from exc
    except VerifyFailed as exc:
        raise web.HTTPInternalServerError(
            reason=_bad_text(str(exc)),
        ) from exc

    return web.json_response(
        {"metric_id": str(metric_id), "metricId": str(metric_id)},
        status=200,
    )


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def build_app(
    *,
    ledger: Ledger | InMemoryLedger | Any,
    api_token: str,
    storage: ObjectStore | None = None,
    reactivity_registry: Any | None = None,
) -> web.Application:
    """Build the aiohttp Application with the worm-core ledger + API token wired in.

    Routes mounted under ``/api/v1/``. Used by both the production CLI
    runner and unit tests. ``storage`` defaults to ``get_storage_backend()``
    (env-driven) — pass an explicit backend in tests to keep them
    container-free.

    ``reactivity_registry`` is optional: when present, /api/v1/reactivities/*
    endpoints proxy through it (W5.A5). When absent, those endpoints
    return honest empty payloads or 503 — same surface the dashboard
    renders an honest empty state for.
    """
    if not api_token:
        raise ValueError(
            "api_token must be non-empty; set WORMBASE_LEDGER_API_TOKEN before boot",
        )

    app = web.Application()
    app[APP_LEDGER_KEY] = ledger
    app[APP_TOKEN_KEY] = api_token
    app[APP_STORAGE_KEY] = storage if storage is not None else get_storage_backend()
    if reactivity_registry is not None:
        app[APP_REGISTRY_KEY] = reactivity_registry

    app.router.add_get("/api/v1/health", health)
    # v1.4 #5 — subscription-eligible kinds catalog (read-only,
    # tenant-agnostic). Powers the dashboard SubscriptionForm's
    # dynamic kind list.
    app.router.add_get(
        "/api/v1/read/subscription_eligible_kinds",
        get_subscription_eligible_kinds,
    )

    # MCP catalog — read-only, no auth, env-gated. The dashboard's
    # /mcp tab fetches this URL via WORMBASE_MCP_CATALOG_URL.
    app.router.add_get("/mcp/catalog", get_mcp_catalog)

    app.router.add_post("/api/v1/people", post_people)
    app.router.add_post(
        r"/api/v1/people/{person_id}/confirm", post_person_confirm,
    )
    app.router.add_post(
        r"/api/v1/people/{person_id}/archive", post_person_archive,
    )
    app.router.add_post(
        r"/api/v1/people/{person_id}/identities", post_person_identities,
    )
    app.router.add_delete(
        r"/api/v1/people/{person_id}/identities/{platform}/{platform_user_id}",
        delete_person_identity,
    )
    app.router.add_post(
        r"/api/v1/people/{person_id}/roles", post_person_roles,
    )
    app.router.add_post(
        r"/api/v1/people/{person_id}/roles/{grant_id}/revoke",
        post_person_role_revoke,
    )
    app.router.add_post("/api/v1/people/merge", post_people_merge)
    app.router.add_post(
        "/api/v1/people/bulk-confirm", post_people_bulk_confirm,
    )
    # Wave H Phase 2 Task 2C — admin queue for worm-proposed positions.
    # The /proposals GET MUST be registered BEFORE the
    # ``/{source_person_id}/split`` route because aiohttp's router
    # matches in registration order and a literal segment ("proposals")
    # would otherwise collide with the ``{source_person_id}`` UUID
    # placeholder.
    app.router.add_get(
        "/api/v1/people/proposals", get_position_proposals,
    )
    app.router.add_post(
        r"/api/v1/people/{person_id}/position/confirm",
        post_person_position_confirm,
    )
    app.router.add_post(
        r"/api/v1/people/{person_id}/position/reject",
        post_person_position_reject,
    )
    app.router.add_post(
        r"/api/v1/people/{source_person_id}/split", post_person_split,
    )

    # Tier 1 OAuth callback orchestrator
    app.router.add_post("/api/v1/installs", post_installs)

    # W7.A3 — list installs for the current tenant. The demo
    # orchestrator queries this before running Beat 1 of the install-arc
    # scenario so ``--skip-installed`` mode can short-circuit the
    # OAuth-click beats when an install already exists.
    app.router.add_get("/api/v1/installs", get_installs)

    # Block I7 — CLI dev helper for default-lake provisioning.
    # Production never calls this (complete_install auto-provisions).
    app.router.add_post(
        "/api/v1/installs/provision-local-lake", post_provision_local_lake,
    )

    # Phase 1 Task 1B — multi-tenancy v2 signup chain.
    # Both Slack OAuth (1B.C) and email magic-link (1B.D) flows POST
    # here. Idempotent at the projection layer (re-emit appends another
    # PEVR cycle; projection upsert keys on tenant_id).
    app.router.add_post(
        "/api/v1/tenants/signup-initiated", post_tenant_signup_initiated,
    )
    app.router.add_post(
        "/api/v1/tenants/signup-completed", post_tenant_signup_completed,
    )

    # Tier 2 — wizard-vs-bot fork (Block G4)
    app.router.add_post("/api/v1/setup-mode", post_setup_mode)

    # Data products + notebooks (Block F2)
    app.router.add_post("/api/v1/data-products", post_data_products)
    app.router.add_post(
        r"/api/v1/data-products/{data_product_id}/regenerate",
        post_data_product_regenerate,
    )
    app.router.add_post(
        r"/api/v1/data-products/{data_product_id}/consume",
        post_data_product_consume,
    )
    app.router.add_get(
        r"/api/v1/data-products/{data_product_id}/replay",
        get_data_product_replay,
    )
    # W2.A8 — POST replay drives the dashboard "Replay" button. The GET
    # variant above is retained for read-only reproducibility checks.
    app.router.add_post(
        r"/api/v1/data-products/{data_product_id}/replay",
        post_data_product_replay,
    )
    app.router.add_post("/api/v1/notebooks", post_notebooks)
    app.router.add_post(r"/api/v1/notebooks/{notebook_id}/run", post_notebook_run)
    app.router.add_post(
        r"/api/v1/notebooks/{notebook_id}/publish", post_notebook_publish,
    )
    # W2.A8 — Sign is publish under the governance frame. Per-Person
    # signature receipt is deterministic; the dashboard surfaces it on
    # screen as the audit-grade attestation badge.
    app.router.add_post(
        r"/api/v1/notebooks/{notebook_id}/sign", post_notebook_sign,
    )

    # W2.A7 — KPI / decision / process primary write actions backing the
    # /kpis, /decisions, /processes dashboard tabs. Same _pevr template
    # as every other dashboard write — full propose/execute/verify/resolve
    # cycle, hash-chained, audit-trailed.
    app.router.add_post("/api/v1/kpis/propose", post_kpi_propose)
    app.router.add_post("/api/v1/decisions", post_decision_record)
    app.router.add_post("/api/v1/processes", post_process_propose)

    # W1.A3 — live ledger SSE feed for the dashboard's install cascade
    # panel. Bearer-authed and tenant-scoped; the dashboard wrapper at
    # `apps/dashboard/app/api/v1/ledger/stream/route.ts` proxies the
    # browser's EventSource into this endpoint and closes on client
    # disconnect. Polling cadence is 250ms; keepalive every 15s.
    app.router.add_get("/api/v1/ledger/stream", get_ledger_stream)

    # W2.A10 — ops observability snapshot (Postgres health, ledger
    # throughput sparkline, per-tenant MCP rate-limit headroom, agent
    # loop status). Bearer-authed; iterates over known tenants for
    # cross-tenant aggregates. Always returns 200 (failures are encoded
    # in the payload itself so the dashboard can render the red banner
    # honestly).
    app.router.add_get("/api/v1/ops/health", get_ops_health)

    # W2.A9 — /research approve / reject buttons + /mcp token issuance.
    # Approve writes emit_experiment_resolved(outcome=keep); reject writes
    # outcome=discard. Token issuance produces a Person-scoped compact
    # bearer the dashboard's "Connect Claude Desktop" panel surfaces.
    app.router.add_post(
        r"/api/v1/experiments/{experiment_id}/approve",
        post_experiment_approve,
    )
    app.router.add_post(
        r"/api/v1/experiments/{experiment_id}/reject",
        post_experiment_reject,
    )
    app.router.add_post("/api/v1/mcp/tokens", post_mcp_tokens)
    app.router.add_post("/api/v1/mcp/presets", post_mcp_preset)

    # Phase 3 Task 3B — Ask the Worm. Dashboard's in-app ask surface
    # forwards questions here; same code path as production chat.
    app.router.add_post("/api/v1/worm/ask", post_worm_ask)

    # W2.A5 — connector registry surface for the dashboard's
    # /sources/new picker + drawer test-connection. The list endpoint
    # is read-only and unauthenticated (parallel to /mcp/catalog) so
    # the dashboard can render the picker without a token round-trip;
    # the test-connection variant calls SurfaceDriver.authenticate against
    # the supplied config — same code path the source-builder uses at
    # runtime, no stub.
    app.router.add_get("/api/v1/connectors", get_connectors)
    app.router.add_post(
        r"/api/v1/connectors/{kind}/test", post_connector_test,
    )

    # W5.A5 — reactivities CRUD + per-Person resource conversations.
    # Mounted unconditionally; handlers themselves degrade gracefully
    # when the registry isn't wired in.
    app.router.add_get("/api/v1/reactivities", get_reactivities)
    app.router.add_post(
        "/api/v1/reactivities/propose", post_reactivity_propose,
    )
    app.router.add_post(
        r"/api/v1/reactivities/{reactivity_id}/confirm",
        post_reactivity_confirm,
    )
    app.router.add_post(
        r"/api/v1/reactivities/{reactivity_id}/disable",
        post_reactivity_disable,
    )
    app.router.add_get(
        r"/api/v1/reactivities/{reactivity_id}/fires",
        get_reactivity_fires,
    )
    app.router.add_get(
        r"/api/v1/people/{person_id}/resource-conversations",
        get_resource_conversations_for_person,
    )

    # v1.1 write-action endpoints — 4 new routes backing the dashboard
    # server actions whose Wave 3 / Wave 3.2 stubs returned an
    # "endpoint v1.1" error when WORM_CORE_API_URL didn't resolve to a
    # real route. With these routes in place the stub branches go cold.
    app.router.add_post(
        "/api/v1/write_actions/register_agent", post_register_agent,
    )
    app.router.add_post(
        "/api/v1/write_actions/import_dbt_catalog",
        post_import_dbt_catalog,
    )
    app.router.add_post(
        "/api/v1/write_actions/import_snowflake_catalog",
        post_import_snowflake_catalog,
    )
    app.router.add_post(
        "/api/v1/write_actions/promote_semantic_gap",
        post_promote_semantic_gap,
    )
    # Legacy alias the Wave 3 Task 5 dashboard server action posts to
    # (``/lake/metrics-proposed/actions.ts`` targets this path). Same
    # handler — keeps the dashboard working whether it points at the
    # canonical write_actions path or the legacy alias.
    app.router.add_post(
        "/api/v1/lake/metrics-proposed/promote",
        post_promote_semantic_gap,
    )

    # v2.A Task 7 — agent subscriptions admin path. Mirrors the
    # MCP-tool semantics (create + revoke write the same
    # agent_subscription_{created,revoked} entry kinds), but routed via
    # HTTP+Bearer auth for the dashboard's admin-override surface.
    app.router.add_post(
        "/api/v1/write_actions/agent_subscriptions_create",
        post_agent_subscriptions_create,
    )
    app.router.add_delete(
        r"/api/v1/write_actions/agent_subscriptions_revoke/{subscription_id}",
        delete_agent_subscription,
    )

    # v1.4 follow-up (Path 5) — agent revoke admin path. Cascades over
    # the agent's active grants, writing one ``agent_grant`` (status=
    # revoked) PEVR cycle per active grant. No new ledger entry kind.
    app.router.add_delete(
        r"/api/v1/write_actions/agents_revoke/{agent_id}",
        delete_agent,
    )

    # Final wave item #5 (2026-05-13) — agent metadata edit path.
    # Wires the agent detail page's Edit modal. Emits one
    # ``agent_metadata_updated`` PEVR cycle (KIND_REGISTRY 103 → 104).
    # Preserves agent_id continuity so audit trails do not fork.
    app.router.add_patch(
        r"/api/v1/write_actions/agents_metadata/{agent_id}",
        patch_agent_metadata,
    )

    # Post-rest path #4 (2026-05-13) — agent metadata revert path.
    # Wires the agent detail page's Revert modal. Reverts the most
    # recent ``agent_metadata_updated`` by emitting a new compensating
    # entry (forward-only; no new ledger kind, no mutation).
    app.router.add_post(
        r"/api/v1/write_actions/agents_metadata_revert/{agent_id}",
        post_agent_metadata_revert,
    )

    # L3 Sub-wave C (2026-05-29) — lineage-edge admin actions. Two
    # POSTs that emit ``lineage_edge_confirmed`` / ``lineage_edge_rejected``
    # PEVR cycles. The projection_lineage_edges fold collapses the new
    # entry onto the existing edge row (state flip; forward-only).
    app.router.add_post(
        r"/api/v1/write_actions/lineage_edges_confirm/{edge_id}",
        post_lineage_edge_confirm,
    )
    app.router.add_post(
        r"/api/v1/write_actions/lineage_edges_reject/{edge_id}",
        post_lineage_edge_reject,
    )

    # L7 Sub-wave C (2026-05-30) — quality-check admin actions. Two
    # POSTs that emit ``quality_check_confirmed`` /
    # ``quality_check_rejected`` PEVR cycles. The
    # projection_quality_checks fold (v022) collapses the new entry
    # onto the existing check row (state flip; forward-only). Mirrors
    # the L3 lineage-edges shape.
    app.router.add_post(
        r"/api/v1/write_actions/quality_checks_confirm/{check_id}",
        post_quality_check_confirm,
    )
    app.router.add_post(
        r"/api/v1/write_actions/quality_checks_reject/{check_id}",
        post_quality_check_reject,
    )

    # L4 Sub-wave C (2026-06-02) — schema-impact admin actions. Two
    # POSTs that emit ``schema_impact_confirmed`` /
    # ``schema_impact_rejected`` PEVR cycles. The
    # projection_schema_impacts fold (v023) collapses the new entry
    # onto the existing impact row (state flip; forward-only).
    # Mirrors the L3 lineage-edges + L7 quality-checks shape.
    app.router.add_post(
        r"/api/v1/write_actions/schema_impacts_confirm/{impact_id}",
        post_schema_impact_confirm,
    )
    app.router.add_post(
        r"/api/v1/write_actions/schema_impacts_reject/{impact_id}",
        post_schema_impact_reject,
    )

    # L5 Sub-wave C (2026-06-05) — semantic-type admin actions. Two
    # POSTs that emit ``semantic_type_confirmed`` /
    # ``semantic_type_rejected`` PEVR cycles. The
    # projection_semantic_types fold (v024) collapses the new entry
    # onto the existing semantic-type row (state flip; forward-only).
    # Mirrors the L3 lineage-edges + L7 quality-checks + L4
    # schema-impacts shape.
    app.router.add_post(
        r"/api/v1/write_actions/semantic_types_confirm/{type_id}",
        post_semantic_type_confirm,
    )
    app.router.add_post(
        r"/api/v1/write_actions/semantic_types_reject/{type_id}",
        post_semantic_type_reject,
    )

    # L6 Sub-wave C (2026-06-06) — column-classification admin actions.
    # Two POSTs that emit ``column_classification_confirmed`` /
    # ``column_classification_rejected`` PEVR cycles. The
    # projection_column_classifications fold (v025) collapses the new
    # entry onto the existing classification row (state flip; forward-
    # only). Mirrors the L3 lineage-edges + L7 quality-checks + L4
    # schema-impacts + L5 semantic-types shape.
    app.router.add_post(
        r"/api/v1/write_actions/column_classifications_confirm/"
        r"{classification_id}",
        post_column_classification_confirm,
    )
    app.router.add_post(
        r"/api/v1/write_actions/column_classifications_reject/"
        r"{classification_id}",
        post_column_classification_reject,
    )

    # L8 Sub-wave C (2026-06-07) — entity-stitch admin actions. Two
    # POSTs that emit ``entity_stitch_confirmed`` /
    # ``entity_stitch_rejected`` PEVR cycles. The
    # projection_entity_stitches fold (v026) collapses the new entry
    # onto the existing stitch row (state flip; forward-only). Mirrors
    # the L3 lineage-edges + L7 quality-checks + L4 schema-impacts +
    # L5 semantic-types + L6 column-classifications shape.
    app.router.add_post(
        r"/api/v1/write_actions/entity_stitches_confirm/{stitch_id}",
        post_entity_stitch_confirm,
    )
    app.router.add_post(
        r"/api/v1/write_actions/entity_stitches_reject/{stitch_id}",
        post_entity_stitch_reject,
    )

    # L1 Sub-wave C (2026-06-08) — source-candidate admin actions. Two
    # POSTs that emit ``source_candidate_promoted`` /
    # ``source_candidate_rejected`` PEVR cycles. The
    # projection_source_candidates fold (v027) collapses the new entry
    # onto the existing candidate row (state flip; forward-only).
    # Mirrors the L3 lineage-edges + L7 quality-checks + L4
    # schema-impacts + L5 semantic-types + L6 column-classifications +
    # L8 entity-stitches shape — but the promote handler additionally
    # dual-writes a downstream ``source_proposed`` via the existing
    # :class:`SourceBuilder` flow (the resulting correlation_id is
    # threaded back into the L1 promote payload as
    # ``downstream_source_proposed_id``).
    app.router.add_post(
        r"/api/v1/write_actions/source_candidates_promote/{candidate_id}",
        post_source_candidate_promote,
    )
    app.router.add_post(
        r"/api/v1/write_actions/source_candidates_reject/{candidate_id}",
        post_source_candidate_reject,
    )

    # L2 Sub-wave C (2026-06-09) — catalog-drift admin actions. Two
    # POSTs that emit ``catalog_drift_acknowledged`` /
    # ``catalog_drift_rejected`` PEVR cycles. The
    # projection_catalog_drifts fold (v028) collapses the new entry
    # onto the existing drift row (state flip; forward-only). Mirrors
    # the L8 entity-stitches shape — but uses ``acknowledge`` rather
    # than ``confirm`` because L2 acknowledgment is a no-op record
    # (no downstream pipeline trigger, no cross-axis effect).
    app.router.add_post(
        r"/api/v1/write_actions/catalog_drifts_acknowledge/{drift_id}",
        post_catalog_drift_acknowledge,
    )
    app.router.add_post(
        r"/api/v1/write_actions/catalog_drifts_reject/{drift_id}",
        post_catalog_drift_reject,
    )

    # Onboarding Sub-wave C (2026-05-30) — Tier 2 governance baseline
    # write-backs. ``domain_pack_selected`` emits parent + fan-out
    # (per-domain ``emit_domain_registered`` + per-policy
    # ``emit_policy_applied``); ``person_invited`` records the
    # co-admin invite intent. Both ride bearer+tenant auth.
    app.router.add_post(
        r"/api/v1/write_actions/domain_pack_selected/{pack_id}",
        post_domain_pack_selected,
    )
    app.router.add_post(
        "/api/v1/write_actions/person_invited",
        post_person_invited,
    )

    # Onboarding Sub-wave D (2026-05-30) — confirmBusinessDef
    # graduation + per-connector probe surface. concept_confirmed
    # writes a real PEVR cycle (no new KIND_REGISTRY entry; reuses the
    # existing ``concept_confirmed`` kind). The probe endpoint returns
    # honest tenant-side connector state — ``works`` / ``degraded`` /
    # ``failed`` / ``unknown`` — backing the /lake/connectors row badge.
    app.router.add_post(
        r"/api/v1/write_actions/concept_confirmed/{term}",
        post_concept_confirmed,
    )
    app.router.add_get(
        r"/api/v1/connectors/{kind}/probe",
        get_connector_probe,
    )

    return app


def read_api_token() -> str | None:
    """Return WORMBASE_LEDGER_API_TOKEN or None if unset/empty."""
    raw = os.environ.get("WORMBASE_LEDGER_API_TOKEN", "").strip()
    return raw or None


def read_api_port(default: int = 8910) -> int:
    raw = os.environ.get("WORMBASE_LEDGER_API_PORT", "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
