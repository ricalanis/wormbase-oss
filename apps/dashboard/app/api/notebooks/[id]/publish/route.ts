/**
 * /api/notebooks/{id}/publish — POST publish via worm-core.
 */
import { NextResponse } from "next/server";
import { publishNotebook } from "../../../../../lib/server/worm-core-write";
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
    return NextResponse.json(
      { error: "no_session", message: "no installer/admin grant for this tenant" },
      { status: 401 },
    );
  }
  let body: Record<string, unknown>;
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }
  const runId = typeof body.run_id === "string" ? body.run_id : "";
  const ownerPersonId =
    typeof body.owner_person_id === "string"
      ? body.owner_person_id
      : me.personId;
  const version = typeof body.version === "string" ? body.version : "1";
  const publishedBy = me.personId;
  if (!runId || !ownerPersonId || !publishedBy) {
    return NextResponse.json(
      { error: "validation_failed", message: "run_id + owner_person_id + signed-in admin required" },
      { status: 400 },
    );
  }
  try {
    const result = await publishNotebook(id, {
      tenantSlug: tenant.slug,
      runId,
      ownerPersonId,
      version,
      publishedBy,
      domainId: typeof body.domain_id === "string" ? body.domain_id : null,
    });
    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    return NextResponse.json(
      { error: "worm_core_error", message: (err as Error).message },
      { status: 502 },
    );
  }
}
