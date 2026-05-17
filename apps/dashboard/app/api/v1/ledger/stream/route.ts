/**
 * GET /api/v1/ledger/stream — Server-Sent-Events proxy to worm-core.
 *
 * Authenticated by the dashboard's existing tenant cookie:
 * `wormbase-tenant-slug`. Reads the worm-core SSE endpoint (also at
 * `/api/v1/ledger/stream`) with the tenant slug forwarded as
 * `X-Tenant-Slug` and the bearer-token forwarded as
 * `Authorization`. Streams every frame straight back to the browser
 * — one ledger row per `data:` line.
 *
 * Query params (forwarded verbatim to worm-core):
 *   - `since`          — exclusive seq lower-bound; only newer rows stream.
 *   - `kinds`          — comma-separated kind whitelist (propose,execute,
 *                        verify,resolve). Defaults to all four when absent.
 *   - `filter_install` — only stream rows whose payload.args.install_id
 *                        matches. Optional.
 *
 * Failure modes:
 *   - 401 if the tenant cookie does not resolve to a real install.
 *   - 502 if the worm-core SSE endpoint is unreachable.
 *   - 503 with a one-shot SSE error frame if worm-core's
 *     WORMBASE_LEDGER_API_TOKEN is unset (operator misconfiguration —
 *     surface honestly so the cascade panel can render the error).
 *
 * The browser's EventSource auto-reconnects on stream end; we close
 * promptly when the client disconnects to avoid leaking upstream
 * fetches. No queueing, no buffering — pure pass-through.
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

function sseFrame(payload: unknown): Uint8Array {
  const data =
    typeof payload === "string" ? payload : JSON.stringify(payload);
  return new TextEncoder().encode(`data: ${data}\n\n`);
}

function sseEvent(event: string, payload: unknown): Uint8Array {
  const data =
    typeof payload === "string" ? payload : JSON.stringify(payload);
  return new TextEncoder().encode(`event: ${event}\ndata: ${data}\n\n`);
}

export async function GET(req: NextRequest): Promise<Response> {
  // Resolve tenant from cookie. Fall back to the default tenant only if
  // the cookie is absent — an unknown slug returns 401 to avoid silently
  // leaking another tenant's stream.
  const cookieStore = await cookies();
  const slug = cookieStore.get(TENANT_COOKIE_NAME)?.value ?? null;
  const tenant = slug ? findTenantBySlug(slug) : getDefaultTenant();
  if (!tenant) {
    return NextResponse.json(
      {
        error: "unknown_tenant",
        message: `tenant cookie "${slug}" not registered`,
      },
      { status: 401 },
    );
  }

  const apiToken = (process.env.WORMBASE_LEDGER_API_TOKEN ?? "").trim();
  if (!apiToken) {
    // Surface honestly: produce a one-shot SSE frame the cascade panel
    // can render as an error rather than 502ing the whole stream.
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          sseEvent("error", {
            error: "ledger_api_token_unset",
            message:
              "WORMBASE_LEDGER_API_TOKEN unset; live ledger feed disabled.",
          }),
        );
        controller.close();
      },
    });
    return new Response(stream, {
      status: 503,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
      },
    });
  }

  // Forward the query string straight through. The browser's EventSource
  // will reconnect on transient errors; the AbortController hooks the
  // browser-side disconnect into the upstream fetch.
  const inboundUrl = new URL(req.url);
  const upstreamUrl = new URL(`${wormCoreBaseUrl()}/api/v1/ledger/stream`);
  for (const key of ["since", "kinds", "filter_install"]) {
    const v = inboundUrl.searchParams.get(key);
    if (v !== null) upstreamUrl.searchParams.set(key, v);
  }

  const upstream = await fetch(upstreamUrl.toString(), {
    headers: {
      Accept: "text/event-stream",
      Authorization: `Bearer ${apiToken}`,
      "X-Tenant-Slug": tenant.slug,
    },
    signal: req.signal,
    cache: "no-store",
  }).catch(
    (err: Error) => ({
      ok: false as const,
      error: err,
    }),
  );

  if ("error" in upstream) {
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          sseEvent("error", {
            error: "worm_core_unreachable",
            message: upstream.error.message,
          }),
        );
        controller.close();
      },
    });
    return new Response(stream, {
      status: 502,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
      },
    });
  }

  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => "");
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          sseEvent("error", {
            error: "worm_core_status",
            status: upstream.status,
            message: text.slice(0, 200),
          }),
        );
        controller.close();
      },
    });
    return new Response(stream, {
      status: 502,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
      },
    });
  }

  // Pass-through: pipe the upstream SSE body straight to the browser.
  // worm-core already framed every row as `data: ...\n\n`.
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}

// `sseFrame` retained for any future inline pre-amble usage; export-blank
// to satisfy the linter's "unused private helper" check without polluting
// the route's public API.
void sseFrame;
