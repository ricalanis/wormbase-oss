/**
 * POST /api/v1/reactivities/propose — dashboard wrapper for the worm-core
 * reactivities propose endpoint (W5.A5).
 *
 * Body: { description: string, proposedBy?: string }
 * Query: ?preview=1 → returns the parsed sketch without persisting.
 *
 * Resolves the current admin Person from cookies + identity helpers and
 * threads it as ``proposed_by`` so the audit row carries provenance.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { proposeReactivity } from "../../../../../lib/server/reactivities";
import { getCurrentPerson } from "../../../../../lib/server/identity";
import {
  getCurrentCompanyId,
  getTenantFromCookies,
} from "../../../../../lib/tenant-cookies";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const tenant = await getTenantFromCookies();
  const companyId = await getCurrentCompanyId();
  const me = await getCurrentPerson(companyId);

  let body: Record<string, unknown> = {};
  try {
    body = ((await req.json()) as Record<string, unknown>) ?? {};
  } catch {
    return NextResponse.json(
      { error: "invalid_json", message: "request body must be valid JSON" },
      { status: 400 },
    );
  }
  const description =
    typeof body.description === "string" ? body.description.trim() : "";
  if (!description) {
    return NextResponse.json(
      {
        error: "validation_failed",
        message: "required: description (non-empty string)",
      },
      { status: 400 },
    );
  }
  const url = new URL(req.url);
  const preview = url.searchParams.get("preview") === "1";

  try {
    const result = await proposeReactivity({
      tenantSlug: tenant.slug,
      description,
      proposedBy: me?.personId ?? "dashboard-admin",
      preview,
    });
    return NextResponse.json(result, { status: preview ? 200 : 201 });
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
