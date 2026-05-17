/**
 * DELETE /api/people/[id]/identities/[platform]/[platform_user_id]
 *
 * A3.5 — detach a {platform, platform_user_id} from a Person via
 * worm-core's `DELETE /api/v1/people/{id}/identities/{platform}/{platform_user_id}`.
 * Writes a full PEVR cycle of `emit_identity_unlinked`.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { unlinkIdentity } from "../../../../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function DELETE(
  req: NextRequest,
  ctx: {
    params: Promise<{
      id: string;
      platform: string;
      platform_user_id: string;
    }>;
  },
) {
  const { id, platform, platform_user_id: platformUserId } = await ctx.params;
  const tenant = await getTenantFromCookies();
  let body: unknown = {};
  try {
    body = await req.json();
  } catch {
    // DELETE bodies are sometimes empty — accept that.
    body = {};
  }
  const obj = (body ?? {}) as Record<string, unknown>;
  const unlinkedBy = typeof obj.unlinked_by === "string" ? obj.unlinked_by : "";
  if (!unlinkedBy) {
    return NextResponse.json(
      { error: "validation_failed", message: "required: unlinked_by (uuid)" },
      { status: 400 },
    );
  }
  try {
    const result = await unlinkIdentity(id, platform, platformUserId, {
      tenantSlug: tenant.slug,
      unlinkedBy,
    });
    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    return NextResponse.json(
      { error: "worm_core_error", message: (err as Error).message ?? String(err) },
      { status: 502 },
    );
  }
}
