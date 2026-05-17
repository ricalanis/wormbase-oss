/**
 * Server-side fetch helpers for the worm-core reactivities endpoints.
 *
 * Mirrors ``lib/server/worm-core-write.ts`` for the W5.A5 surface — read
 * + propose / confirm / disable / fires + per-Person resource
 * conversations. Used only from Next.js server contexts (route handlers,
 * RSC actions). The bearer token is a server-side env var; never sent
 * to the browser.
 *
 * Errors map to:
 *   - 4xx from worm-core (validation / auth / tenant) → throws Error
 *     with the response body as the message; the route handler maps to
 *     the appropriate HTTP status for the dashboard client.
 *   - 5xx from worm-core or network failures → throws; route handler
 *     maps to 502.
 */

const DEFAULT_BASE = "http://worm-core:8910";

function readBase(): string {
  return (process.env.WORMBASE_LEDGER_API_BASE ?? DEFAULT_BASE).replace(
    /\/+$/,
    "",
  );
}

function readToken(): string {
  const raw = process.env.WORMBASE_LEDGER_API_TOKEN ?? "";
  const trimmed = raw.trim();
  if (!trimmed) {
    throw new Error(
      "WORMBASE_LEDGER_API_TOKEN is not set; refusing to call the worm-core reactivities API",
    );
  }
  return trimmed;
}

interface RequestOptions {
  method: "GET" | "POST";
  path: string;
  tenantSlug: string;
  body?: Record<string, unknown> | null;
}

async function request<T>(opts: RequestOptions): Promise<T> {
  const base = readBase();
  const token = readToken();
  const url = `${base}${opts.path}`;
  const init: RequestInit = {
    method: opts.method,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      "X-Tenant-Slug": opts.tenantSlug,
    },
    cache: "no-store",
  };
  if (opts.body !== null && opts.body !== undefined) {
    init.body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (err) {
    throw new Error(
      `worm-core ${opts.method} ${opts.path} failed: ${(err as Error).message}`,
    );
  }
  const text = await res.text();
  if (!res.ok) {
    throw new Error(
      `worm-core ${opts.method} ${opts.path} returned ${res.status}: ${text}`,
    );
  }
  if (text.length === 0) return {} as T;
  try {
    return JSON.parse(text) as T;
  } catch (err) {
    throw new Error(
      `worm-core ${opts.method} ${opts.path} returned non-JSON: ${(err as Error).message}`,
    );
  }
}

export async function listReactivities(
  tenantSlug: string,
): Promise<{ reactivities: unknown[] }> {
  return request<{ reactivities: unknown[] }>({
    method: "GET",
    path: "/api/v1/reactivities",
    tenantSlug,
  });
}

export interface ProposeReactivityArgs {
  tenantSlug: string;
  description: string;
  proposedBy?: string;
  preview?: boolean;
}

export async function proposeReactivity(
  args: ProposeReactivityArgs,
): Promise<unknown> {
  const path = args.preview
    ? "/api/v1/reactivities/propose?preview=1"
    : "/api/v1/reactivities/propose";
  return request({
    method: "POST",
    path,
    tenantSlug: args.tenantSlug,
    body: {
      description: args.description,
      proposed_by: args.proposedBy ?? "dashboard-admin",
    },
  });
}

export interface ConfirmReactivityArgs {
  tenantSlug: string;
  reactivityId: string;
  confirmedBy: string;
}

export async function confirmReactivity(
  args: ConfirmReactivityArgs,
): Promise<unknown> {
  return request({
    method: "POST",
    path: `/api/v1/reactivities/${encodeURIComponent(args.reactivityId)}/confirm`,
    tenantSlug: args.tenantSlug,
    body: { confirmed_by: args.confirmedBy },
  });
}

export interface DisableReactivityArgs {
  tenantSlug: string;
  reactivityId: string;
  disabledBy: string;
  reason: string;
}

export async function disableReactivity(
  args: DisableReactivityArgs,
): Promise<unknown> {
  return request({
    method: "POST",
    path: `/api/v1/reactivities/${encodeURIComponent(args.reactivityId)}/disable`,
    tenantSlug: args.tenantSlug,
    body: { disabled_by: args.disabledBy, reason: args.reason },
  });
}

export interface ListReactivityFiresArgs {
  tenantSlug: string;
  reactivityId: string;
  limit?: number;
}

export async function listReactivityFires(
  args: ListReactivityFiresArgs,
): Promise<{ fires: unknown[] }> {
  const safeLimit = Math.max(
    1,
    Math.min(500, Math.floor(args.limit ?? 50)),
  );
  return request<{ fires: unknown[] }>({
    method: "GET",
    path: `/api/v1/reactivities/${encodeURIComponent(args.reactivityId)}/fires?limit=${safeLimit}`,
    tenantSlug: args.tenantSlug,
  });
}
