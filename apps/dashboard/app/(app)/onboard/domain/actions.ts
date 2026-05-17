/**
 * Server actions for /onboard/domain — Onboarding Sub-wave C (2026-05-30).
 *
 * Wires the Tier 2 domain pack picker. ``selectDomainPackAction``
 * threads the current admin Person UUID through ``getCurrentPerson`` —
 * never a placeholder, never the picker target as the granter.
 *
 * The pack picker's idempotent contract surfaces honestly to the UI: a
 * re-pick on a tenant that already has a pack-selection returns
 * ``alreadySeeded: true`` so the UI renders an honest "already seeded"
 * receipt rather than re-firing the fan-out.
 */
"use server";

import { revalidatePath } from "next/cache";

import { getCurrentPerson } from "../../../../lib/server/identity";
import { selectDomainPack } from "../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../lib/tenant-cookies";

export interface SelectDomainPackResult {
  ok: boolean;
  packId?: string;
  packVersion?: string;
  alreadySeeded?: boolean;
  domainIds?: string[];
  policyIds?: string[];
  error?: string;
}

export async function selectDomainPackAction(
  packId: string,
  notes?: string,
): Promise<SelectDomainPackResult> {
  const cleanPackId = (packId ?? "").trim().toLowerCase();
  if (!cleanPackId) {
    return { ok: false, error: "missing pack_id" };
  }

  try {
    const tenant = await getTenantFromCookies();
    const me = await getCurrentPerson(tenant.companyId);
    if (!me) {
      return {
        ok: false,
        error:
          "no admin Person could be resolved for this tenant; complete onboarding first",
      };
    }

    const result = await selectDomainPack({
      tenantSlug: tenant.slug,
      companyId: tenant.companyId,
      packId: cleanPackId,
      selectedByPersonId: me.personId,
      notes: notes?.trim() || undefined,
    });

    // The picker landed; force the page to re-fetch the domain list so
    // the seeded domains surface immediately on next render.
    revalidatePath("/onboard/domain");
    revalidatePath("/domains");

    return {
      ok: true,
      packId: result.pack_id,
      packVersion: result.pack_version,
      alreadySeeded: result.already_seeded,
      domainIds: result.domain_ids,
      policyIds: result.policy_ids,
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { ok: false, error: msg };
  }
}
