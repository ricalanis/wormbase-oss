/**
 * POST /api/people/[id]/archive — archive a Person.
 *
 * A3.5 — calls worm-core's `POST /api/v1/people/{id}/archive`, which
 * writes a full PEVR cycle of `emit_person_archived`. Failures from
 * worm-core surface as 502; validation failures as 400.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { archivePerson } from "../../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

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
  const archivedBy = typeof obj.archived_by === "string" ? obj.archived_by : "";
  const reason = typeof obj.reason === "string" ? obj.reason.trim() : "";
  if (!archivedBy || !reason) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message:
          "required: archived_by (uuid string), reason (non-empty string)",
      },
      { status: 400 },
    );
  }
  try {
    const result = await archivePerson(id, {
      tenantSlug: tenant.slug,
      archivedBy,
      reason,
    });
    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    return NextResponse.json(
      { error: "worm_core_error", message: (err as Error).message ?? String(err) },
      { status: 502 },
    );
  }
}
