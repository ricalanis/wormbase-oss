/**
 * /api/people/[id] — single Person.
 *
 * A3 (read-only scope) of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * GET returns the folded `PersonRow` for the given person_id, or 404 if no
 * `emit_person_proposed` has ever been written for that id in this tenant.
 */
import { NextResponse } from "next/server";
import { getPersonById } from "../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const companyId = await getCurrentCompanyId();
  const person = await getPersonById(companyId, id);
  if (!person) {
    return NextResponse.json(
      { error: "not_found", message: `no Person with id ${id} in this tenant` },
      { status: 404 },
    );
  }
  return NextResponse.json({ person });
}
