/**
 * Tenant registry + slug → company_id derivation.
 *
 * Mirrors `apps/channel-adapter/src/wormbase_channel_adapter/tenant.py` and
 * `apps/worm-core/src/wormbase_core/service.py` — every consumer that wants
 * to look up a tenant by slug derives the same UUID by computing UUIDv5 of
 * the slug under the same namespace.
 *
 * Two known tenants ship with the dashboard:
 *   - `baseworm`   — the demo Slack workspace (default)
 *   - `democorp`   — a clean second tenant, used to demonstrate multi-tenant
 *                     isolation. Provision via `wormbase demo seed --tenant democorp`.
 *
 * A future "list tenants from `tenants` table" Postgres path is wired below;
 * if no such table exists we fall back to the hard-coded list. This survives
 * the demo today and gives a slot to grow into.
 */
// NOTE: this module is imported by client components (TenantSwitcher,
// TenantProvider). Do NOT import `node:crypto` or any other Node-only
// module here. UUIDv5 derivation lives in `tenants-derive.ts` and is
// invoked server-side only (e.g. when admin tools provision a new tenant);
// the dashboard's runtime tenant list is precomputed below.

export const WORMBASE_TENANT_NAMESPACE =
  "6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f";

export interface Tenant {
  slug: string;
  companyId: string;
  displayName: string;
}

/**
 * Pre-computed UUIDv5 of each known tenant slug under
 * WORMBASE_TENANT_NAMESPACE. Verified to match
 * `apps/channel-adapter/.../tenant.py` and `apps/worm-core/.../service.py`.
 * Add a new tenant by:
 *   1. seeding it: `wormbase demo seed --tenant <slug>`
 *   2. running scripts/derive-tenant-uuid.mjs to compute the UUID
 *   3. appending the entry below
 */
const KNOWN_TENANTS: ReadonlyArray<Tenant> = [
  {
    slug: "baseworm",
    displayName: "Baseworm",
    companyId: "a8989ece-b38a-5811-9625-327a79a65f90",
  },
  {
    slug: "democorp",
    displayName: "Democorp",
    companyId: "f9e1af07-371f-538b-bdde-cec81bcb6196",
  },
  // Demo carousel tenants seeded by `wormbase demo seed --demo-tenants`
  // (Phase 1B.G). Magic-link evaluators are assigned to one of these via
  // round-robin in /api/auth/email/confirm. UUIDs derived via
  // scripts/derive-tenant-uuid.mjs against WORMBASE_TENANT_NAMESPACE.
  {
    slug: "wormbase-saas-demo",
    displayName: "WormBase SaaS Demo",
    companyId: "6206d469-bbf1-53e2-8b8b-d651acc8a8d3",
  },
  {
    slug: "wormbase-fintech-demo",
    displayName: "WormBase Fintech Demo",
    companyId: "9794ee37-90ac-5ca1-8055-a42a377833c6",
  },
  {
    slug: "wormbase-marketplace-demo",
    displayName: "WormBase Marketplace Demo",
    companyId: "8b69f089-8491-54b3-9fd2-6413642cc377",
  },
  {
    slug: "wormbase-ecommerce-demo",
    displayName: "WormBase Ecommerce Demo",
    companyId: "8ea97d06-4c2d-5eb5-9d51-091d01de5479",
  },
  {
    slug: "wormbase-agency-demo",
    displayName: "WormBase Agency Demo",
    companyId: "c9f8e4b3-9c68-5c6c-98f1-99a6959c8d89",
  },
];

/**
 * Look up a tenant's company id from its slug. Client-safe: uses the
 * precomputed map. Throws if the slug isn't registered — call sites in
 * the dashboard always pass slugs from `KNOWN_TENANTS`.
 */
export function tenantToCompanyUuid(slug: string): string {
  const normalized = slug.trim().toLowerCase();
  if (!normalized) throw new Error("tenant slug must be non-empty");
  const found = KNOWN_TENANTS.find((t) => t.slug === normalized);
  if (!found) {
    throw new Error(
      `tenant slug "${normalized}" not registered; run derive-tenant-uuid.mjs and add it to KNOWN_TENANTS`,
    );
  }
  return found.companyId;
}

export const DEFAULT_TENANT_SLUG = "baseworm";

export function getDefaultTenant(): Tenant {
  return (
    KNOWN_TENANTS.find((t) => t.slug === DEFAULT_TENANT_SLUG) ?? KNOWN_TENANTS[0]
  );
}

export function findTenantBySlug(slug: string | null | undefined): Tenant | null {
  if (!slug) return null;
  const s = slug.trim().toLowerCase();
  return KNOWN_TENANTS.find((t) => t.slug === s) ?? null;
}

/**
 * List known tenants. Future Postgres path: introspect a `tenants` table or
 * `SELECT DISTINCT company_id FROM ledger`. For now we return the hard-coded
 * list — the demo only needs baseworm + democorp, and any new tenant must be
 * seeded explicitly via the sim-harness CLI before it shows up here anyway.
 */
export async function listKnownTenants(): Promise<Tenant[]> {
  return [...KNOWN_TENANTS];
}

/** Synchronous variant — no Postgres path; used in client/component code. */
export function listKnownTenantsSync(): Tenant[] {
  return [...KNOWN_TENANTS];
}
