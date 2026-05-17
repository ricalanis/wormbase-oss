/**
 * GET /api/v1/ops/health — proxy to worm-core's /api/v1/ops/health (W2.A10).
 *
 * Authenticated by the dashboard's existing tenant cookie. Forwards the
 * tenant slug as `X-Tenant-Slug` and the bearer token as `Authorization`.
 *
 * Failure modes are surfaced **honestly** rather than being swallowed:
 *
 *   - 401 if the tenant cookie does not resolve to a registered install.
 *   - 502 with `{ ok: false, error, detail }` JSON if worm-core is
 *     unreachable. The /ops page renders this as a red banner — that's
 *     the entire point of the observability tab.
 *   - 503 if `WORMBASE_LEDGER_API_TOKEN` is unset — operator misconfig.
 *
 * Cache-Control is `no-store` so the dashboard's polling hook always
 * sees fresh data.
 */
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { cookies } from "next/headers";

import { TENANT_COOKIE_NAME } from "../../../../../lib/tenant-cookies";
import { findTenantBySlug, getDefaultTenant } from "../../../../../lib/tenants";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const DEFAULT_WORM_CORE_BASE = "http://worm-core:8910";

function wormCoreBaseUrl(): string {
  return (process.env.WORMBASE_LEDGER_API_BASE ?? DEFAULT_WORM_CORE_BASE).replace(
    /\/+$/,
    "",
  );
}

export async function GET(_req: NextRequest): Promise<Response> {
  const cookieStore = await cookies();
  const slug = cookieStore.get(TENANT_COOKIE_NAME)?.value ?? null;
  const tenant = slug ? findTenantBySlug(slug) : getDefaultTenant();
  if (!tenant) {
    return NextResponse.json(
      {
        ok: false,
        error: "unknown_tenant",
        message: `tenant cookie "${slug}" not registered`,
      },
      { status: 401 },
    );
  }

  const apiToken = (process.env.WORMBASE_LEDGER_API_TOKEN ?? "").trim();
  if (!apiToken) {
    return NextResponse.json(
      {
        ok: false,
        error: "ledger_api_token_unset",
        message:
          "WORMBASE_LEDGER_API_TOKEN unset; ops health proxy disabled.",
      },
      { status: 503 },
    );
  }

  const upstreamUrl = `${wormCoreBaseUrl()}/api/v1/ops/health`;
  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, {
      headers: {
        Authorization: `Bearer ${apiToken}`,
        "X-Tenant-Slug": tenant.slug,
        Accept: "application/json",
      },
      cache: "no-store",
    });
  } catch (err) {
    return NextResponse.json(
      {
        ok: false,
        error: "worm_core_unreachable",
        message:
          err instanceof Error ? err.message : String(err),
      },
      { status: 502 },
    );
  }

  if (!upstream.ok) {
    const text = await upstream.text().catch(() => "");
    return NextResponse.json(
      {
        ok: false,
        error: "worm_core_status",
        status: upstream.status,
        message: text.slice(0, 400),
      },
      { status: 502 },
    );
  }

  const body = await upstream.json().catch(() => null);
  if (body == null) {
    return NextResponse.json(
      {
        ok: false,
        error: "worm_core_bad_json",
        message: "worm-core returned a non-JSON body",
      },
      { status: 502 },
    );
  }

  return NextResponse.json(body, {
    status: 200,
    headers: { "Cache-Control": "no-store" },
  });
}
