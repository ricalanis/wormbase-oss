/**
 * GET /api/v1/dashboard/ramp — knowledge-ramp counter gauges (Demo-day P2).
 *
 * Returns the three integer-counted gauges + 60-bucket sparklines folded
 * from the tenant's ledger. The same fold lives in
 * ``apps/worm-core/src/wormbase_core/projections/knowledge_ramp.py``
 * (Python, replay-determinism canonical) and in
 * ``lib/ledger-client.ts::getKnowledgeRampGauges`` (TS, SQL fast-path
 * for SSR). The dashboard's `/dashboard` page calls this route to
 * refresh the gauges via client-side polling without reloading the
 * full RSC tree.
 *
 * Tenancy: resolves company_id from the dashboard's tenant cookie via
 * ``getCurrentCompanyId``. Multi-tenant safe — the SQL path filters
 * every query by company_id; tenants never see each other's rows.
 *
 * Empty-state contract (PRD §7 P2): when no contributing entries exist,
 * the response carries ``count: 0`` per axis with a zero-vector
 * sparkline. The caller renders ``0`` honestly + a hint string. No
 * fixture fallback.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { getKnowledgeRampGauges } from "../../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(_req: NextRequest): Promise<Response> {
  const companyId = await getCurrentCompanyId();
  const payload = await getKnowledgeRampGauges(companyId);
  return NextResponse.json(payload, {
    status: 200,
    headers: { "Cache-Control": "no-store" },
  });
}
