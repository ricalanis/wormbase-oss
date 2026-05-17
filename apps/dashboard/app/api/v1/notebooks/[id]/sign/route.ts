/**
 * /api/v1/notebooks/{id}/sign — POST sign (publish) via worm-core.
 *
 * W2.A8 of docs/superpowers/plans/2026-04-28-production-hardening.md.
 *
 * "Sign" is the governance-framed publish: an admin Person attests
 * that this notebook run is canonical. worm-core writes
 * `emit_notebook_published` and returns a per-Person signature receipt
 * the dashboard surfaces back to the user.
 *
 * The signed-in admin's `personId` is threaded as `signed_by` — the
 * client cannot pick a different signer (no self-grant placeholders,
 * per the in-project cleanup checklist).
 */
import { NextResponse } from "next/server";
import { signNotebook } from "../../../../../../lib/server/worm-core-write";
import { getCurrentPerson } from "../../../../../../lib/server/identity";
import { getTenantFromCookies } from "../../../../../../lib/tenant-cookies";

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
      {
        error: "no_session",
        message: "no installer/admin grant for this tenant",
      },
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

  if (!runId) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message: "run_id required to sign a notebook run",
      },
      { status: 400 },
    );
  }

  try {
    const result = await signNotebook(id, {
      tenantSlug: tenant.slug,
      runId,
      ownerPersonId,
      version,
      // The signer is always the signed-in admin — never a client-supplied
      // value. This is the governance invariant.
      signedBy: me.personId,
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
