/**
 * GET /api/v1/reactivities/list — dashboard wrapper for the worm-core
 * reactivities list endpoint (W5.A5).
 *
 * Returns ``{ reactivities: [...] }``. On worm-core failure returns the
 * same shape with ``[]`` so the dashboard renders an honest empty
 * state — same pattern as /mcp/catalog.
 */
import { NextResponse } from "next/server";
import { listReactivities } from "../../../../../lib/server/reactivities";
import { getTenantFromCookies } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function GET() {
  const tenant = await getTenantFromCookies();
  try {
    const result = await listReactivities(tenant.slug);
    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    return NextResponse.json(
      {
        reactivities: [],
        error: "worm_core_error",
        message: (err as Error).message ?? String(err),
      },
      { status: 502 },
    );
  }
}
