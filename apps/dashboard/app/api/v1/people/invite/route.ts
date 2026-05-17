/**
 * POST /api/v1/people/invite — admin invites a new Person by email.
 *
 * W2.A6 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * The current admin Person (resolved via `getCurrentPerson`) becomes the
 * `proposed_by` on the worm-core ledger entry. The route is bearer-authed
 * via the dashboard's existing tenant cookie; no separate auth header is
 * required from the browser. There is no synthesized "pending" platform
 * shim — `platform` and `platform_user_id` are required fields per the
 * production-onboarding spec.
 *
 * Returns the worm-core `{person_id, entry_ids}` envelope on 201, or the
 * upstream error mapped to the dashboard's 400/401/502 surface.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { getCurrentPerson } from "../../../../../lib/server/identity";
import { proposePerson } from "../../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const tenant = await getTenantFromCookies();
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: "invalid_json", message: "request body must be valid JSON" },
      { status: 400 },
    );
  }
  const obj = (body ?? {}) as Record<string, unknown>;
  const name = typeof obj.name === "string" ? obj.name.trim() : "";
  const email = typeof obj.email === "string" ? obj.email.trim() : "";
  const position =
    typeof obj.position === "string" ? obj.position.trim() : "";
  const platform =
    typeof obj.platform === "string" ? obj.platform.trim() : "";
  const platformUserId =
    typeof obj.platform_user_id === "string"
      ? obj.platform_user_id.trim()
      : "";

  if (!name || !email || !platform || !platformUserId) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message:
          "required: name, email, platform, platform_user_id (all non-empty strings)",
      },
      { status: 400 },
    );
  }

  // Resolve the inviting admin so the ledger entry's `proposed_by`
  // carries a real Person id, not a placeholder.
  const me = await getCurrentPerson(tenant.companyId);
  if (!me) {
    return NextResponse.json(
      {
        error: "not_authenticated",
        message:
          "no current admin Person resolved for tenant; finish onboarding first",
      },
      { status: 401 },
    );
  }

  try {
    const result = await proposePerson({
      tenantSlug: tenant.slug,
      name,
      email,
      platform,
      platformUserId,
      position: position || null,
      proposedBy: me.personId,
    });
    return NextResponse.json(result, { status: 201 });
  } catch (err) {
    return NextResponse.json(
      {
        error: "worm_core_error",
        message: (err as Error).message ?? String(err),
      },
      { status: 502 },
    );
  }
}
