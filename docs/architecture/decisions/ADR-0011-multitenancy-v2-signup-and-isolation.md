# ADR-0011: Multi-tenant signup, session, and isolation model

**Status:** Accepted
**Date:** 2026-05-04

## Context

WormBase's substrate is multi-tenant from day one: every ledger entry
carries `company_id`; `tenantSlugFor(platform, workspaceId)` produces
deterministic UUIDv5 slugs; cross-tenant data-leak tests pin row-level
isolation. By mid-2026 the substrate was multi-tenant but the **product
surface** still carried single-operator assumptions: a hardcoded
`KNOWN_TENANTS` array of two tenants, an unsigned `wormbase-tenant-slug`
cookie that any user could set to any value via the `/login` page, and
no canonical signup ledger flow that distinguished "this tenant signed up
via Slack OAuth" from "this tenant was assigned to an evaluator via
magic-link to a demo carousel."

The system needed a canonical signup model that wrote auditable ledger
entries, a signed session cookie that resisted forgery, an MCP token gate
that asserted the bound Person actually existed in the bound tenant, and
a demo-tenant strategy that scaled beyond one shared workspace.

## Decision

WormBase's multi-tenancy v2 lands as a focused wave that grafts a
canonical signup flow on top of the existing OAuth + Install machinery,
plus a magic-link side-door for evaluators:

### Tenant identity

One tenant per Slack workspace. Slug is `slack_team_{team_id.lower()}`;
tenant UUID is `uuid5(WORMBASE_TENANT_NAMESPACE, slug)`. Three-way parity
between worm-core (`service.py:tenant_to_uuid`), dashboard
(`tenants-derive.ts:deriveTenantCompanyId`), and channel-adapter
(`tenant.py`) keeps SaaS, local, and demo deployments hash-stable.

### Signup framing as ledger entries

Two new entry kinds: `tenant_signup_initiated` and
`tenant_signup_completed`. Every signup writes the canonical pair, with
`signup_source ∈ {slack_oauth, email_magic_link, demo_seed,
bootstrapped}`. A new `projection_tenants` table folds the signup entries
into queryable rows carrying `tenant_id`, `slug`, `display_name`,
`signup_source`, `signup_email`, `created_at`, `signup_completed_at`,
`status`, and a `demo_visitors` JSONB array.

### Slack OAuth flow

Two redirect URIs (`/onboarding/oauth/slack/callback` for onboarding,
`/api/auth/slack/callback` for sign-in / re-auth) share a single backend
helper. The helper branches on `projection_tenants`: no row → signup
chain; existing active row → re-auth path (idempotent
`completeInstall`); existing suspended row → 403.

### Email magic-link side-door

`POST /api/auth/email/request` mints a 15-minute scoped token, emits
`tenant_signup_initiated`, and returns the link (in production, via SMTP
through a `MagicLinkSender` Protocol; in dev mode, in the response JSON).
`GET /api/auth/email/confirm?token=...` decodes the token, assigns a
demo tenant via round-robin over evaluators' history, emits
`tenant_signup_completed` with `assigned_tenant_slug`, and binds a
session cookie. The evaluator gets `tenancy.observer` — read-only access.

### Signed session cookie

`wormbase-session` replaces the unsigned `wormbase-tenant-slug` cookie.
Compact signed blob carrying `{person_id, tenant_slug, exp}`, signed with
the same secret as MCP Person tokens (one rotation surface). `httpOnly`,
server-side-only validation. The legacy cookie stays honored for one
release as a soft fallback.

### MCP token tenant-scoping

`authorize_caller` adds a projection-read gate: when a compact token
claims `(person_id, tenant_slug)`, `projection_persons` MUST contain an
unrevoked Person at `(person_id, tenant_id = tenant_to_uuid(tenant_slug))`.
A token forged with the right secret but an arbitrary `person_id` is now
rejected at the auth layer, not just at the role-filter layer. Audit
entries stop polluting `projection_mcp_calls` with phantom callers.

### Demo tenant carousel

Five themed demo tenants seeded via `wormbase demo seed --demo-tenants`:
`wormbase-saas-demo`, `wormbase-fintech-demo`, `wormbase-marketplace-demo`,
`wormbase-ecommerce-demo`, `wormbase-agency-demo`. Each carries a
recorded JSONL of ~50-100 wire events that wire-replay can use to bring
the tenant from freshly-installed to 30-day-old worm deterministically.
Magic-link assignment is round-robin over evaluators' `demo_visitors`
history.

### Tenant lifecycle scope

Create-only for this wave. Suspend, delete, and export are explicitly
deferred to a later polish wave with reserved-but-unregistered entry
kinds (the doctrine says kinds are forever; no names get reserved
without an implementation).

## Consequences

**Positive:**

- Multi-tenancy at the product layer matches the substrate's
  multi-tenancy. The hardcoded `KNOWN_TENANTS` array becomes a
  fallback for un-Postgres'd local dev; the source of truth is
  `projection_tenants`.
- Every signup is auditable: dashboard can answer "how did this tenant
  arrive?" by reading `signup_source` and `signup_email` from
  `projection_tenants`.
- Session cookies are signed; MCP tokens are projection-gated. The
  cross-tenant data-leak contract gets crisper, not just defensible.
- Demo tenants are real production tenants with `signup_source='demo_seed'`,
  not toy fixtures. Same code path, different `signup_source` tag.

**Negative:**

- Net new entry kinds: 2 (`tenant_signup_initiated`,
  `tenant_signup_completed`). The doctrine's cumulative kind count
  advances toward its raised threshold; the freeze-pause review must
  account for these.
- Two redirect URIs for the same OAuth callback (onboarding vs sign-in)
  is a minor URL-surface complication. The shared helper keeps the logic
  in one place but the URI duplication is real.
- The legacy `wormbase-tenant-slug` cookie stays honored as a soft
  fallback for one release. Two cookies coexist for a release window;
  the new one wins when both are present.

**Neutral:**

- The default `MagicLinkSender` is `LogOnlySender` — prints the link to
  stderr. SMTP / SES / SendGrid integration is a future polish task. The
  Protocol surface is shipped now; the production sender slots in later.
- Demo tenant reset is a future polish task (nightly cron that wipes
  `demo_visitors` and replays the seed JSONL). Demo state accumulates
  until reset.
- Suspend / delete / export entry-kind names (`tenant_suspended`,
  `tenant_deleted`, `tenant_exported`) are **not** reserved in advance.
  Per doctrine, kinds are forever; we don't reserve names without an
  implementation.

## Cross-references

- Related ADRs: ADR-0002 (the MCP server whose bearer-token gate this
  decision tightens); ADR-0007 (the identity model whose Person + Install
  rows the signup flow writes).
- Architecture: `ARCHITECTURE.md` §5 ("Identity model") and §7 ("Install
  lifecycle") describe the substrate this decision extends to a real
  multi-tenant product surface.
