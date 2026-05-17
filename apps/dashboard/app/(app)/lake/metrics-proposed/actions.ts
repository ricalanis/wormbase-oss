/**
 * Server actions for /lake/metrics-proposed (Wave 3 Task 5).
 *
 * The "Promote" button on the admin queue calls ``promoteSemanticGap`` to
 * register a new metric for the catalog (which, in the worm's normal
 * flow, would land as an ``external_metric_imported`` PEVR cycle keyed
 * by the same ``metric_name`` the gap proposed).
 *
 * Architectural constraint (CLAUDE.md §1):
 *   Dashboard reads ledger truth — it does NOT direct-write the ledger.
 *   The promotion path goes through the worm-core HTTP write API; if
 *   the endpoint is not wired yet, the action returns a stub error so
 *   the surface degrades honestly (admin sees "endpoint v1.1; promote
 *   via the agent-gateway tool for now") rather than silently faking
 *   the write.
 */
"use server";

import { getCurrentCompanyId, getTenantFromCookies } from "../../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../../lib/server/identity";
import { getRolesForPerson } from "../../../../lib/ledger-client";

export interface PromoteSemanticGapResult {
  ok: boolean;
  error?: string;
}

const DEFAULT_WORM_CORE_BASE = "http://worm-core:8910";

function readBase(): string {
  const raw = (
    process.env.WORM_CORE_API_URL ?? process.env.WORMBASE_LEDGER_API_BASE ?? ""
  ).trim();
  return raw.replace(/\/+$/, "");
}

function readToken(): string {
  return (process.env.WORMBASE_LEDGER_API_TOKEN ?? "").trim();
}

/**
 * Admin-only: promote a ``semantic_gap_proposed`` row to a registered
 * metric.
 *
 * Wave 3 surface:
 *
 *   * Verifies the caller holds an unrevoked ``tenancy.admin`` (or
 *     ``tenancy.installer``) grant.
 *   * Forwards to ``${worm-core}/api/v1/lake/metrics-proposed/promote``
 *     when ``WORM_CORE_API_URL`` / ``WORMBASE_LEDGER_API_BASE`` is set.
 *   * Returns ``{ok: false, error: ...}`` honestly when the endpoint is
 *     not yet wired; the queue surfaces the error inline so the admin
 *     knows the action is v1.1.
 *
 * The dashboard NEVER calls the ledger directly — every promotion lands
 * on worm-core's write surface (PEVR-cycled, hash-chained, audit-grade).
 */
export async function promoteSemanticGap(
  semanticGapEntryId: string,
  metricName: string,
  metricExpression: string,
  domainId: string,
): Promise<PromoteSemanticGapResult> {
  // 1. Argument sanity (caller may have come through a form).
  const id = (semanticGapEntryId ?? "").trim();
  const name = (metricName ?? "").trim();
  const expr = (metricExpression ?? "").trim();
  const dom = (domainId ?? "").trim();
  if (!id) return { ok: false, error: "missing semantic_gap_entry_id" };
  if (!name) return { ok: false, error: "missing metric_name" };
  if (!expr) return { ok: false, error: "missing metric_expression" };
  if (!dom) return { ok: false, error: "missing domain_id" };

  // 2. Admin role check (tenancy.admin OR tenancy.installer).
  const companyId = await getCurrentCompanyId();
  const person = await getCurrentPerson(companyId);
  if (!person) {
    return { ok: false, error: "no authenticated person" };
  }
  if (person.tenancyRole !== "admin" && person.tenancyRole !== "installer") {
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
    if (!live.includes("admin") && !live.includes("installer")) {
      return { ok: false, error: "admin role required" };
    }
  }

  // 3. Forward to worm-core write API (the only ledger-write path).
  const base = readBase();
  if (!base) {
    return {
      ok: false,
      error:
        "promote_semantic_gap endpoint v1.1 (no WORM_CORE_API_URL configured)",
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
  const url = `${base}/api/v1/lake/metrics-proposed/promote`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "X-Tenant-Slug": tenant.slug,
      },
      body: JSON.stringify({
        semantic_gap_entry_id: id,
        metric_name: name,
        metric_expression: expr,
        domain_id: dom,
        promoted_by: person.personId,
      }),
      cache: "no-store",
    });
  } catch (e) {
    return { ok: false, error: `network: ${(e as Error).message}` };
  }

  if (res.status === 404) {
    return {
      ok: false,
      error:
        "promote_semantic_gap endpoint v1.1 (worm-core has not exposed " +
        "POST /api/v1/lake/metrics-proposed/promote yet)",
    };
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    return {
      ok: false,
      error: `worm-core API ${res.status}: ${body || res.statusText}`,
    };
  }
  return { ok: true };
}

// Re-export for tests so they can stub the base/token reading.
export const __test__ = {
  readBase,
  readToken,
  DEFAULT_WORM_CORE_BASE,
};
