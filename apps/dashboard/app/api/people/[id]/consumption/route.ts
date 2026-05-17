/**
 * /api/people/{id}/consumption — list of data-product consumption events for one Person.
 *
 * F5 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 */
import { NextResponse } from "next/server";
import { listDataProductConsumption } from "../../../../../lib/server/data-products";
import { getTenantFromCookies } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const tenant = await getTenantFromCookies();
  const consumption = await listDataProductConsumption(tenant.companyId, {
    personId: id,
  });
  return NextResponse.json({ consumption });
}
