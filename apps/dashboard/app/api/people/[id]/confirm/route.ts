/**
 * POST /api/people/[id]/confirm — confirm a proposed Person.
 *
 * A3.5 — calls worm-core's `POST /api/v1/people/{id}/confirm`, which
 * writes a full PEVR cycle of `emit_person_confirmed`. Failures from
 * worm-core surface as 502; validation failures as 400.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { confirmPerson } from "../../../../../lib/server/worm-core-write";
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
  const confirmedBy = typeof obj.confirmed_by === "string" ? obj.confirmed_by : "";
  if (!confirmedBy) {
    return NextResponse.json(
      { error: "validation_failed", message: "required: confirmed_by (uuid string)" },
      { status: 400 },
    );
  }
  try {
    const result = await confirmPerson(id, {
      tenantSlug: tenant.slug,
      confirmedBy,
    });
    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    return NextResponse.json(
      { error: "worm_core_error", message: (err as Error).message ?? String(err) },
      { status: 502 },
    );
  }
}
