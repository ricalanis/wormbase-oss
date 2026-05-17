/**
 * /api/notebooks/{id} — single notebook read + run runs list.
 */
import { NextResponse } from "next/server";
import {
  getNotebook,
  listNotebookRuns,
} from "../../../../lib/server/notebooks";
import { getTenantFromCookies } from "../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const tenant = await getTenantFromCookies();
  const nb = await getNotebook(tenant.companyId, id);
  if (!nb) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }
  const runs = await listNotebookRuns(tenant.companyId, id);
  return NextResponse.json({ notebook: nb, runs });
}
