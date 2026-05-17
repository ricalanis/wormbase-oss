/**
 * Slack OAuth signup-vs-reauth decision logic.
 *
 * Phase 1B.C of the multi-tenancy v2 plan. The OAuth callback handler at
 * ``app/onboarding/oauth/[platform]/callback/route.ts`` (and its sign-in
 * alias at ``app/api/auth/slack/callback/route.ts``) calls
 * ``decideSignupVsReauth`` after the code exchange to decide whether
 * the workspace is a new tenant (write the canonical signup chain) or
 * an existing tenant logging back in (skip the signup chain; the
 * existing install orchestrator handles re-auth idempotently).
 *
 * Pure logic — no I/O. Caller fetches ``projection_tenants`` for the
 * slug via the Postgres reader and passes the result (or null) into
 * this function.
 */

export interface ProjectionTenantRow {
  /** Canonical tenant slug. */
  slug: string;
  /** Lifecycle status; one of pending|active|suspended|deleted. */
  status: "pending" | "active" | "suspended" | "deleted";
}

export type SignupDecision =
  | { kind: "signup" }
  | { kind: "reauth" }
  | { kind: "rejected"; reason: string };

/**
 * Decide whether an OAuth callback is a fresh signup, a re-auth into an
 * existing tenant, or a rejected attempt against a suspended/deleted
 * tenant.
 *
 * - No projection row → signup (first install for this workspace).
 * - Active row → reauth (Slack re-grant flow; no tenant_signup_* writes).
 * - Pending row → signup (a previous attempt didn't complete; treat as
 *   resumption — the projection_tenants row will upsert on signup_completed).
 * - Suspended → rejected with hint.
 * - Deleted → rejected with hint (only an admin tool can restore;
 *   orchestrator-driven recovery is Phase 4 polish).
 */
export function decideSignupVsReauth(args: {
  tenantSlug: string;
  existingProjectionRow: ProjectionTenantRow | null;
}): SignupDecision {
  const { existingProjectionRow } = args;
  if (existingProjectionRow === null) return { kind: "signup" };
  if (existingProjectionRow.status === "active") return { kind: "reauth" };
  if (existingProjectionRow.status === "pending") return { kind: "signup" };
  if (existingProjectionRow.status === "suspended") {
    return {
      kind: "rejected",
      reason:
        "tenant is suspended; contact support@wormbase to restore access",
    };
  }
  return {
    kind: "rejected",
    reason:
      "tenant is deleted; admin tool required to restore (Phase 4 polish)",
  };
}

/**
 * Mirror of the existing ``tenantSlugFor(platform, workspaceId)`` in
 * ``app/onboarding/oauth/[platform]/callback/route.ts``. Hoisted into
 * this helper module so callers don't need to reach into the route
 * file. Both paths must produce the same slug.
 */
export function deriveTenantSlug(platform: string, workspaceId: string): string {
  return `${platform}_team_${workspaceId.toLowerCase()}`;
}

/**
 * Compute the sha256 hex of an OAuth state token, matching the format
 * the ``tenant_signup_initiated`` payload's ``pending_token_hash``
 * field expects (64 lowercase hex chars).
 *
 * Imported from node:crypto inside the module rather than at the top so
 * this file remains importable from a client component (the helper
 * itself only runs server-side, but the type exports above are used in
 * the dashboard chrome).
 */
export async function sha256HexHash(input: string): Promise<string> {
  // Dynamic import keeps this server-only helper out of client bundles.
  const { createHash } = await import("node:crypto");
  return createHash("sha256").update(input, "utf8").digest("hex");
}

/**
 * Display name fallback for a Slack workspace. Slack's ``team.name`` may
 * be empty when the workspace owner hasn't filled it; fall back to the
 * derived slug capitalized so the dashboard never shows a blank chip.
 */
export function safeWorkspaceDisplayName(
  rawName: string | null | undefined,
  fallbackSlug: string,
): string {
  const trimmed = (rawName ?? "").trim();
  if (trimmed) return trimmed;
  return fallbackSlug.replace(/^slack_team_/, "Slack ").replace(/_/g, " ");
}
