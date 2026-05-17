/**
 * /api/v1/data-products/{id}/replay — POST strict-replay via worm-core.
 *
 * W2.A8 of docs/superpowers/plans/2026-04-28-production-hardening.md.
 *
 * This is the production replay path. The dashboard's `<ReplayButton />`
 * posts here; we proxy to worm-core's `POST /api/v1/data-products/{id}/replay`,
 * which re-hashes the original artifact bytes against the pinned
 * source-hashes and refuses to write a new generate cycle if the bytes
 * have drifted.
 *
 * The response's `matches_original` flag drives the "bit-identical
 * content_hash" badge on the data-products drill-in page.
 */
import { NextResponse } from "next/server";
import { replayDataProduct } from "../../../../../../lib/server/worm-core-write";
import { getTenantFromCookies } from "../../../../../../lib/tenant-cookies";

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
    const result = await replayDataProduct(id, {
      tenantSlug: tenant.slug,
      strict: typeof body.strict === "boolean" ? body.strict : true,
      generatedBy:
        typeof body.generated_by === "string" ? body.generated_by : "replay",
    });
    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    const msg = (err as Error).message;
    // worm-core returns 409 with body.error="replay_mismatch" when the
    // strict-mode bytes have drifted. Surface that as a non-2xx so the
    // button can render the drift state explicitly. Other failures
    // collapse to 502 (transient worm-core / network).
    if (msg.includes("replay_mismatch") || msg.includes(" 409")) {
      return NextResponse.json(
        { error: "replay_mismatch", message: msg },
        { status: 409 },
      );
    }
    return NextResponse.json(
      { error: "worm_core_error", message: msg },
      { status: 502 },
    );
  }
}
