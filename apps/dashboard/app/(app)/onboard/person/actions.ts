/**
 * Server actions for /onboard/person — Onboarding Sub-wave C (2026-05-30).
 *
 * Wires the Tier 2 co-admin invite form. ``invitePersonAction``
 * threads the current admin Person UUID through ``getCurrentPerson`` —
 * never a placeholder. At least one of email / platform_id must be
 * supplied; the action enforces this client-side AND on the wire (the
 * worm-core endpoint returns 400 if both are absent — defense in
 * depth).
 *
 * The actual ``person_proposed`` → ``person_confirmed`` lifecycle
 * fires when the invitee accepts the signed acceptance URL. This
 * action only emits ``person_invited`` (audit anchor + intent).
 */
"use server";

import { revalidatePath } from "next/cache";

import { getCurrentPerson } from "../../../../lib/server/identity";
import { invitePerson } from "../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../lib/tenant-cookies";

export interface InvitePersonResult {
  ok: boolean;
  inviteeEmail?: string | null;
  inviteePlatformId?: string | null;
  roleIntent?: string;
  error?: string;
}

const _VALID_ROLE_INTENTS = new Set(["admin", "member", "observer"]);

export async function invitePersonAction(
  args: {
    inviteeEmail?: string;
    inviteePlatformId?: string;
    roleIntent?: string;
    notes?: string;
  },
): Promise<InvitePersonResult> {
  const email = (args.inviteeEmail ?? "").trim();
  const platformId = (args.inviteePlatformId ?? "").trim();
  if (!email && !platformId) {
    return {
      ok: false,
      error: "at least one of inviteeEmail or inviteePlatformId must be supplied",
    };
  }

  const roleIntent = (args.roleIntent ?? "member").trim().toLowerCase();
  if (!_VALID_ROLE_INTENTS.has(roleIntent)) {
    return {
      ok: false,
      error: `roleIntent must be one of admin / member / observer; got ${JSON.stringify(roleIntent)}`,
    };
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

    const result = await invitePerson({
      tenantSlug: tenant.slug,
      companyId: tenant.companyId,
      invitedByPersonId: me.personId,
      inviteeEmail: email || null,
      inviteePlatformId: platformId || null,
      roleIntent: roleIntent as "admin" | "member" | "observer",
      notes: args.notes?.trim() || undefined,
    });

    revalidatePath("/onboard/person");
    revalidatePath("/people");

    return {
      ok: true,
      inviteeEmail: result.invitee_email,
      inviteePlatformId: result.invitee_platform_id,
      roleIntent: result.role_intent,
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { ok: false, error: msg };
  }
}
