/**
 * GET /api/v1/research/composite_score — Demo-day P1.
 *
 * Reads the canonical composite-score series for the current tenant.
 * Returns a `CompositeScoreSeries` object with ≥9 sampled points
 * across the trailing-window ledger range (default 7 days). Empty
 * `points: []` when no ledger entries exist (no fixture fallback per
 * CLAUDE.md ¶9).
 *
 * Query params:
 *   ?points=<n>         number of points to sample (default 9, min 2)
 *   ?windowDays=<n>     trailing-window length in days (default 7)
 */
import { NextResponse } from "next/server";
import { getCompositeScoreSeries } from "../../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(req: Request) {
  const url = new URL(req.url);
  const pointsRaw = url.searchParams.get("points");
  const windowRaw = url.searchParams.get("windowDays");
  const points = pointsRaw ? Math.max(2, parseInt(pointsRaw, 10) || 9) : 9;
  const windowDays = windowRaw ? Math.max(1, parseInt(windowRaw, 10) || 7) : 7;

  const companyId = await getCurrentCompanyId();
  const series = await getCompositeScoreSeries(companyId, points, windowDays);

  return NextResponse.json({
    ok: true,
    series,
    fetchedAt: Date.now(),
  });
}
