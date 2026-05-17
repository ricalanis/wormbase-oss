/**
 * /api/data-products/{id}/regenerate — POST regenerate via worm-core.
 */
import { NextResponse } from "next/server";
import { regenerateDataProduct } from "../../../../../lib/server/worm-core-write";
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
    const result = await regenerateDataProduct(id, {
      tenantSlug: tenant.slug,
      sourceHashes: Array.isArray(body.source_hashes)
        ? (body.source_hashes as string[])
        : [],
      contentsBytesB64:
        typeof body.contents_bytes_b64 === "string"
          ? body.contents_bytes_b64
          : null,
      generatedBy:
        typeof body.generated_by === "string" ? body.generated_by : "worm",
    });
    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    return NextResponse.json(
      { error: "worm_core_error", message: (err as Error).message },
      { status: 502 },
    );
  }
}
