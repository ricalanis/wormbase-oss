/**
 * POST /api/v1/connectors/test/[kind] — connector test-connection proxy.
 *
 * W2.A5 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * Body: `{config: Record<string, unknown>}` (the kind-specific form
 * payload — e.g. `{dsn: "postgres://..."}` for postgres).
 *
 * Forwards to worm-core's `/api/v1/connectors/{kind}/test` which calls
 * the real `Connector.authenticate` against the supplied config — same
 * code path the source-builder uses at runtime, no stub.
 *
 * Response envelope (forwarded unchanged):
 *   - `{ok: true, kind, handle_id, version, hash}` on success
 *   - `{ok: false, kind, error}` on validation or upstream failure
 *
 * The picker UI renders the hash as a content-addressed receipt so the
 * operator sees a stable, visible artifact when the test passes — the
 * receipt is folded back into the source-propose payload if they
 * proceed to "create source".
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { getTenantFromCookies } from "../../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const DEFAULT_WORM_CORE_BASE = "http://worm-core:8910";

function wormCoreBaseUrl(): string {
  return (
    process.env.WORMBASE_LEDGER_API_BASE ?? DEFAULT_WORM_CORE_BASE
  ).replace(/\/+$/, "");
}

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ kind: string }> },
): Promise<NextResponse> {
  const { kind } = await ctx.params;
  if (!kind) {
    return NextResponse.json(
      { ok: false, error: "kind_required", message: "connector kind missing" },
      { status: 400 },
    );
  }

  const apiToken = (process.env.WORMBASE_LEDGER_API_TOKEN ?? "").trim();
  if (!apiToken) {
    return NextResponse.json(
      {
        ok: false,
        kind,
        error: "ledger_api_token_unset",
        message:
          "WORMBASE_LEDGER_API_TOKEN unset; refusing to call the worm-core test endpoint",
      },
      { status: 503 },
    );
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    body = {};
  }
  const obj = (body ?? {}) as Record<string, unknown>;
  const rawConfig = obj.config;
  const config =
    rawConfig && typeof rawConfig === "object" && !Array.isArray(rawConfig)
      ? (rawConfig as Record<string, unknown>)
      : {};

  const tenant = await getTenantFromCookies();
  const tenantSlug = tenant.slug;
  const upstreamUrl = `${wormCoreBaseUrl()}/api/v1/connectors/${encodeURIComponent(kind)}/test`;

  let res: Response;
  try {
    res = await fetch(upstreamUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiToken}`,
        "X-Tenant-Slug": tenantSlug,
      },
      body: JSON.stringify({ config }),
      cache: "no-store",
    });
  } catch (err) {
    return NextResponse.json(
      {
        ok: false,
        kind,
        error: "worm_core_unreachable",
        message: (err as Error).message ?? String(err),
      },
      { status: 502 },
    );
  }

  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : {};
  } catch {
    return NextResponse.json(
      {
        ok: false,
        kind,
        error: "worm_core_non_json",
        message: text.slice(0, 400),
      },
      { status: 502 },
    );
  }

  // worm-core returns ok=false / 200 for validation failures (so the UI
  // can surface the error message) and 4xx for unknown kinds. Forward
  // the body verbatim; bump the status to 200 if upstream returned the
  // ok=false envelope so the dashboard fetch layer doesn't treat it as
  // a transport error.
  const envelope = (parsed ?? {}) as Record<string, unknown>;
  const ok = envelope.ok === true;
  const status = res.status >= 500 ? 502 : res.status;
  return NextResponse.json(envelope, { status: ok ? 200 : status });
}
