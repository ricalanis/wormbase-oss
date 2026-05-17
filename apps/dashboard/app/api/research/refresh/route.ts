import { NextResponse } from "next/server";
import {
  getExperimentsForUser,
  getHeadlineMetricsHistory,
  getPositionsRegistry,
  getResearchOverview,
} from "../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

/**
 * Live /research read endpoint for client-side polling.
 *
 * /research polls every 10s — the autoresearch loop runs slowly enough that
 * 10s is plenty (loop cadence is 30s in dev, 10min in prod), but new
 * propose / run / resolve entries land within seconds of cycle completion.
 *
 * Returns: tenant overview + (optional) per-user filtered experiments +
 *          (optional) headline metric history for a position.
 *
 * Query params:
 *   ?personId=<uuid>   filter the experiments to this person
 *   ?position=<id>     fetch headline-metric history for this position
 */
export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(req: Request) {
  const companyId = await getCurrentCompanyId();
  const url = new URL(req.url);
  const personId = url.searchParams.get("personId") ?? undefined;
  const position = url.searchParams.get("position") ?? undefined;
  const metricId = url.searchParams.get("metricId") ?? undefined;

  const [overview, registry, experiments, history] = await Promise.all([
    getResearchOverview(companyId),
    getPositionsRegistry(companyId),
    getExperimentsForUser(companyId, personId, 50),
    position
      ? getHeadlineMetricsHistory(companyId, position, metricId)
      : Promise.resolve(null),
  ]);

  return NextResponse.json({
    ok: true,
    overview,
    registry,
    experiments,
    history,
    fetchedAt: Date.now(),
  });
}
