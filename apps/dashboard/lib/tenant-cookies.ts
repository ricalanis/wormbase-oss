/**
 * Server-side helpers for resolving the current tenant from request cookies.
 *
 * RSCs (most dashboard pages) call `getTenantFromCookies()` which reads
 * (in priority order):
 *
 *   1. The signed `wormbase-session` cookie (Phase 1B.E — multi-tenancy
 *      v2). Decoded with `WORMBASE_LEDGER_API_TOKEN`; rejected on
 *      tamper/expiry.
 *   2. The legacy `wormbase-tenant-slug` cookie (unsigned). Honored for
 *      one release window; will be deleted in Phase 4.
 *
 * If neither resolves, falls back to the default tenant. Never throws —
 * every dashboard route gets a valid tenant.
 */
import { cookies } from "next/headers";
import {
  findTenantBySlug,
  getDefaultTenant,
  type Tenant,
} from "./tenants";
import {
  SESSION_COOKIE_NAME,
  decodeSessionCookie,
} from "./server/auth/session";

export const TENANT_COOKIE_NAME = "wormbase-tenant-slug";

/**
 * Read the tenant from request cookies. Prefers the signed session
 * cookie when present; falls back to the legacy slug cookie; finally
 * falls back to the default tenant.
 *
 * Async to remain compatible with Next 15's async `cookies()` API.
 */
export async function getTenantFromCookies(): Promise<Tenant> {
  try {
    const store = await cookies();
    // 1. Prefer the signed session cookie (Phase 1B.E).
    const sessionRaw = store.get(SESSION_COOKIE_NAME)?.value ?? null;
    if (sessionRaw) {
      const secret = (process.env.WORMBASE_LEDGER_API_TOKEN ?? "").trim();
      if (secret) {
        const claims = decodeSessionCookie(sessionRaw, { secret });
        if (claims !== null) {
          const t = findTenantBySlug(claims.tenantSlug);
          if (t) return t;
        }
      }
    }
    // 2. Legacy unsigned slug cookie. Honored until Phase 4 polish.
    const slug = store.get(TENANT_COOKIE_NAME)?.value ?? null;
    return findTenantBySlug(slug) ?? getDefaultTenant();
  } catch {
    // Outside a request scope (e.g. static generation) — fall back.
    return getDefaultTenant();
  }
}

/**
 * Convenience: just the company UUID for the current tenant.
 */
export async function getCurrentCompanyId(): Promise<string> {
  return (await getTenantFromCookies()).companyId;
}
