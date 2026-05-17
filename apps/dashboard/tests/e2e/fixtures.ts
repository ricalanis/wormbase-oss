/**
 * Shared E2E fixtures (W6.A5).
 *
 * Two responsibilities:
 *
 *   1. Skip-when-stack-down. Each spec uses `test` from this module, which
 *      consults the global-setup sentinel and short-circuits with a clean
 *      `test.skip()` and an honest reason when the dashboard isn't reachable.
 *
 *   2. Tenant + role plumbing. `roleContext(role)` returns a fresh browser
 *      context with the tenant cookie planted plus a hint cookie naming the
 *      role lens. The dashboard's role-aware chrome reads role from the
 *      ledger Person row in production; for E2E we plant a short-lived
 *      `wb-role-hint` cookie that the test harness recognises (and that the
 *      production code ignores when not in test mode).
 *
 * Selectors are surfaced as `tid(name)` helpers (and direct
 * `page.getByTestId` calls) so the spec text reads as user intent rather
 * than a CSS-class soup. CSS-class dependency is forbidden by the W6.A5 quality
 * bar.
 */
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

import {
  test as base,
  expect,
  type BrowserContext,
  type Page,
} from "@playwright/test";

import type { HarnessSentinel } from "./global-setup";

export type TenantSlug = "baseworm" | "democorp";
export type RoleLens = "installer" | "admin" | "member" | "observer";

/** Tenant cookie name — must match `apps/dashboard/lib/tenant-cookies.ts`. */
export const TENANT_COOKIE_NAME = "wormbase-tenant-slug";
/** Test-only role-hint cookie. Production code ignores it. */
export const ROLE_HINT_COOKIE_NAME = "wb-role-hint";

const SENTINEL_PATH = join(".playwright-state", "harness.json");

function readSentinel(): HarnessSentinel | null {
  if (!existsSync(SENTINEL_PATH)) return null;
  try {
    return JSON.parse(readFileSync(SENTINEL_PATH, "utf-8")) as HarnessSentinel;
  } catch {
    return null;
  }
}

interface WormFixtures {
  /** Tenant slug planted in cookies for this test run. Defaults to baseworm. */
  tenant: TenantSlug;
  /** Role lens for the test (no production effect; hint cookie). */
  role: RoleLens;
  /** Page with the right tenant + role cookies already planted. */
  ctxPage: Page;
}

export const test = base.extend<WormFixtures>({
  tenant: ["baseworm", { option: true }],
  role: ["admin", { option: true }],
  // Auto-applied skip: every test in this fixture file (and visual.spec.ts
  // which imports `test` from here) short-circuits with an honest reason
  // when the global-setup probe couldn't reach the dashboard.
  page: async ({ page }, use) => {
    const sentinel = readSentinel();
    if (sentinel && !sentinel.reachable) {
      test.skip(
        true,
        `dashboard unreachable at ${sentinel.baseUrl}: ${sentinel.reason}`,
      );
    }
    await use(page);
  },
  ctxPage: async ({ page, context, tenant, role, baseURL }, use) => {
    await plantTenantCookies(context, baseURL ?? "http://localhost:3000", {
      tenant,
      role,
    });
    await use(page);
  },
});

export { expect };

/** Plant tenant + role cookies on a context. */
export async function plantTenantCookies(
  context: BrowserContext,
  baseUrl: string,
  opts: { tenant: TenantSlug; role: RoleLens },
): Promise<void> {
  const url = new URL(baseUrl);
  const domain = url.hostname;
  await context.addCookies([
    {
      name: TENANT_COOKIE_NAME,
      value: opts.tenant,
      domain,
      path: "/",
      sameSite: "Lax",
    },
    {
      name: ROLE_HINT_COOKIE_NAME,
      value: opts.role,
      domain,
      path: "/",
      sameSite: "Lax",
    },
  ]);
}

/** data-testid selector helper — keeps spec text readable. */
export function tid(name: string): string {
  return `[data-testid="${name}"]`;
}

/** Every (app)-prefixed top-level route the role-aware nav can render. The
 *  primary check: every role can navigate to the routes its nav exposes
 *  without 5xx-ing. Mirrors `apps/dashboard/lib/role-nav.ts`. */
export const TAB_ROUTES: ReadonlyArray<{
  href: string;
  testid: string;
  label: string;
}> = [
  { href: "/dashboard", testid: "dashboard", label: "Dashboard" },
  { href: "/sources", testid: "sources", label: "Sources" },
  { href: "/kpis", testid: "kpis", label: "KPIs" },
  { href: "/data-products", testid: "data-products", label: "Data products" },
  { href: "/notebooks", testid: "notebooks", label: "Notebooks" },
  { href: "/topics", testid: "topics", label: "Topics" },
  { href: "/decisions", testid: "decisions", label: "Decisions" },
  { href: "/processes", testid: "processes", label: "Processes" },
  { href: "/system-map", testid: "system-map", label: "System map" },
  { href: "/research", testid: "research", label: "Research" },
  { href: "/activity", testid: "activity", label: "Activity" },
  { href: "/trace", testid: "trace", label: "Trace" },
  { href: "/people", testid: "people", label: "People" },
  { href: "/domains", testid: "domains", label: "Domains" },
  { href: "/policies", testid: "policies", label: "Policies" },
  { href: "/channels", testid: "channels", label: "Channels" },
  { href: "/mcp", testid: "mcp", label: "MCP" },
  { href: "/ops", testid: "ops", label: "Ops" },
  { href: "/reactivities", testid: "reactivities", label: "Reactivities" },
  {
    href: "/governance/tenant-quota",
    testid: "tenant-quota",
    label: "Tenant quota",
  },
];

/** Every role lens we run visual + e2e against. */
export const ROLE_LENSES: ReadonlyArray<RoleLens> = [
  "admin",
  "installer",
  "member",
  "observer",
];
