/**
 * GET /api/auth/email/confirm — magic-link confirm endpoint.
 *
 * Phase 1B.D introduced the route + the deterministic-per-email demo
 * tenant pick. Phase 4C (Wave H — final-level v1 launch) promotes the
 * session-binding to the signed `wormbase-session` cookie format from
 * 1B.E so subsequent dashboard requests resolve through the same secret
 * the rest of the auth surface trusts.
 *
 * Flow:
 *
 *   1. Decode + verify the magic-link token under
 *      ``WORMBASE_LEDGER_API_TOKEN`` (HMAC-SHA256). Reject expired /
 *      tampered / wrong-secret tokens.
 *   2. Pick a demo tenant slug deterministically per email
 *      (``hash(email) % len(slugs)``). Same email always lands on the
 *      same tenant — see ``pickDemoTenantForEmail`` for the projection-
 *      backed round-robin policy that supersedes this in a future
 *      iteration.
 *   3. Mint a signed `wormbase-session` cookie (httpOnly, sameSite=lax,
 *      30-day TTL) carrying ``{tenantSlug, personId: null, exp}``.
 *      Magic-link visitors are observer-only (no Person grant) — they
 *      get read access to the demo tenant; admin operations require an
 *      actual Person bound to the session.
 *   4. 303-redirect to ``/dashboard?welcome=email`` so the visitor lands
 *      in the dashboard with the welcome state surfaced (the dashboard
 *      reads ``?welcome=`` to render the first-run banner).
 *
 * Errors:
 *   - 400 missing_token / invalid_or_expired
 *   - 503 auth_secret_unset / no_demo_tenants
 */
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import {
  decodeMagicLinkToken,
  getDemoTenantSlugs,
} from "../../../../../lib/server/auth/magic-link";
import {
  DEFAULT_SESSION_TTL_SECONDS,
  SESSION_COOKIE_NAME,
  encodeSessionCookie,
} from "../../../../../lib/server/auth/session";
import { TENANT_COOKIE_NAME } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest): Promise<NextResponse> {
  const url = new URL(req.url);
  const token = url.searchParams.get("token") ?? "";
  if (!token) {
    return NextResponse.json(
      { error: "missing_token", message: "?token= required" },
      { status: 400 },
    );
  }
  const secret = (process.env.WORMBASE_LEDGER_API_TOKEN ?? "").trim();
  if (!secret) {
    return NextResponse.json(
      {
        error: "auth_secret_unset",
        message:
          "WORMBASE_LEDGER_API_TOKEN unset; magic-link auth disabled until configured",
      },
      { status: 503 },
    );
  }
  const claims = decodeMagicLinkToken(token, { secret });
  if (claims === null) {
    return NextResponse.json(
      {
        error: "invalid_or_expired",
        message: "magic link is invalid or expired; request a new link",
      },
      { status: 400 },
    );
  }

  const demoSlugs = getDemoTenantSlugs();
  if (demoSlugs.length === 0) {
    return NextResponse.json(
      {
        error: "no_demo_tenants",
        message:
          "no demo tenants configured (WORMBASE_DEMO_TENANT_SLUGS unset and defaults empty)",
      },
      { status: 503 },
    );
  }
  // Deterministic-per-email pick. The full projection-backed round-robin
  // (``pickDemoTenantForEmail``) supersedes this once the
  // projection_tenants visit-log reader is wired into the route.
  let h = 0;
  for (const c of claims.email) {
    h = (h * 31 + c.charCodeAt(0)) | 0;
  }
  const idx = Math.abs(h) % demoSlugs.length;
  const assignedSlug = demoSlugs[idx];

  // Mint the signed session cookie (Phase 1B.E format).
  const sessionCookie = encodeSessionCookie({
    tenantSlug: assignedSlug,
    personId: null, // observer-only; magic-link visitors have no Person grant.
    secret,
    expiresInSeconds: DEFAULT_SESSION_TTL_SECONDS,
  });

  const dashboardUrl = new URL("/dashboard", url.origin);
  dashboardUrl.searchParams.set("welcome", "email");
  const res = NextResponse.redirect(dashboardUrl, { status: 303 });
  res.cookies.set(SESSION_COOKIE_NAME, sessionCookie, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: DEFAULT_SESSION_TTL_SECONDS,
    secure: url.protocol === "https:",
  });
  // Clear any stale legacy slug cookie so the new session is the only
  // source-of-truth — getTenantFromCookies prefers the signed cookie
  // already, but the legacy cookie persists otherwise and confuses
  // observability.
  res.cookies.set(TENANT_COOKIE_NAME, "", {
    path: "/",
    maxAge: 0,
  });
  res.headers.set("Referrer-Policy", "no-referrer");
  return res;
}
