/**
 * POST /api/v1/reactivities/[id]/confirm — admin confirms a proposed
 * reactivity (W5.A5).
 *
 * Threads the current admin Person id as ``confirmed_by``. Returns 401
 * if no admin Person is resolvable — the install must exist before
 * /reactivities is browsable.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { confirmReactivity } from "../../../../../../lib/server/reactivities";
import { getCurrentPerson } from "../../../../../../lib/server/identity";
import {
  getCurrentCompanyId,
  getTenantFromCookies,
} from "../../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function POST(
  _req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  if (!id) {
    return NextResponse.json(
      { error: "validation_failed", message: "missing reactivity id" },
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
          "no admin Person on this tenant; complete the install before confirming reactivities",
      },
      { status: 401 },
    );
  }

  try {
    const result = await confirmReactivity({
      tenantSlug: tenant.slug,
      reactivityId: id,
      confirmedBy: me.personId,
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
