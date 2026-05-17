import { NextResponse } from "next/server";
import { getKpiTree } from "../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

/**
 * Live KPI tree read for client-side polling. The /kpis React Flow view
 * polls this every 5s during demo runs — that 5s cadence is what makes the
 * worm feel alive: nodes appear as the medallion cascade fires, statuses
 * flip from proposed → connected, confidence ticks up.
 *
 * Forces dynamic rendering (no Next caching) so each tick hits the real
 * ledger projection.
 */
export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  const companyId = await getCurrentCompanyId();
  const root = await getKpiTree(companyId);
  return NextResponse.json({ ok: true, root, fetchedAt: Date.now() });
}
