/**
 * GET /api/v1/reactivities/[id]/fires?limit= — last N fires of one
 * reactivity (W5.A5). Proxies to the worm-core endpoint with the
 * tenant header.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { listReactivityFires } from "../../../../../../lib/server/reactivities";
import { getTenantFromCookies } from "../../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  if (!id) {
    return NextResponse.json(
      { error: "validation_failed", message: "missing reactivity id" },
      { status: 400 },
    );
  }
  const url = new URL(req.url);
  const limitRaw = url.searchParams.get("limit");
  const limit = limitRaw ? Number(limitRaw) : 50;

  const tenant = await getTenantFromCookies();
  try {
    const result = await listReactivityFires({
      tenantSlug: tenant.slug,
      reactivityId: id,
      limit: Number.isFinite(limit) ? limit : 50,
    });
    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    // Honest empty: if worm-core is unreachable, the dashboard should
    // still render the "no fires yet" state rather than blowing up.
    return NextResponse.json(
      {
        fires: [],
        error: "worm_core_error",
        message: (err as Error).message ?? String(err),
      },
      { status: 502 },
    );
  }
}
