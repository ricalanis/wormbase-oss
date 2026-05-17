/**
 * GET /api/v1/research/keep_rate — Demo-day P1.
 *
 * Returns per-scope per-day keep-rate samples for the current tenant.
 * Reads `metrics_keep_rate_published` ledger entries via the
 * `getKeepRateSeries` accessor; empty `[]` array when no publications
 * have landed yet (no fixture fallback per CLAUDE.md ¶9 — the chart
 * renders the empty state honestly).
 *
 * Query params:
 *   ?days=<n>   trailing-window length in days (default 7)
 */
import { NextResponse } from "next/server";
import { getKeepRateSeries } from "../../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(req: Request) {
  const url = new URL(req.url);
  const daysRaw = url.searchParams.get("days");
  const days = daysRaw ? Math.max(1, parseInt(daysRaw, 10) || 7) : 7;

  const companyId = await getCurrentCompanyId();
  const rows = await getKeepRateSeries(companyId, days);

  return NextResponse.json({
    ok: true,
    rows,
    days,
    fetchedAt: Date.now(),
  });
}
