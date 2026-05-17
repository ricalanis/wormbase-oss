/**
 * POST /api/v1/reactivities/[id]/disable — admin disables an active
 * reactivity (W5.A5).
 *
 * Body: { reason: string } — required, surfaced on the disabled card.
 * Threads the current admin Person id as ``disabled_by``.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { disableReactivity } from "../../../../../../lib/server/reactivities";
import { getCurrentPerson } from "../../../../../../lib/server/identity";
import {
  getCurrentCompanyId,
  getTenantFromCookies,
} from "../../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  if (!id) {
    return NextResponse.json(
      { error: "validation_failed", message: "missing reactivity id" },
      { status: 400 },
    );
  }

  let body: Record<string, unknown> = {};
  try {
    body = ((await req.json()) as Record<string, unknown>) ?? {};
  } catch {
    body = {};
  }
  const reason = typeof body.reason === "string" ? body.reason.trim() : "";
  if (!reason) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message: "required: reason (non-empty string)",
      },
      { status: 400 },
    );
  }

  const tenant = await getTenantFromCookies();
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);
  if (!me) {
    return NextResponse.json(
      {
        error: "no_admin_person",
        message:
          "no admin Person on this tenant; complete the install before disabling reactivities",
      },
      { status: 401 },
    );
  }

  try {
    const result = await disableReactivity({
      tenantSlug: tenant.slug,
      reactivityId: id,
      disabledBy: me.personId,
      reason,
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
