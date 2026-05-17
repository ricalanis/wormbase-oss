/**
 * POST /api/v1/experiments/[id]/approve — W2.A9.
 *
 * Wraps worm-core's ``POST /api/v1/experiments/{id}/approve`` with the
 * dashboard's tenant cookie + current-Person resolution. The button on
 * /research's experiments table calls this endpoint; the worm-core
 * write writes ``emit_experiment_resolved`` with ``outcome=keep``
 * through the canonical PEVR cycle.
 *
 * Body (optional): { rationale?: string, observedDelta?: number }
 *
 * Returns 200 with the worm-core envelope on success, 401 if the
 * current Person can't be resolved (no install in the ledger), 502 on
 * worm-core error.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { approveExperiment } from "../../../../../../lib/server/worm-core-write";
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
          "no admin Person on this tenant; complete the install before approving experiments",
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
    const result = await approveExperiment(id, {
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
