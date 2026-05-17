/**
 * /api/data-products/{id} — single data-product read.
 */
import { NextResponse } from "next/server";
import {
  getDataProduct,
  listDataProductRuns,
  listDataProductConsumption,
} from "../../../../lib/server/data-products";
import { getTenantFromCookies } from "../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const tenant = await getTenantFromCookies();
  const dp = await getDataProduct(tenant.companyId, id);
  if (!dp) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }
  const [runs, consumption] = await Promise.all([
    listDataProductRuns(tenant.companyId, id),
    listDataProductConsumption(tenant.companyId, { dataProductId: id }),
  ]);
  return NextResponse.json({ dataProduct: dp, runs, consumption });
}
