/**
 * Server-side identity helpers.
 *
 * Two surfaces:
 *
 *   * ``getCurrentPerson(companyId)`` — returns the "current Person" for
 *     the authenticated session, or ``null`` when no installer or admin
 *     grant exists for the tenant. There is no "Unknown / observer"
 *     fallback any more — the production path requires a real Install
 *     row, and the ``(app)/`` layout redirects to ``/onboarding`` when
 *     ``getCurrentInstall`` returns null. Callers under ``(app)/`` can
 *     therefore assume the layout has guarded them; API routes that
 *     run outside the layout must check for null and return 401.
 *
 *   * ``getCurrentInstall(companyId)`` — returns the most recent active
 *     Install row for the tenant (folded from ``emit_install_completed``
 *     − ``emit_install_revoked``), or ``null`` if none exists.
 *
 * The layout uses ``getCurrentInstall`` to decide whether to render the
 * dashboard chrome at all. ``getCurrentPerson`` is the fine-grained
 * "who am I, what role" query for individual surfaces.
 */
import { getInstalls, getPeople, getRolesForPerson } from "../ledger-client";
import type {
  InstallRow,
  PersonRoleGrant,
  PersonRow,
  TenancyRole,
} from "../ledger-client.types";

export interface CurrentPerson {
  personId: string;
  name: string;
  position: string | null;
  tenancyRole: TenancyRole;
}

/**
 * Resolve the "session" Person for the given tenant. Walks the people
 * roster and picks the first Person holding an unrevoked
 * ``tenancy.installer`` (preferred) or ``tenancy.admin`` grant. Returns
 * ``null`` when no such Person exists — the dashboard's ``(app)/``
 * layout redirects to ``/onboarding`` in that case, so callers under
 * the layout can safely treat null as "should never happen."
 */
export async function getCurrentPerson(
  companyId: string,
): Promise<CurrentPerson | null> {
  let people: PersonRow[] = [];
  try {
    people = await getPeople(companyId);
  } catch {
    return null;
  }

  if (people.length === 0) return null;

  const candidate = await pickTopGrantHolder(companyId, people);
  if (!candidate) return null;
  return {
    personId: candidate.personId,
    name: candidate.displayName,
    position: candidate.position,
    tenancyRole: candidate.tenancyRole ?? "observer",
  };
}

/**
 * Resolve the active Install row for the given tenant. The ``(app)/``
 * layout calls this once per render and redirects to ``/onboarding``
 * when the result is null — i.e. the dashboard is not browsable until
 * a real install has landed in the ledger.
 */
export async function getCurrentInstall(
  companyId: string,
): Promise<InstallRow | null> {
  let installs: InstallRow[] = [];
  try {
    installs = await getInstalls(companyId);
  } catch {
    return null;
  }
  // Pick the most recent active install. ``getInstalls`` already drops
  // revoked rows from the active set; if all rows are revoked, treat
  // the tenant as un-installed and let the layout redirect.
  const active = installs.filter((i) => i.status === "active");
  if (active.length === 0) return null;
  // If multiple active installs (one per platform), prefer Slack first
  // to match the demo's day-one platform; otherwise the lexicographic
  // first is deterministic.
  const slackFirst = active.find((i) => i.platform === "slack");
  return slackFirst ?? active[0];
}

/**
 * Walk the roster and pick the first Person whose unrevoked tenancy grants
 * include `installer` (preferred) or `admin` (fallback). The roster is
 * already deterministically ordered (sorted by personId in `getPeople`), so
 * "first" is stable across calls.
 */
async function pickTopGrantHolder(
  companyId: string,
  people: PersonRow[],
): Promise<PersonRow | null> {
  // Fast path: the projected `tenancyRole` field already encodes the
  // highest-priority grant. We can avoid extra round-trips by trusting
  // it for 99% of cases and only fetching detail grants when we need a
  // tiebreaker between two installers.
  const installer = people.find((p) => p.tenancyRole === "installer");
  if (installer) return installer;
  const admin = people.find((p) => p.tenancyRole === "admin");
  if (admin) return admin;

  // No installer/admin via the roster projection — fall back to a per-Person
  // grants probe in case the projection is stale.
  for (const p of people) {
    let grants: PersonRoleGrant[] = [];
    try {
      grants = await getRolesForPerson(companyId, p.personId);
    } catch {
      grants = [];
    }
    const tenancy = grants
      .filter((g) => g.facet === "tenancy" && g.revokedAt === null)
      .map((g) => g.role);
    if (tenancy.includes("installer")) return p;
    if (tenancy.includes("admin")) return p;
  }
  return null;
}
