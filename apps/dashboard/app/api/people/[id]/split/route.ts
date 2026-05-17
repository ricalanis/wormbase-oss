/**
 * POST /api/people/[id]/split — split a Person.
 *
 * A6 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 * Calls worm-core's `POST /api/v1/people/{source_person_id}/split`,
 * which writes a propose_person + unlink_identity (seed) plus
 * unlink+link per remaining identity to move. 4xx from validation;
 * 502 from worm-core errors.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { splitPerson } from "../../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

interface RawIdentity {
  platform?: unknown;
  platform_user_id?: unknown;
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
  const newPersonName =
    typeof obj.new_person_name === "string" ? obj.new_person_name.trim() : "";
  const splitBy = typeof obj.split_by === "string" ? obj.split_by.trim() : "";
  const rawIdentities = Array.isArray(obj.identities_to_move)
    ? (obj.identities_to_move as RawIdentity[])
    : [];

  if (!newPersonName || !splitBy || rawIdentities.length === 0) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message:
          "required: new_person_name, split_by, identities_to_move (non-empty array)",
      },
      { status: 400 },
    );
  }

  const identitiesToMove = rawIdentities.map((i) => {
    const platform = typeof i.platform === "string" ? i.platform.trim() : "";
    const platformUserId =
      typeof i.platform_user_id === "string" ? i.platform_user_id.trim() : "";
    return { platform, platformUserId };
  });
  if (identitiesToMove.some((i) => !i.platform || !i.platformUserId)) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message:
          "every identity must carry non-empty platform + platform_user_id",
      },
      { status: 400 },
    );
  }

  try {
    const result = await splitPerson(id, {
      tenantSlug: tenant.slug,
      newPersonName,
      newPersonEmail:
        typeof obj.new_person_email === "string"
          ? obj.new_person_email
          : null,
      newPersonPosition:
        typeof obj.new_person_position === "string"
          ? obj.new_person_position
          : null,
      identitiesToMove,
      splitBy,
    });
    return NextResponse.json(result, { status: 200 });
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
