/**
 * Server-side fetch helper for worm-core's ops-health endpoint (W2.A10).
 *
 * Mirrors the structure of `worm-core-write.ts` but for the read-only
 * `GET /api/v1/ops/health` route. Used by the /ops page's server-side
 * initial render so the first paint already carries real data; the
 * client-side `OpsLiveView` then takes over with 5s polling.
 *
 * Failures are returned as a structured envelope rather than thrown —
 * /ops is the surface that's *supposed to* render honest "Postgres is
 * unreachable" or "worm-core proxy down" states. Throwing here would
 * defeat the point.
 */

import type {
  OpsHealthError,
  OpsHealthPayload,
} from "../ledger-client.types";

const DEFAULT_BASE = "http://worm-core:8910";

function readBase(): string {
  return (process.env.WORMBASE_LEDGER_API_BASE ?? DEFAULT_BASE).replace(
    /\/+$/,
    "",
  );
}

function readToken(): string | null {
  const raw = (process.env.WORMBASE_LEDGER_API_TOKEN ?? "").trim();
  return raw.length === 0 ? null : raw;
}

export async function fetchOpsHealth(
  tenantSlug: string,
): Promise<OpsHealthPayload | OpsHealthError> {
  const token = readToken();
  if (token === null) {
    return {
      ok: false,
      error: "ledger_api_token_unset",
      message:
        "WORMBASE_LEDGER_API_TOKEN unset; ops health unavailable until configured.",
    };
  }
  const url = `${readBase()}/api/v1/ops/health`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        "X-Tenant-Slug": tenantSlug,
        Accept: "application/json",
      },
      cache: "no-store",
    });
  } catch (err) {
    return {
      ok: false,
      error: "worm_core_unreachable",
      message: err instanceof Error ? err.message : String(err),
    };
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    return {
      ok: false,
      error: "worm_core_status",
      status: res.status,
      message: text.slice(0, 400),
    };
  }
  let body: unknown;
  try {
    body = await res.json();
  } catch (err) {
    return {
      ok: false,
      error: "worm_core_bad_json",
      message: err instanceof Error ? err.message : String(err),
    };
  }
  return body as OpsHealthPayload;
}
