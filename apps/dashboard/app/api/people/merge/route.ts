/**
 * POST /api/people/merge — merge two Persons into one keeper.
 *
 * A6 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 * Calls worm-core's `POST /api/v1/people/merge`, which writes a
 * *sequence* of independent PEVR cycles (unlink + link per identity +
 * one archive on the mergee). 4xx from validation; 502 from worm-core
 * errors.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { mergePersons } from "../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../lib/tenant-cookies";

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
  const keeperId = typeof obj.keeper_id === "string" ? obj.keeper_id.trim() : "";
  const mergeeId = typeof obj.mergee_id === "string" ? obj.mergee_id.trim() : "";
  const mergedBy = typeof obj.merged_by === "string" ? obj.merged_by.trim() : "";
  if (!keeperId || !mergeeId || !mergedBy) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message: "required: keeper_id, mergee_id, merged_by (all non-empty)",
      },
      { status: 400 },
    );
  }
  if (keeperId === mergeeId) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message: "keeper_id and mergee_id must differ",
      },
      { status: 400 },
    );
  }
  try {
    const result = await mergePersons({
      tenantSlug: tenant.slug,
      keeperId,
      mergeeId,
      mergedBy,
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
