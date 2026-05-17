/**
 * Server actions for /lake/entity-stitches (L8 Sub-wave D, 2026-06-07).
 *
 * Architectural contract (mirrors /lake/lineage/actions.ts +
 * /lake/quality/actions.ts + /lake/schema-impact/actions.ts +
 * /lake/semantic-types/actions.ts + /lake/column-classification/actions.ts):
 *
 *   * Dashboard NEVER direct-writes the ledger. Confirm + reject route
 *     through worm-core's HTTP write API at
 *     ``POST /api/v1/write_actions/entity_stitches_confirm/{stitch_id}``
 *     and ``POST /api/v1/write_actions/entity_stitches_reject/{stitch_id}``
 *     (Sub-wave C).
 *
 *   * Admin role check is enforced at the server-action layer (defense
 *     in depth — worm-core's endpoint also checks via tenant header +
 *     bearer token, but refusing here means non-admins can never reach
 *     the wire).
 *
 *   * ``confirmed_by_person_id`` / ``rejected_by_person_id`` is threaded
 *     from ``getCurrentPerson(companyId)`` — never a placeholder.
 *
 *   * Reject reason is constrained to the strict 5-value L8 enum on
 *     :class:`EntityStitchRejectedPayload`: ``false_positive`` /
 *     ``low_value`` / ``wrong_pairing`` / ``out_of_scope`` / ``other``.
 *     The L8-specific 5th value is ``wrong_pairing`` (distinct from
 *     L6's ``wrong_level``, L5's ``wrong_type``, L4's
 *     ``already_handled`` and L7's ``wrong_threshold``).
 *
 *   * Per Sub-wave C handoff concern #3, ``entity_kind`` admin override
 *     is OUT OF SCOPE for this sub-wave — confirm posts without
 *     override. Future enhancement noted in close-out tracker.
 */
"use server";

import {
  getCurrentCompanyId,
  getTenantFromCookies,
} from "../../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../../lib/server/identity";
import { getRolesForPerson } from "../../../../lib/ledger-client";

const DEFAULT_WORM_CORE_BASE = "http://worm-core:8910";

const VALID_REJECT_REASONS = new Set<string>([
  "false_positive",
  "low_value",
  "wrong_pairing",
  "out_of_scope",
  "other",
]);

export type EntityStitchRejectReason =
  | "false_positive"
  | "low_value"
  | "wrong_pairing"
  | "out_of_scope"
  | "other";

export interface EntityStitchActionResult {
  ok: boolean;
  error?: string;
}

function readBase(): string {
  const raw = (
    process.env.WORM_CORE_API_URL ??
    process.env.WORMBASE_LEDGER_API_BASE ??
    ""
  ).trim();
  return raw.replace(/\/+$/, "");
}

function readToken(): string {
  return (process.env.WORMBASE_LEDGER_API_TOKEN ?? "").trim();
}

/**
 * Resolve the caller's identity + verify the admin role. Returns the
 * Person UUID on success or an error string on miss. Probes the
 * roster projection first, then the per-Person grants table as a
 * fallback (mirroring L3/L7/L4/L5/L6 actions).
 */
async function resolveAdminPersonId(
  companyId: string,
): Promise<{ personId: string } | { error: string }> {
  const person = await getCurrentPerson(companyId);
  if (!person) return { error: "no authenticated person" };

  if (person.tenancyRole === "admin" || person.tenancyRole === "installer") {
    return { personId: person.personId };
  }

  // Defensive: also probe the grants table directly in case the
  // person's projection lags. Production rule per CLAUDE.md §5:
  // installers are super-admins; admins are the canonical role.
  let grants: Awaited<ReturnType<typeof getRolesForPerson>> = [];
  try {
    grants = await getRolesForPerson(companyId, person.personId);
  } catch {
    grants = [];
  }
  const live = grants
    .filter((g) => g.facet === "tenancy" && g.revokedAt === null)
    .map((g) => g.role);
  if (live.includes("admin") || live.includes("installer")) {
    return { personId: person.personId };
  }
  return { error: "admin role required" };
}

/**
 * Confirm a previously-proposed entity-stitch. Forwards to worm-core's
 * write API (L8 Sub-wave C).
 *
 * Per Sub-wave C handoff concern #3, the entity_kind admin override is
 * out of scope for this sub-wave; confirm posts the stitch as
 * proposed (no override field on the body). Future enhancement.
 */
