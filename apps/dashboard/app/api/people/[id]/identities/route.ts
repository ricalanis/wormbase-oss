/**
 * /api/people/[id]/identities — read + link.
 *
 * A3 / A3.5 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * GET returns `{identities: PersonIdentityDetailRow[]}` for the given
 * person_id. Folds `emit_person_proposed` (initial identity) +
 * `emit_identity_linked` − `emit_identity_unlinked`.
 *
 * POST attaches a {platform, platform_user_id} to the Person via
 * worm-core's `POST /api/v1/people/{id}/identities`. Full PEVR cycle of
 * `emit_identity_linked` lands in the ledger.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { getIdentitiesForPerson } from "../../../../../lib/ledger-client";
import { linkIdentity } from "../../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const tenant = await getTenantFromCookies();
  const identities = await getIdentitiesForPerson(tenant.companyId, id);
  return NextResponse.json({ identities });
}

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
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
  const platform = typeof obj.platform === "string" ? obj.platform.trim() : "";
  const platformUserId =
    typeof obj.platform_user_id === "string" ? obj.platform_user_id.trim() : "";
  const linkedBy = typeof obj.linked_by === "string" ? obj.linked_by : "";
  if (!platform || !platformUserId || !linkedBy) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message:
          "required: platform, platform_user_id (non-empty), linked_by (uuid)",
      },
      { status: 400 },
    );
  }
  try {
    const result = await linkIdentity(id, {
      tenantSlug: tenant.slug,
      platform,
      platformUserId,
      linkedBy,
    });
    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    return NextResponse.json(
      { error: "worm_core_error", message: (err as Error).message ?? String(err) },
      { status: 502 },
    );
  }
}
