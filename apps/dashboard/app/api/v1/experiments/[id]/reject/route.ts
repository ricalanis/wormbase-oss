/**
 * POST /api/v1/experiments/[id]/reject — W2.A9.
 *
 * Mirror of /approve with ``outcome=discard``. See approve/route.ts for
 * the architectural notes — the only difference is the verb, the
 * worm-core endpoint, and the resulting ledger ``outcome`` arg.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { rejectExperiment } from "../../../../../../lib/server/worm-core-write";
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
      { error: "validation_failed", message: "missing experiment id" },
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
          "no admin Person on this tenant; complete the install before rejecting experiments",
      },
      { status: 401 },
    );
  }

  let body: Record<string, unknown> = {};
  try {
    body = ((await req.json()) as Record<string, unknown>) ?? {};
  } catch {
    body = {};
  }
  const rationale =
    typeof body.rationale === "string" ? body.rationale : undefined;
  const observedDelta =
    typeof body.observedDelta === "number" ? body.observedDelta : undefined;

  try {
    const result = await rejectExperiment(id, {
      tenantSlug: tenant.slug,
      resolvedBy: me.personId,
      rationale,
      observedDelta,
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
