/**
 * POST /api/people/[id]/roles/[grant_id]/revoke
 *
 * A3.5 — revoke a tenancy-facet role grant via worm-core's
 * `POST /api/v1/people/{id}/roles/{grant_id}/revoke`. Writes a full
 * PEVR cycle of `emit_role_revoked`. The grant_id is forwarded to
 * worm-core for routing symmetry; the projection collapses by
 * (person_id, role).
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { revokeRole } from "../../../../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ id: string; grant_id: string }> },
) {
  const { id, grant_id: grantId } = await ctx.params;
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
  const revokedBy = typeof obj.revoked_by === "string" ? obj.revoked_by : "";
  const role = typeof obj.role === "string" ? obj.role : "";
  if (!revokedBy || !role) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message: "required: revoked_by (uuid), role",
      },
      { status: 400 },
    );
  }
  try {
    const result = await revokeRole(id, grantId, {
      tenantSlug: tenant.slug,
      role,
      revokedBy,
    });
    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    return NextResponse.json(
      { error: "worm_core_error", message: (err as Error).message ?? String(err) },
      { status: 502 },
    );
  }
}
