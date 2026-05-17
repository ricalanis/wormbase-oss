/**
 * /api/people — read-only roster + propose-person write.
 *
 * A3 + A3.5 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * GET returns `{persons: PersonRow[]}` for the tenant resolved from the
 * `wormbase-tenant-slug` cookie. The PersonRow shape is folded directly from
 * the canonical identity + role ledger entries written by A1 + A2
 * (`emit_person_proposed`, `emit_person_confirmed`, `emit_person_archived`,
 * `emit_identity_linked` / `emit_identity_unlinked`, `emit_role_assigned` /
 * `emit_role_revoked`, `emit_domain_role_assigned`, `emit_resource_role_assigned`).
 *
 * POST proposes a new Person via worm-core's HTTP write API
 * (`POST /api/v1/people`). The request flows: dashboard route → server-side
 * `lib/server/worm-core-write.ts` → worm-core (port 8910) → ledger.write
 * (full PEVR cycle, hash-chained). The previous A3 stub returned 405 with a
 * note that this would land in A3.5; this is that landing.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { getPeople } from "../../../lib/ledger-client";
import { proposePerson } from "../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function GET() {
  const tenant = await getTenantFromCookies();
  const persons = await getPeople(tenant.companyId);
  return NextResponse.json({ persons });
}

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
  const platform =
    typeof obj.platform === "string" ? obj.platform.trim() : "";
  const platformUserId =
    typeof obj.platform_user_id === "string"
      ? obj.platform_user_id.trim()
      : "";
  if (!name || !platform || !platformUserId) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message:
          "required: name, platform, platform_user_id (all non-empty strings)",
      },
      { status: 400 },
    );
  }
  try {
    const result = await proposePerson({
      tenantSlug: tenant.slug,
      name,
      email: typeof obj.email === "string" ? obj.email : null,
      platform,
      platformUserId,
      position: typeof obj.position === "string" ? obj.position : null,
      proposedBy:
        typeof obj.proposed_by === "string"
          ? obj.proposed_by
          : "dashboard-admin",
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