export async function confirmEntityStitch(
  stitchId: string,
  notes?: string,
): Promise<EntityStitchActionResult> {
  const id = (stitchId ?? "").trim();
  if (!id) return { ok: false, error: "missing stitch_id" };

  const companyId = await getCurrentCompanyId();
  const auth = await resolveAdminPersonId(companyId);
  if ("error" in auth) return { ok: false, error: auth.error };

  const base = readBase();
  if (!base) {
    return {
      ok: false,
      error:
        "confirm_entity_stitch endpoint unavailable (no WORM_CORE_API_URL configured)",
    };
  }
  const token = readToken();
  if (!token) {
    return {
      ok: false,
      error:
        "WORMBASE_LEDGER_API_TOKEN not set — refusing to call worm-core write API",
    };
  }

  const tenant = await getTenantFromCookies();
  const url = `${base}/api/v1/write_actions/entity_stitches_confirm/${encodeURIComponent(id)}`;
  const trimmedNotes =
    typeof notes === "string" && notes.trim().length > 0
      ? notes.trim().slice(0, 2048)
      : undefined;
  const body: Record<string, unknown> = {
    company_id: companyId,
    confirmed_by: auth.personId,
  };
  if (trimmedNotes !== undefined) body.notes = trimmedNotes;

  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "X-Tenant-Slug": tenant.slug,
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch (e) {
    return { ok: false, error: `network: ${(e as Error).message}` };
  }

  if (res.status === 404) {
    return {
      ok: false,
      error: `no entity_stitch_proposed entry found for stitch_id ${id}`,
    };
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    return {
      ok: false,
      error: `worm-core API ${res.status}: ${text || res.statusText}`,
    };
  }
  return { ok: true };
}

/**
 * Reject a previously-proposed entity-stitch. Forwards to worm-core's
 * write API (L8 Sub-wave C). ``reason`` is the strict 5-value L8 enum
 * value from the rejection modal dropdown.
 */
export async function rejectEntityStitch(
  stitchId: string,
  reason: string,
  notes?: string,
): Promise<EntityStitchActionResult> {
  const id = (stitchId ?? "").trim();
  if (!id) return { ok: false, error: "missing stitch_id" };
  const reasonNormalized = (reason ?? "").trim();
  if (!VALID_REJECT_REASONS.has(reasonNormalized)) {
    return {
      ok: false,
      error: `invalid reason '${reasonNormalized}'; expected one of ${[...VALID_REJECT_REASONS].join(", ")}`,
    };
  }

  const companyId = await getCurrentCompanyId();
  const auth = await resolveAdminPersonId(companyId);
  if ("error" in auth) return { ok: false, error: auth.error };

  const base = readBase();
  if (!base) {
    return {
      ok: false,
      error:
        "reject_entity_stitch endpoint unavailable (no WORM_CORE_API_URL configured)",
    };
  }
  const token = readToken();
  if (!token) {
    return {
      ok: false,
      error:
        "WORMBASE_LEDGER_API_TOKEN not set — refusing to call worm-core write API",
    };
  }

  const tenant = await getTenantFromCookies();
  const url = `${base}/api/v1/write_actions/entity_stitches_reject/${encodeURIComponent(id)}`;
  const trimmedNotes =
    typeof notes === "string" && notes.trim().length > 0
      ? notes.trim().slice(0, 2048)
      : undefined;
  const body: Record<string, unknown> = {
    company_id: companyId,
    rejected_by: auth.personId,
    reason: reasonNormalized,
  };
  if (trimmedNotes !== undefined) body.notes = trimmedNotes;

  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "X-Tenant-Slug": tenant.slug,
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch (e) {
    return { ok: false, error: `network: ${(e as Error).message}` };
  }

  if (res.status === 404) {
    return {
      ok: false,
      error: `no entity_stitch_proposed entry found for stitch_id ${id}`,
    };
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    return {
      ok: false,
      error: `worm-core API ${res.status}: ${text || res.statusText}`,
    };
  }
  return { ok: true };
}

// Re-exports for tests.
export const __test__ = {
  readBase,
  readToken,
  VALID_REJECT_REASONS,
  DEFAULT_WORM_CORE_BASE,
};
