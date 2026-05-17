/**
 * Per-connector probe accessor — Onboarding Sub-wave D (2026-05-30).
 *
 * Polishes ``/lake/surfaces`` with per-row tenant-side health badges.
 * Fetches ``GET /api/v1/connectors/{kind}/probe`` from worm-core and
 * surfaces the result on each row. The endpoint returns one of four
 * honest states:
 *
 *   * ``works``    — probe attempted + succeeded
 *   * ``degraded`` — probe attempted + partial result
 *   * ``failed``   — probe attempted + raised
 *   * ``unknown``  — no probe wired for this kind (honest non-fake-
 *                    positive when the kind has no tenant-side health
 *                    check yet)
 *
 * Honesty contract: connectors that haven't been wired for a probe
 * yet MUST return ``unknown`` with an explicit reason — never
 * ``works`` by default. The badge surface honors this; a missing
 * probe renders a neutral "unknown · not wired" pill, not a green
 * "works" pill.
 */
import { headers } from "next/headers";

export type ConnectorProbeState = "works" | "degraded" | "failed" | "unknown";

export interface ConnectorProbe {
  kind: string;
  state: ConnectorProbeState;
  reason: string | null;
}

const DEFAULT_WORM_CORE_BASE = "http://worm-core:8910";

function wormCoreBaseUrl(): string {
  return (
    process.env.WORMBASE_LEDGER_API_BASE ?? DEFAULT_WORM_CORE_BASE
  ).replace(/\/+$/, "");
}

function isProbeState(value: unknown): value is ConnectorProbeState {
  return (
    value === "works" ||
    value === "degraded" ||
    value === "failed" ||
    value === "unknown"
  );
}

/**
 * Probe a single connector kind.
 *
 * On any wire-level failure (worm-core unreachable, malformed
 * response) we synthesize a ``state="unknown"`` probe with the error
 * as the reason — the marketplace row renders a neutral badge rather
 * than disappearing. No fake-positive ``works`` on failures.
 */
export async function probeConnector(
  kind: string,
  opts?: { fetchImpl?: typeof fetch; baseUrl?: string },
): Promise<ConnectorProbe> {
  const cleanKind = kind.trim();
  if (!cleanKind) {
    return {
      kind: "",
      state: "unknown",
      reason: "empty connector kind",
    };
  }

  let url: string;
  try {
    // RSC path: prefer the dashboard's own proxy when running inside
    // a server component (we tunnel auth + tenant headers via the
    // request handler). Fall back to direct upstream when called from
    // a non-RSC context (tests, scripts).
    const h = await headers();
    const host = h.get("host") ?? "localhost:3000";
    const proto = h.get("x-forwarded-proto") ?? "http";
    url = `${proto}://${host}/api/v1/connectors/${encodeURIComponent(cleanKind)}/probe`;
  } catch {
    url =
      `${opts?.baseUrl ?? wormCoreBaseUrl()}/api/v1/connectors/` +
      `${encodeURIComponent(cleanKind)}/probe`;
  }

  const fetchImpl = opts?.fetchImpl ?? fetch;
  try {
    const res = await fetchImpl(url, { method: "GET", cache: "no-store" });
    if (res.status === 404) {
      return {
        kind: cleanKind,
        state: "unknown",
        reason: `unknown connector kind '${cleanKind}'`,
      };
    }
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return {
        kind: cleanKind,
        state: "unknown",
        reason: `worm-core probe HTTP ${res.status}: ${text.slice(0, 200)}`,
      };
    }
    const body = (await res.json()) as {
      kind?: string;
      state?: unknown;
      reason?: string | null;
    };
    if (!isProbeState(body.state)) {
      return {
        kind: cleanKind,
        state: "unknown",
        reason: "probe response missing or invalid 'state' field",
      };
    }
    return {
      kind: body.kind ?? cleanKind,
      state: body.state,
      reason: body.reason ?? null,
    };
  } catch (err) {
    return {
      kind: cleanKind,
      state: "unknown",
      reason:
        `probe fetch failed: ${(err as Error).message ?? String(err)}`,
    };
  }
}

/**
 * Batched probe — calls ``probeConnector`` for every kind in
 * parallel + folds the results into a kind-keyed Map.
 *
 * Used by the /lake/surfaces page to enrich the catalog rows with
 * tenant-side state in one pass.
 */
export async function probeConnectors(
  kinds: readonly string[],
  opts?: { fetchImpl?: typeof fetch; baseUrl?: string },
): Promise<Map<string, ConnectorProbe>> {
  const results = await Promise.all(
    kinds.map(async (k) => probeConnector(k, opts)),
  );
  const map = new Map<string, ConnectorProbe>();
  for (const probe of results) {
    map.set(probe.kind, probe);
  }
  return map;
}
