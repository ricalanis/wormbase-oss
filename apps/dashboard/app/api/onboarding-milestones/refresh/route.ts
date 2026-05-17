import { NextResponse } from "next/server";
import { getOnboardingMilestones } from "../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

/**
 * Live onboarding-milestones read — Step 2 (proactivity hook) of the canonical
 * product arc. The TimeToAhaPanel polls this every 5s during demo runs so the
 * audience sees milestones tick over in real time.
 *
 * Forces dynamic rendering (no Next caching) so each tick hits the live
 * ledger MIN(ts) projection.
 */
export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  const companyId = await getCurrentCompanyId();
  const milestones = await getOnboardingMilestones(companyId);
  return NextResponse.json({ ok: true, milestones, fetchedAt: Date.now() });
}
