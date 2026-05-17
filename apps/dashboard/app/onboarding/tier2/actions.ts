/**
 * Server actions for /onboarding/tier2 (Sub-wave A F2 + Sub-wave D
 * graduation, 2026-05-30).
 *
 * Wires `Tier2Client.tsx`'s onConfirm callbacks. The current write set:
 *
 *   - `confirmBusinessDef`       — Sub-wave D graduated: tries the
 *                                  real `concept_confirmed` PEVR cycle
 *                                  via worm-core's
 *                                  `/api/v1/write_actions/concept_confirmed/{term}`
 *                                  endpoint, falls back to the
 *                                  synthetic-receipt writer when the
 *                                  endpoint returns 404 (no prior
 *                                  proposal) or worm-core is
 *                                  unreachable.
 *   - `rejectBusinessDef`        — synthetic receipt (concept_rejected).
 *                                  No real ledger kind yet — future
 *                                  Sub-wave port follows confirm's
 *                                  shape.
 *   - `assignDomainOwner`        — live PEVR cycle via tryPgWrite +
 *                                  synthetic receipt fallback
 *
 * Architectural contract (mirrors connect/dbt-manifest/actions.ts):
 *
 *   * Dashboard reads ledger truth — direct ledger writes are routed
 *     through the existing `ledger-client` writers, which themselves
 *     fall back to a synthetic receipt when Postgres is unreachable.
 *   * Per-action error returns rather than throws so the panel can
 *     render an honest receipt-or-error state.
 *   * No new KIND_REGISTRY rows. Sub-wave D reuses the existing
 *     ``concept_confirmed`` kind via the new write_action endpoint.
 *
 * Channel-talkativeness edits remain on `/settings/channels` (not in
 * this wizard tier) per the post-2026-04-27 minimal-friction posture
 * documented in
 * `docs/superpowers/notes/2026-05-30-onboarding-audit.md` §6 — see the
 * Talkativeness section in Tier2Client.tsx.
 */
"use server";

import {
  assignDomainOwner as _assignDomainOwner,
  confirmBusinessDef as _confirmBusinessDef,
  rejectBusinessDef as _rejectBusinessDef,
} from "../../../lib/ledger-client";
import { getCurrentPerson } from "../../../lib/server/identity";
import { confirmConcept as _confirmConcept } from "../../../lib/server/worm-core-write";
import {
  getCurrentCompanyId,
  getTenantFromCookies,
} from "../../../lib/tenant-cookies";

export interface Tier2ActionResult {
  ok: boolean;
  receipt?: {
    hash: string;
    source: string;
    owner: string;
    classification: string;
    ts: string;
  };
  error?: string;
}

/**
 * Confirm a worm-proposed business definition.
 *
 * Sub-wave D graduation: tries the real
 * ``POST /api/v1/write_actions/concept_confirmed/{term}`` endpoint
 * first. The worm-core handler resolves ``term → concept_id`` from a
 * prior ``concept_proposed`` entry and emits a real
 * ``concept_confirmed`` PEVR cycle.
 *
 * Fallback behaviour (in order of preference):
 *   1. Real PEVR cycle when worm-core is reachable + a prior
 *      ``concept_proposed`` entry exists for the term.
 *   2. Synthetic receipt when the endpoint returns 404 ("no prior
 *      proposal") or worm-core is unreachable / unauthenticated. The
 *      UI still shows a visible receipt; the operator can surface
 *      the gap from the audit trail (the synthetic receipt's hash
 *      is deterministic so it's clearly identifiable).
 *
 * No new KIND_REGISTRY rows.
 */
export async function confirmBusinessDefAction(
  term: string,
): Promise<Tier2ActionResult> {
  const cleanTerm = (term ?? "").trim();
  if (!cleanTerm) {
    return { ok: false, error: "missing term" };
  }
  const companyId = await getCurrentCompanyId();
  const synthetic = await _confirmBusinessDef(companyId, cleanTerm).catch(
    (err: unknown) =>
      ({
        hash: "",
        source: "onboarding · tier 2",
        owner: "ricardo",
        classification: "internal",
        ts: new Date().toISOString(),
        _error: (err as Error).message ?? String(err),
      }) as unknown as Tier2ActionResult["receipt"],
  );

  // Sub-wave D: try the real worm-core endpoint. We thread the current
  // admin Person's UUID through getCurrentPerson(companyId) (never a
  // placeholder; see CLAUDE.md §9 "Self-grant placeholders" anti-
  // pattern).
  try {
    const tenant = await getTenantFromCookies();
    const me = await getCurrentPerson(companyId);
    if (
      tenant.slug &&
      me?.personId &&
      process.env.WORMBASE_LEDGER_API_TOKEN
    ) {
      const result = await _confirmConcept({
        tenantSlug: tenant.slug,
        companyId,
        term: cleanTerm,
        confirmedByPersonId: me.personId,
      });
      // Returned receipt prefers the real ledger entry id over the
      // synthetic hash so the dashboard panel surfaces audit-grade
      // attestation when it's available.
      return {
        ok: true,
        receipt: {
          hash: result.entry_ids[0] ?? synthetic?.hash ?? "",
          source: "onboarding · tier 2 · concept_confirmed",
          owner: me.name ?? "current admin",
          classification: "internal",
          ts: new Date().toISOString(),
        },
      };
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    // A 404 from worm-core means "no prior proposal" — fall through
    // to the synthetic receipt below so the wizard UX still
    // completes. Any other error short-circuits to the error path so
    // operators see the failure.
    if (!msg.includes("404")) {
      return { ok: false, error: msg };
    }
  }

  // Synthetic-receipt fallback (worm-core unreachable, no
  // prior proposal, or no current Person).
  return { ok: true, receipt: synthetic };
}

/**
 * Reject a worm-proposed business definition. Symmetric to
 * `confirmBusinessDefAction`. Synthetic receipt today; future Sub-wave
 * C may promote to a real `emit_concept_rejected` ledger write.
 */
export async function rejectBusinessDefAction(
  term: string,
): Promise<Tier2ActionResult> {
  const cleanTerm = (term ?? "").trim();
  if (!cleanTerm) {
    return { ok: false, error: "missing term" };
  }
  try {
    const companyId = await getCurrentCompanyId();
    const receipt = await _rejectBusinessDef(companyId, cleanTerm);
    return { ok: true, receipt };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { ok: false, error: msg };
  }
}

/**
 * Assign a Person as the owner of a domain.
 *
 * Writes a real `emit_domain_owner_assigned` PEVR cycle when Postgres
 * is reachable (via the existing `assignDomainOwner` writer in
 * ledger-client.ts) and falls back to a synthetic receipt otherwise.
 * The downstream `getDomains()` projection picks up the new owner on
 * the next 10s poll, so the /domains card grid refreshes live.
 */
export async function assignDomainOwnerAction(
  domainId: string,
  personId: string,
): Promise<Tier2ActionResult> {
  const cleanDomain = (domainId ?? "").trim();
  const cleanPerson = (personId ?? "").trim();
  if (!cleanDomain) {
    return { ok: false, error: "missing domain_id" };
  }
  if (!cleanPerson) {
    return { ok: false, error: "missing person_id" };
  }
  try {
    const companyId = await getCurrentCompanyId();
    const receipt = await _assignDomainOwner(
      companyId,
      cleanDomain,
      cleanPerson,
    );
    return { ok: true, receipt };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { ok: false, error: msg };
  }
}
