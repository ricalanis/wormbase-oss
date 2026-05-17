/**
 * /api/data-products/{id}/consume — POST consumption event via worm-core.
 *
 * Called automatically when the drawer mounts so the consumption trace
 * stays accurate. surface defaults to dashboard.
 */
import { NextResponse } from "next/server";
import { consumeDataProduct } from "../../../../../lib/server/worm-core-write";
import { getCurrentPerson } from "../../../../../lib/server/identity";
import { getTenantFromCookies } from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const tenant = await getTenantFromCookies();
  const me = await getCurrentPerson(tenant.companyId);
  if (!me) {
    // No installer/admin Person yet — surface 401 so the client knows
    // to redirect rather than silently dropping consumption events.
    return NextResponse.json(
      { error: "no_session", message: "no installer/admin grant for this tenant" },
      { status: 401 },
    );
  }
  let body: Record<string, unknown> = {};
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    body = {};
  }
  const surface =
    typeof body.surface === "string" &&
    ["dashboard", "chat", "voice", "export"].includes(body.surface)
      ? (body.surface as "dashboard" | "chat" | "voice" | "export")
      : "dashboard";
  try {
    const result = await consumeDataProduct(id, {
      tenantSlug: tenant.slug,
      consumedByPersonId: me.personId,
      surface,
      channel: typeof body.channel === "string" ? body.channel : null,
    });
    return NextResponse.json({ ok: true, recorded: true, ...result });
  } catch (err) {
    return NextResponse.json(
      { error: "worm_core_error", message: (err as Error).message },
      { status: 502 },
    );
  }
}
