/**
 * Role-based row filtering helpers.
 *
 * D8 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * Usage from a server-side page:
 *
 *   const me = await getCurrentPerson(companyId);
 *   const allRows = await getKpiTree(companyId);
 *   const visible = filterByDomainAccess(allRows, me, await getDomainAccessSet(companyId, me));
 *
 * For Thursday the access surface is intentionally simple:
 *   - admin / installer  → see every row
 *   - observer           → see every row (read-only — chrome enforces by
 *                          rendering a muted nav)
 *   - member             → see rows whose `domain_id` is in their
 *                          domain.contributor-or-better grants
 *
 * When a Person has no domain grants at all (fresh tenant) the helper
 * returns an empty list for members — rather than nothing-everywhere
 * the page header surfaces a "you don't have access yet" notice via
 * `memberHasNoAccess`.
 */
import type { CurrentPerson } from "./identity";
import { getRolesForPerson } from "../ledger-client";

export type AccessSet = ReadonlySet<string>;

/**
 * Resolve the set of domain_ids a Person has `contributor`-or-better
 * access to. Owners and contributors both qualify; revoked grants are
 * filtered out by getRolesForPerson.
 */
export async function getDomainAccessSet(
  companyId: string,
  me: CurrentPerson | null,
): Promise<AccessSet> {
  if (!me) return new Set();
  if (!me.personId) return new Set();
  try {
    const grants = await getRolesForPerson(companyId, me.personId);
    const domainIds: string[] = [];
    for (const g of grants) {
      if (g.facet !== "domain") continue;
      if (g.role !== "owner" && g.role !== "contributor") continue;
      if (g.scopeId) domainIds.push(g.scopeId);
    }
    return new Set(domainIds);
  } catch {
    return new Set();
  }
}

/**
 * Filter a list of rows that carry a `domain_id` (or domainId, or
 * `domain` keyed by string) by the current Person's role and access
 * set. Admins and observers see everything; members see only rows
 * whose domain is in their grant set.
 */
export function filterByDomainAccess<T>(
  rows: T[],
  me: CurrentPerson | null,
  access: AccessSet,
  fields: string[] = ["domain_id", "domainId", "domain"],
): T[] {
  // The (app)/ layout redirects to /onboarding when there's no current
  // Person; defensively, a null `me` means "no access yet."
  if (!me) return [];
  if (me.tenancyRole === "admin" || me.tenancyRole === "installer") return rows;
  if (me.tenancyRole === "observer") return rows;
  // Member path: filter by domain access. If access is empty we still
  // return [] (the page header explains via memberHasNoAccess).
  return rows.filter((r) => {
    if (typeof r !== "object" || r === null) return false;
    const rec = r as Record<string, unknown>;
    for (const f of fields) {
      const v = rec[f];
      if (typeof v === "string" && access.has(v)) return true;
    }
    return false;
  });
}

/** True when the current Person is a member with zero domain grants. */
export function memberHasNoAccess(
  me: CurrentPerson | null,
  access: AccessSet,
): boolean {
  if (!me) return false;
  return me.tenancyRole === "member" && access.size === 0;
}
