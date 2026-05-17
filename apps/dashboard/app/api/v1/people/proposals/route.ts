/**
 * GET /api/v1/people/proposals — pending position-proposals queue.
 *
 * Wave H Phase 2 Task 2C — Position Auto-Confirm UX.
 *
 * Thin proxy over worm-core's ``GET /api/v1/people/proposals``. The
 * dashboard's ``/people/proposals`` server component fetches this URL
 * to render the admin queue; ``/people`` reads it server-side to compute
 * the notification badge count.
 *
 * Returns the worm-core envelope ``{proposals: PositionProposalRow[]}``
 * unchanged so the queue surface and the badge can share one shape.
 */
import { NextResponse } from "next/server";
import { listPositionProposals } from "../../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function GET() {
  const tenant = await getTenantFromCookies();
  try {
    const result = await listPositionProposals(tenant.slug);
    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    return NextResponse.json(
      {
        error: "worm_core_error",
        message: (err as Error).message ?? String(err),
      },
      { status: 502 },
    );
  }
}
