/**
 * /api/notebooks/{id}/run — POST run via worm-core.
 */
import { NextResponse } from "next/server";
import { runNotebook } from "../../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const tenant = await getTenantFromCookies();
  let body: Record<string, unknown> = {};
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    body = {};
  }
  try {
    const result = await runNotebook(id, {
      tenantSlug: tenant.slug,
      runBy: typeof body.run_by === "string" ? body.run_by : "worm",
      timeoutS: typeof body.timeout_s === "number" ? body.timeout_s : 30,
    });
    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    return NextResponse.json(
      { error: "worm_core_error", message: (err as Error).message },
      { status: 502 },
    );
  }
}
