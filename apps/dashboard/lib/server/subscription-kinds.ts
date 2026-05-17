/**
 * Server-side fetch helper for the worm-core subscription-eligible
 * kinds catalog (v1.4 #5).
 *
 * Replaces the hardcoded 8-kind list that shipped in v2.A Batch C's
 * ``SubscriptionForm`` with a dynamic, drift-free list derived from
 * the canonical ``KIND_REGISTRY`` at request time. Excludes meta-
 * kinds (would cause subscription recursion), PEVR primitives, and
 * infra heartbeats.
 *
 * Endpoint: ``GET /api/v1/read/subscription_eligible_kinds``. No
 * bearer token (read-only, tenant-agnostic — same posture as
 * ``GET /mcp/catalog``).
 *
 * Falls back to an empty list when the endpoint is unreachable;
 * the form renders a graceful empty state pointing operators at
 * the MCP path for power-user subscriptions.
 */

const DEFAULT_BASE = "http://worm-core:8910";

export interface SubscriptionEligibleKind {
  kind: string;
  label: string;
  description: string;
  family: string;
}

function readBase(): string {
  return (
    process.env.WORMBASE_LEDGER_API_BASE ?? DEFAULT_BASE
  ).replace(/\/+$/, "");
}

/**
 * Fetch the eligible-kinds catalog. Returns ``[]`` when the endpoint
 * is unreachable so the page renders without throwing.
 */
export async function getSubscriptionEligibleKinds(): Promise<
  SubscriptionEligibleKind[]
> {
  const base = readBase();
  const url = `${base}/api/v1/read/subscription_eligible_kinds`;
  try {
    const res = await fetch(url, {
      method: "GET",
      cache: "no-store",
    });
    if (!res.ok) return [];
    const body = (await res.json()) as { kinds?: unknown };
    if (!Array.isArray(body.kinds)) return [];
    return body.kinds
      .filter(
        (row): row is SubscriptionEligibleKind =>
          typeof row === "object" &&
          row !== null &&
          typeof (row as SubscriptionEligibleKind).kind === "string" &&
          typeof (row as SubscriptionEligibleKind).label === "string" &&
          typeof (row as SubscriptionEligibleKind).description === "string" &&
          typeof (row as SubscriptionEligibleKind).family === "string",
      );
  } catch {
    return [];
  }
}
