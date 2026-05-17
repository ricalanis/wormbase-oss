/**
 * Server actions for /lake/catalog-drift (L2 Sub-wave D, 2026-06-09).
 *
 * Architectural contract (mirrors L3/L7/L4/L5/L6/L8/L1 actions):
 *
 *   * Dashboard NEVER direct-writes the ledger. Acknowledge + reject
 *     route through worm-core's HTTP write API at
 *     ``POST /api/v1/write_actions/catalog_drifts_acknowledge/{drift_id}``
 *     and
 *     ``POST /api/v1/write_actions/catalog_drifts_reject/{drift_id}``
 *     (Sub-wave C).
 *
 *   * Admin role check is enforced at the server-action layer
 *     (defense in depth — worm-core's endpoint also checks via
 *     tenant header + bearer token).
 *
 *   * ``acknowledged_by`` / ``rejected_by`` is threaded from
 *     ``getCurrentPerson(companyId)`` — never a placeholder.
 *
 *   * Reject reason is constrained to the strict 5-value L2 enum on
 *     :class:`CatalogDriftRejectedPayload`: ``false_positive`` /
 *     ``inconsequential`` / ``expected_change`` / ``out_of_scope`` /
 *     ``other``. The L2-specific 5th value is ``expected_change``
 *     (distinct from L1's ``duplicate``, L8's ``wrong_pairing``,
 *     L6's ``wrong_level``, L5's ``wrong_type``, L4's
 *     ``already_handled``, L7's ``wrong_threshold``).
 *
 *   * Acknowledge is record-only — no downstream pipeline trigger
 *     (unlike L1's promote dual-write). The
 *     ``catalog_drift_acknowledged`` entry simply flips the
 *     projection state to ``"acknowledged"`` for the
 *     (company_id, drift_id) row.
 *
 *   * Body shape uses snake_case (``drift_id`` is in the URL path;
 *     bodies carry ``company_id`` / ``acknowledged_by`` /
 *     ``rejected_by`` / ``reason`` / ``notes``). Sub-wave C handoff
 *     concern #4 notes the response also carries both ``driftId``
 *     (camelCase) and ``drift_id`` (snake_case) — actions don't
 *     consume the response body so this is fine.
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
  "inconsequential",
  "expected_change",
  "out_of_scope",
  "other",
]);

export type CatalogDriftRejectReason =
  | "false_positive"
  | "inconsequential"
  | "expected_change"
  | "out_of_scope"
  | "other";

export interface CatalogDriftActionResult {
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
 * fallback (mirroring L3-L8 + L1 actions).
 */
async function resolveAdminPersonId(
  companyId: string,
): Promise<{ personId: string } | { error: string }> {
  const person = await getCurrentPerson(companyId);
  if (!person) return { error: "no authenticated person" };

  if (person.tenancyRole === "admin" || person.tenancyRole === "installer") {
    return { personId: person.personId };
  }

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
 * Acknowledge a previously-proposed catalog drift. Forwards to
 * worm-core's write API (L2 Sub-wave C); the endpoint writes a
 * ``catalog_drift_acknowledged`` ledger entry which flips the
 * projection state to ``"acknowledged"``. No downstream pipeline is
 * triggered; no cross-axis effect is fired.
 */
export async function acknowledgeCatalogDrift(
  driftId: string,
  notes?: string,
): Promise<CatalogDriftActionResult> {
  const id = (driftId ?? "").trim();
  if (!id) return { ok: false, error: "missing drift_id" };

  const companyId = await getCurrentCompanyId();
  const auth = await resolveAdminPersonId(companyId);
  if ("error" in auth) return { ok: false, error: auth.error };

  const base = readBase();
  if (!base) {
    return {
      ok: false,
      error:
        "acknowledge_catalog_drift endpoint unavailable (no WORM_CORE_API_URL configured)",
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
  const url = `${base}/api/v1/write_actions/catalog_drifts_acknowledge/${encodeURIComponent(id)}`;
  const trimmedNotes =
    typeof notes === "string" && notes.trim().length > 0
      ? notes.trim().slice(0, 2048)
      : undefined;
  const body: Record<string, unknown> = {
    company_id: companyId,
    acknowledged_by: auth.personId,
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
      error: `no catalog_drift_proposed entry found for drift_id ${id}`,
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
 * Reject a previously-proposed catalog drift. Forwards to worm-core's
 * write API (L2 Sub-wave C). ``reason`` is the strict 5-value L2 enum
 * value from the rejection modal dropdown.
 */
export async function rejectCatalogDrift(
  driftId: string,
  reason: string,
  notes?: string,
): Promise<CatalogDriftActionResult> {
  const id = (driftId ?? "").trim();
  if (!id) return { ok: false, error: "missing drift_id" };
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
        "reject_catalog_drift endpoint unavailable (no WORM_CORE_API_URL configured)",
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
  const url = `${base}/api/v1/write_actions/catalog_drifts_reject/${encodeURIComponent(id)}`;
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
      error: `no catalog_drift_proposed entry found for drift_id ${id}`,
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
