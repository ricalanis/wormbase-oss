/**
 * POST /api/v1/people/[id]/position/confirm — admin confirms a worm-proposed position.
 *
 * Wave H Phase 2 Task 2C — Position Auto-Confirm UX.
 *
 * Thin proxy over worm-core's
 * ``POST /api/v1/people/{id}/position/confirm``. The current admin Person
 * — resolved server-side from the tenant cookie — becomes
 * ``confirmed_by`` on the entry; never trusted from the wire.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { getCurrentPerson } from "../../../../../../../lib/server/identity";
import { confirmPositionProposal } from "../../../../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../../../../lib/tenant-cookies";

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
  const position = typeof obj.position === "string" ? obj.position.trim() : "";
  if (!position) {
    return NextResponse.json(
      { error: "validation_failed", message: "required: position (non-empty string)" },
      { status: 400 },
    );
  }

  const me = await getCurrentPerson(tenant.companyId);
  if (!me) {
    return NextResponse.json(
      {
        error: "not_authenticated",
        message:
          "no current admin Person resolved for tenant; finish onboarding first",
      },
      { status: 401 },
    );
  }

  try {
    const result = await confirmPositionProposal(id, {
      tenantSlug: tenant.slug,
      position,
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
